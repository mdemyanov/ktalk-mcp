#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml>=6.0,<7.0"]
# ///
"""check-status-drift.py — opt-in: Status застрял в Draft/Review (git-aware).

Для статей с Статус ∈ {Draft, Review}, чей последний git-коммит старше
--stale-days, печатает WARNING-кандидата на дрейф.

Размерностей проверки две, и они независимы (ADR-008 Д1):
  A. читаемость  — известен ли статус каждой статьи. Git не нужен;
  B. залежалость — не стоит ли Draft/Review дольше --stale-days. Git нужен.
Предусловие вправе отменить только те проверки, которые от него зависят, поэтому
размерность A выполняется всегда: и когда каталог вне рабочего дерева git, и когда в
репозитории ещё нет ни одного коммита, и когда бинаря git нет в PATH. Ни одна из этих
трёх проб прогон не прерывает — они гасят размерность B и записывают свой код возврата.

Exit: 0 — проверка выполнена: чисто, либо найдены кандидаты (advisory), либо размерность
          «залежалость» объявленно пропущена (каталог не под версионным контролем ЛИБО
          в репозитории ещё нет ни одного коммита)
      1 — не смог проверить: frontmatter хотя бы одной статьи не читается (её статус
          неизвестен), ЛИБО вызов git по конкретной статье завершился ошибкой, ЛИБО
          бинаря git нет в PATH (размерность «залежалость» непроверяема). Отсутствие
          git-репозитория сюда НЕ входит — это исход 0 (см. ADR-008 Д3)
      2 — ошибка использования: путь не каталог, неизвестный флаг, PyYAML не установлен
      3 — ЗАРЕЗЕРВИРОВАН, сегодня не используется: возможный будущий hard-fail на
          найденных кандидатов. Ввод потребует нового ADR
"""
from __future__ import annotations
import argparse, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _validate_common import MalformedYamlError, parse_frontmatter, require_yaml

STALE_STATUSES = {"Draft", "Review"}


class _GitCallFailed(Exception):
    """Вызов git по конкретной статье упал или отдал неразбираемый вывод.

    Отличается от «истории нет»: там данных нет по построению, здесь их не удалось
    прочитать. Слияние двух исходов в один `None` — то же, что чинит ADR-008 Д3.
    """


GIT_OK = "ok"
GIT_NO_BINARY = "no-binary"
GIT_NO_REPO = "no-repo"
GIT_NO_COMMITS = "no-commits"


def _git_probe(content_dir: Path) -> str:
    """Одна проба на все предусловия размерности «залежалость» (ADR-008 Д3, редакция 2).

    Ни одна ветка прогон не прерывает: прерывать вправе только тотальные предусловия
    шагов 1-3 (нет PyYAML, неизвестный флаг, путь не каталог), без которых не выполнима
    ни одна размерность. Всё, что выясняется здесь, вправе лишь погасить размерность B
    и записать свой код возврата.

    Исходы:
      GIT_OK          — есть рабочее дерево и есть история;
      GIT_NO_BINARY   — бинаря git нет в PATH: размерность B непроверяема целиком.
                        «Не смог проверить» (exit 1), а не окружение: git — ЧАСТИЧНОЕ
                        предусловие, оно гасит B и не касается A. Прецедент
                        `require_yaml()` относится к тотальным и здесь неприменим;
      GIT_NO_REPO     — каталог не в рабочем дереве: истории не существует, объявленный
                        отказ (exit 0);
      GIT_NO_COMMITS  — рабочее дерево есть, HEAD не разрешается. Тот же объявленный
                        отказ и по той же причине. Проверяется здесь, одной командой
                        уровня репозитория: перебором статей исход был бы одинаков у
                        всех и известен заранее, но `git log` вернул бы ошибку и
                        мис-классифицировал его как «вызов упал».
    """
    try:
        subprocess.run(["git", "-C", str(content_dir), "rev-parse", "--is-inside-work-tree"],
                       check=True, capture_output=True)
    except FileNotFoundError:
        return GIT_NO_BINARY
    except subprocess.CalledProcessError:
        return GIT_NO_REPO
    head = subprocess.run(["git", "-C", str(content_dir), "rev-parse", "--verify", "HEAD"],
                          capture_output=True)
    return GIT_OK if head.returncode == 0 else GIT_NO_COMMITS


def _last_commit_ts(path: Path) -> int | None:
    """Timestamp последнего коммита файла.

    None — коммитов у файла нет: статья новая по построению, залежаться не могла.
    Raises _GitCallFailed — вызов упал или вывод не число: статус проверить не удалось.
    """
    try:
        r = subprocess.run(["git", "-C", str(path.parent), "log", "-1", "--format=%ct", "--", path.name],
                           check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as e:
        detail = " ".join((e.stderr or "").split()) or f"exit {e.returncode}"
        raise _GitCallFailed(f"вызов git не удался — {detail}") from e
    except FileNotFoundError as e:
        # Достижимо только для бинаря, исчезнувшего между пробой и обходом. Код тот же,
        # что у отсутствующего на старте (1) — расщепления одного факта на два кода в
        # зависимости от момента обнаружения больше нет.
        raise _GitCallFailed("бинарь git исчез из PATH во время прогона") from e
    out = r.stdout.strip()
    if not out:
        return None
    try:
        return int(out)
    except ValueError as e:
        raise _GitCallFailed(f"git отдал не timestamp, а {out!r}") from e


def _status_values(fm: dict) -> list[str]:
    for p in (fm or {}).get("properties") or []:
        if isinstance(p, dict) and p.get("name") == "Статус":
            v = p.get("value")
            return v if isinstance(v, list) else [v]
    return []


def main(argv: list[str]) -> int:
    require_yaml()
    ap = argparse.ArgumentParser(description="Detect status drift (Draft/Review stale)")
    ap.add_argument("content_dir", nargs="?", default="content")
    ap.add_argument("--stale-days", type=int, default=14)
    args = ap.parse_args(argv)

    content_dir = Path(args.content_dir)
    if not content_dir.is_dir():
        print(f"ERROR: not a directory: {content_dir}", file=sys.stderr)
        return 2

    # Проба идёт до обхода, но обход под её условие не попадает: размерность
    # «читаемость» от git не зависит ни одним шагом (ADR-008 Д1, Д4).
    probe = _git_probe(content_dir)
    git_ok = probe == GIT_OK
    git_missing = probe == GIT_NO_BINARY
    if probe == GIT_NO_BINARY:
        print(f"{content_dir}/: бинаря git нет в PATH — размерность «залежалость» "
              f"непроверяема; читаемость проверяется  [error]")
    elif probe == GIT_NO_REPO:
        print(f"{content_dir}/: каталог не под версионным контролем (git) — проверка "
              f"залежалости пропущена; читаемость проверяется [INFO]")
    elif probe == GIT_NO_COMMITS:
        print(f"{content_dir}/: в репозитории git нет ни одного коммита — истории не "
              f"существует, проверка залежалости пропущена [INFO]")

    cutoff = time.time() - args.stale_days * 86400
    warned = unreadable = no_history = 0
    for md in content_dir.rglob("*.md"):
        if md.name == "_index.md":
            continue
        try:
            fm = parse_frontmatter(md)
        except MalformedYamlError as e:
            # Статус такой статьи неизвестен — размерность «читаемость» не выполнена.
            # Форма строки — как у format_issues.
            print(f"{e.path}: {e.message}  [error]")
            unreadable += 1
            continue
        if not fm:
            continue
        vals = _status_values(fm)
        if not (set(vals) & STALE_STATUSES):
            continue
        if not git_ok:
            continue  # размерность B объявленно пропущена — это отказ, а не провал
        try:
            ts = _last_commit_ts(md)
        except _GitCallFailed as e:
            print(f"{md}: {e}  [error]")
            unreadable += 1
            continue
        if ts is None:
            no_history += 1
            continue
        if ts < cutoff:
            days = int((time.time() - ts) / 86400)
            print(f"{md}: Статус {vals} не менялся {days}д — кандидат на дрейф [warning]")
            warned += 1

    print(f"\nDrift candidates: {warned}")
    print(f"Статей, по которым проверка не выполнена: {unreadable}")
    if git_ok:
        # Без git размерность B не выполнялась — печатать по ней число значило бы
        # утверждать непроверенное.
        print(f"Статей без истории коммитов: {no_history}")
    return 1 if (unreadable or git_missing) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
