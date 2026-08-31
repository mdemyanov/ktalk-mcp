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
У размерности A три исхода, не два, и ни один из них не молчит (ADR-007 Д1,
`gate-failure-semantics`, «Three gate outcomes»): статус прочитан; frontmatter не читается
(`[error]`, считается в «проверка не выполнена»); статус НЕ ОБЪЯВЛЕН. У третьего исхода четыре
причины, и каждая называется своей строкой: frontmatter не объявлен вовсе; свойства «Статус»
во frontmatter нет; свойство есть, список значений пуст (`value: []`); свойство есть, значение
`null` (`value: null`, `value: [null]` — так пишет Gramax при нерезолвнутом регистре enum,
issue #9, коммит `745c397`). Третий исход — «нечего проверять», а не «не смог проверить»:
отсутствие «Статуса» законно по профилю (`content/.doc-root.yaml` обязательным его не
объявляет, `validate-content.py` не требует). Поэтому он печатает [INFO], кода возврата не
меняет и имеет собственный счётчик — сценарий «The refusal is declared explicitly» спеки
(«the field is not declared, IS EMPTY, or no frontmatter is declared»): объявленный отказ
обязан быть ОБЪЯВЛЕН строкой, а не тишиной. До DEV-119 такая статья уходила в `continue`
молча: 68 статей из 398 на дереве базы `3b9e3ec` — число ПРИБОРА, замеренное прогоном по тому
дереву. Греп по литералу (`grep -q "name: Статус"`, 93 файла, минус 26 `_index.md` явной ветки
ниже) даёт 67 и врёт на единицу в свою пользу: `ADR-076-…-spec.md` цитирует саму команду
замера в блоке кода, и литерал засчитывается статье, у которой свойства нет (DEV-119, DEV-121).
Две причины из четырёх завёл уже DEV-121: `value: [null]` до него оставался тихим `continue`
(список `[None]` истинен), а `value: []` печатался с чужой причиной «нет property».
Предусловие вправе отменить только те проверки, которые от него зависят, поэтому
размерность A выполняется всегда: и когда каталог вне рабочего дерева git, и когда в
репозитории ещё нет ни одного коммита, и когда бинаря git нет в PATH. Ни одна из этих
трёх проб прогон не прерывает — они гасят размерность B и записывают свой код возврата.

Третья размерность — состояние самого предмета (ADR-041 Д2/Д3/Д5, долг Д-1 §7 ADR-043-spec).
Три состояния, те же, что у `validate-content.py`, и объявляются они ТЕМ ЖЕ ключом того же
файла: S1 — каталог есть; S2 — каталога нет и отказ не объявлен (ERROR, 1); S3 —
`documentaryCircuit: absent` в `.nauta-gates.yaml` (громкая строка, 0). Функция чтения ключа
ИМПОРТИРУЕТСЯ у соседа (`documentary_circuit_declaration`), а не переписывается: второй ключ
и второй способ его читать дали бы потребителю два разных ответа на один вопрос.
Замер до правки (DEV-026): `cd $(mktemp -d); git init; uv run scripts/check-status-drift.py`
→ `ERROR: not a directory: content`, EXIT=2 — то есть на реальном проекте без документарного
контура повторялась находка B1, у соседа уже вылеченная.

Exit: 0 — проверка выполнена: чисто, либо найдены кандидаты (advisory), либо размерность
          «залежалость» объявленно пропущена (каталог не под версионным контролем ЛИБО
          в репозитории ещё нет ни одного коммита), либо от предмета объявленно отказались
          (`documentaryCircuit: absent` — S3)
      1 — не смог проверить: frontmatter хотя бы одной статьи не читается (её статус
          неизвестен), ЛИБО вызов git по конкретной статье завершился ошибкой, ЛИБО
          бинаря git нет в PATH (размерность «залежалость» непроверяема), ЛИБО умолчания
          `content/` нет и отказ не объявлен (S2), ЛИБО ключ отказа несёт неизвестное
          значение. Отсутствие git-репозитория сюда НЕ входит — это исход 0 (ADR-008 Д3)
      2 — ошибка использования: путь НАЗВАН вызывающим и каталогом не является, неизвестный
          флаг, PyYAML не установлен. Отсутствие УМОЛЧАНИЯ сюда больше не входит (Д5 ADR-041)
      3 — ЗАРЕЗЕРВИРОВАН, сегодня не используется: возможный будущий hard-fail на
          найденных кандидатов. Ввод потребует нового ADR
"""
from __future__ import annotations
import argparse, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _validate_common import MalformedYamlError, parse_frontmatter, require_yaml

STALE_STATUSES = {"Draft", "Review"}

# S2 — предмета нет, отказ не объявлен (У-4). Маркер несёт ровно первая строка (Д3 ADR-042),
# продолжение — те же две починки, что у соседа: третьим вариантом молчание не является.
S2_MESSAGE = (
    "ERROR: не смог проверить дрейф статусов — каталога content/ в этом дереве нет, и отказ "
    "от него не объявлен.\n"
    "  Почини одним из двух: повтори /nauta:init (запускает bin/init.sh)  — завести контур\n"
    "  (ADR-041 Д1); либо documentaryCircuit: absent в .nauta-gates.yaml — объявить, что\n"
    "  документарного контура у проекта нет (ADR-041 Д3). Молчание третьим вариантом не\n"
    "  является: ни одна статья сейчас на дрейф не проверена."
)

S3_MESSAGE = (
    "контур Д: documentaryCircuit: absent — проверка дрейфа статусов не выполняется "
    "(объявленный\nотказ, ADR-041 Д3, тот же ключ и тот же читатель, что у "
    "validate-content.py)."
)


def _neighbour():
    """Модуль `validate-content.py`, импортированный по пути (имя с дефисом не импортируемо).

    Зачем импорт, а не копия: ключ отказа от контура Д — ОДИН (ADR-041 Д3), и способ его
    читать обязан быть один, иначе расхождение реализаций даёт потребителю два разных ответа
    на один вопрос. Сосед доставляется той же позицией `PAYLOAD_FILES`, что и этот файл
    (§4 ADR-043-spec, п.14 и п.9), поэтому его отсутствие — порча доставки, а не конфигурация.
    """
    import importlib.util

    path = Path(__file__).parent / "validate-content.py"
    spec = importlib.util.spec_from_file_location("_validate_content_neighbour", path)
    if spec is None or spec.loader is None:
        raise FileNotFoundError(path)
    module = importlib.util.module_from_spec(spec)
    # Регистрация ДО exec_module обязательна: `@dataclass` внутри соседа резолвит аннотации
    # через `sys.modules[cls.__module__]`, и без записи падает `AttributeError: 'NoneType'
    # object has no attribute '__dict__'` (замер DEV-026 — первый прогон правки Д-1).
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


# Исход «статус не объявлен» размерности A. Форма строки — как у соседних исходов
# (`<path>: <message>  [<level>]`), уровень INFO и код 0 — по таблице ADR-007 Д1, строка
# «Осознанный отказ … тишина законна, но объявлена строкой». От `[error]`-исхода отличается
# причиной, а не громкостью: там frontmatter НЕ ЧИТАЕТСЯ (не смог проверить), здесь он прочитан
# и «Статуса» в нём нет по праву профиля (нечего проверять).
NO_STATUS_TEMPLATE = (
    "{path}: «Статус» не объявлен ({cause}) — на дрейф не проверяется; свойство не обязательно "
    "по профилю, но исход обязан быть назван, а не пропущен молча  [INFO]"
)
NO_FRONTMATTER_CAUSE = "frontmatter не объявлен"
NO_PROPERTY_CAUSE = "во frontmatter нет property «Статус»"
# Причины DEV-121. Свойство ЕСТЬ, значения у него нет — и это не то же самое, что «свойства
# нет»: сообщать про отсутствие property на статье, где она объявлена, значит утверждать о
# статье неверное. Сценарий «The refusal is declared explicitly» перечисляет оба входа одним
# исходом («the field is not declared, IS EMPTY, or no frontmatter is declared»), поэтому
# уровень и код у всех четырёх причин общие, а строка — своя.
EMPTY_VALUE_CAUSE = "property «Статус» объявлена, её список значений пуст"
NULL_VALUE_CAUSE = "property «Статус» объявлена, её значение — null"


def _status_values(fm: dict) -> list[str]:
    for p in (fm or {}).get("properties") or []:
        if isinstance(p, dict) and p.get("name") == "Статус":
            v = p.get("value")
            return v if isinstance(v, list) else [v]
    return []


def _status_property_declared(fm: dict) -> bool:
    """Объявлено ли во frontmatter само свойство «Статус» — независимо от его значения.

    Второй проход по тому же списку, а не второе возвращаемое значение `_status_values`:
    сигнатуру `_status_values` не трогает ни эта задача, ни ADR-008-spec («Не делать»:
    «Не менять `STALE_STATUSES`, `_status_values`, критерий `ts < cutoff`»). Различить
    «свойства нет» и «свойство есть, значения нет» без этого факта нельзя: у обоих входов
    список объявленных значений пуст.
    """
    return any(
        isinstance(p, dict) and p.get("name") == "Статус"
        for p in (fm or {}).get("properties") or []
    )


def _no_status_cause(fm: dict, vals: list) -> str:
    """Причина исхода «статус не объявлен» — одна из четырёх, ни одна не подменяет другую.

    `value: null` и `value: [null]` дают `vals == [None]`: список ИСТИНЕН, поэтому до
    DEV-121 такая статья не попадала ни под `not vals`, ни под пересечение со
    `STALE_STATUSES` — уходила в `continue` молча при НЕИЗВЕСТНОМ статусе. Класс входа
    штатный: `value: [null]` пишет Gramax, когда регистр значения enum в профиле не
    резолвится (тело коммита `745c397`, issue #9).
    """
    if not fm:
        return NO_FRONTMATTER_CAUSE
    if not _status_property_declared(fm):
        return NO_PROPERTY_CAUSE
    return EMPTY_VALUE_CAUSE if not vals else NULL_VALUE_CAUSE


def main(argv: list[str]) -> int:
    require_yaml()
    ap = argparse.ArgumentParser(description="Detect status drift (Draft/Review stale)")
    ap.add_argument("content_dir", nargs="?", default=None)
    ap.add_argument("--stale-days", type=int, default=14)
    args = ap.parse_args(argv)

    # Д5 ADR-041: адрес, названный вызывающим, и умолчание — разные исходы.
    named_by_caller = args.content_dir is not None
    content_dir = Path(args.content_dir if named_by_caller else "content")
    if named_by_caller and not content_dir.is_dir():
        print(f"ERROR: not a directory: {content_dir}", file=sys.stderr)
        return 2

    try:
        neighbour = _neighbour()
    except (OSError, SyntaxError) as exc:
        reason = " ".join(str(exc).split())
        print(f"ERROR: не смог проверить — scripts/validate-content.py, у которого читается "
              f"объявление отказа от контура Д, не импортируется: {reason}", file=sys.stderr)
        return 1

    gates, gate_issues = neighbour._load_gates(content_dir)
    declared_absent, decl_issues = neighbour.documentary_circuit_declaration(gates)
    for issue in gate_issues + decl_issues:
        print(f"{issue.path}: {issue.message}  [{issue.level}]")
    if any(i.level == "error" for i in gate_issues + decl_issues):
        return 1

    if declared_absent:
        print(S3_MESSAGE)  # S3: объявление сильнее находки, но громкое
        return 0
    if not content_dir.is_dir():
        print(S2_MESSAGE, file=sys.stderr)  # S2
        return 1

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
    warned = unreadable = no_history = no_status = 0
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
        vals = _status_values(fm) if fm else []
        # Критерий исхода — есть ли хоть одно ОБЪЯВЛЕННОЕ значение, а не непустой список:
        # `[None]` (`value: null`, `value: [null]`) непуст, но статуса не несёт (DEV-121).
        declared = [v for v in vals if v is not None]
        if not declared:
            print(NO_STATUS_TEMPLATE.format(path=md, cause=_no_status_cause(fm, vals)))
            no_status += 1
            continue
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
    # Размерность A от git не зависит — число печатается всегда, как и предыдущее.
    print(f"Статей без объявленного «Статуса»: {no_status}")
    if git_ok:
        # Без git размерность B не выполнялась — печатать по ней число значило бы
        # утверждать непроверенное.
        print(f"Статей без истории коммитов: {no_history}")
    return 1 if (unreadable or git_missing) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
