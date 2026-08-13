# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyyaml>=6.0",
# ]
# ///
"""_drift_check.py — drift-check algorithm for /pm-review and publish-public.sh (гейт 6d).

Implements check_drift() function per design-spec §3c and parse_bypass_from_commits().

Usage (манифест указан напрямую):
    uv run scripts/_drift_check.py --changed-files <file1> <file2> ...
        --manifest docs/overlays/profiles/<name>/manifest.yaml
        [--bypass-reason "<reason>"]

Usage (манифест резолвится из маркера каталога; --manifest и --doc-root взаимоисключимы):
    uv run scripts/_drift_check.py --changed-files <file1> <file2> ...
        --doc-root content/.doc-root.yaml
        [--profiles-dir docs/overlays/profiles]

Usage (карта зон репозитория; --zones-manifest взаимоисключим и с --manifest, и с --doc-root —
ADR-010 Д3, ADR-010-repo-zone-map-spec.md §2):
    uv run scripts/_drift_check.py --changed-files <file1> <file2> ...
        --zones-manifest docs/zones.yaml

    Строит drift_pairs из каждой kind: derived зоны docs/zones.yaml (пропуская зоны, у которых
    gate целиком состоит из литерала "НЕТ") и передаёт их в check_drift() без изменений.
    Инстансы берутся из поля `pairs` зоны, если оно есть (несколько узких пар одного паттерна —
    см. examples/ в docs/zones.yaml), иначе — из singular `derived_from`/`path` самой зоны.

Exit: 0 — проверка выполнена: чисто, либо WARN-расхождение (soft-fail), либо объявленный INFO-отказ
          (нет --manifest, --doc-root и --zones-manifest; файла .doc-root.yaml нет; в нём нет
          profile:; drift_pairs отсутствует или пуст; docs/zones.yaml без ключа zones/с пустым
          списком; отдельная derived-зона с gate целиком из "НЕТ")
      1 — гейт не смог выполнить проверку: манифест указан, но отсутствует или не парсится,
          ЛИБО .doc-root.yaml существует, но не парсится, ЛИБО profile: объявлен без значения,
          ЛИБО --zones-manifest указан, но файл отсутствует/не парсится, ЛИБО derived-зона с
          gate (не только "НЕТ") без derived_from/path — ни прямо, ни внутри pairs.
          Отсутствующий .doc-root.yaml сюда НЕ входит — это исход 0 (см. ADR-007 Д1, асимметрия).
          Отсутствующий --zones-manifest, наоборот, входит — тот же класс, что и --manifest:
          путь называет проверяемый артефакт, а не место, где декларация может лежать
      2 — ошибка использования или окружения (неизвестный/конфликтующий флаг, PyYAML не установлен)
      3 — ЗАРЕЗЕРВИРОВАН, сегодня не используется: возможный будущий hard-fail на найденный drift.
          Ввод потребует нового ADR (развилка 1 закрыта owner'ом 2026-07-26)

Потребителям сравнивать `!= 0`, а не `== 1`: появление кода 3 не должно их править.

Примечание (TPL-41, PT-EPIC-16): строка про код 2 здесь НАМЕРЕННО отличается от
docstring-формулировки соседнего check-status-drift.py («ошибка использования» — без
«или окружения», ADR-008 Д2 редакция 2). Это не разнобой, который надо выровнять: у
_drift_check.py оба повода кода 2 (неизвестный флаг — использование; отсутствие PyYAML —
окружение) настоящие и независимо достижимые, а «использование или окружение» здесь же и
литеральный контракт ADR-007 Д2. У check-status-drift.py ось «использование/окружение»
не работает вообще (ADR-008 Д1 редакция 2) — там единственный частичный «средовой» повод
(отсутствие бинаря git) переклассифицирован в код 1, а не 2. Формулировки разных скриптов
расходятся потому, что сами скрипты структурно разные, а не потому, что кто-то забыл
править одну докстроку вслед за другой. ADR-007 Д4 прямо ссылается на слово «окружение» из
этого блока («совпадает с «2 — окружение» из Д2, отдельной обработки не требует») — сузить
формулировку здесь означало бы разойтись с текстом уже принятого (Approved, неизменяемого)
ADR-007. См. ADR-008 Д2 (абзац «Расхождение оставлено сознательно»).
"""
from __future__ import annotations

import argparse
import fnmatch
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _validate_common import MalformedYamlError, parse_yaml_file  # noqa: E402


def _matches_pattern(file_path: str, pattern: str) -> bool:
    """Returns True if file_path matches glob pattern.

    Pattern may end with '/' (directory prefix) or contain fnmatch wildcards.
    Examples:
        'content/30-requirements/' matches 'content/30-requirements/foo.md'
        'content/*-module-*/' matches 'content/10-module-01-intro/lesson.md'
        'src/' matches 'src/auth/login.py'
    """
    # Normalise trailing slash patterns to prefix match
    if pattern.endswith("/"):
        # Directory prefix — match any file under that prefix (supports fnmatch globs too)
        # Split pattern into directory part and match
        norm_path = file_path.replace("\\", "/")
        norm_pattern = pattern.rstrip("/")
        # If pattern has wildcards — use fnmatch on path prefix segments
        if "*" in norm_pattern or "?" in norm_pattern or "[" in norm_pattern:
            # Check each prefix of the path against the pattern
            parts = norm_path.split("/")
            for i in range(1, len(parts)):
                prefix = "/".join(parts[:i])
                if fnmatch.fnmatch(prefix, norm_pattern):
                    return True
            return False
        else:
            # Plain prefix check
            return norm_path.startswith(norm_pattern + "/") or norm_path == norm_pattern
    else:
        # Direct fnmatch
        return fnmatch.fnmatch(file_path, pattern)


def check_drift(
    changed_files: list[str],
    drift_pairs: list[dict] | None,
    bypass_reason: str | None = None,
) -> list[dict]:
    """Returns list of {"level": "WARN"|"INFO", "message": str} events.

    Algorithm per design-spec §3c:
    1. drift_pairs is None → INFO skip (absent from manifest)
    2. drift_pairs == [] → INFO skip (empty, e.g. custom profile)
    3. bypass_reason non-empty (after strip) → INFO bypass for each affected pair
    4. bypass_reason empty/whitespace-only → WARN about empty reason + proceed to check
    5. For each pair: if downstream changed AND upstream NOT changed → WARN
    """
    events: list[dict] = []

    # Step 1: drift_pairs absent
    if drift_pairs is None:
        events.append({
            "level": "INFO",
            "message": "no drift_pairs declared, skipping check",
        })
        return events

    # Step 2: drift_pairs empty list
    if len(drift_pairs) == 0:
        events.append({
            "level": "INFO",
            "message": "drift_pairs is empty (custom profile), skipping check",
        })
        return events

    # Step 3 & 4: Normalise bypass
    bypass_active = False
    bypass_reason_stripped: str | None = None
    if bypass_reason is not None:
        stripped = bypass_reason.strip()
        if stripped:
            bypass_active = True
            bypass_reason_stripped = stripped
        else:
            # Empty/whitespace-only bypass reason → WARN
            events.append({
                "level": "WARN",
                "message": "empty skip-drift reason — bypass ignored",
            })

    # Pre-compute matches for all pairs to support chain-change logic
    # A file that is a downstream of pair N but also an upstream of pair M
    # (and pair M's downstream is also changed) is considered "intentionally changed"
    # for the purpose of pair N — suppress WARN.
    pair_data = []
    for pair in drift_pairs:
        if not isinstance(pair, dict):
            pair_data.append(None)
            continue
        upstream_pattern = pair.get("upstream", "")
        downstream_pattern = pair.get("downstream", "")
        if not upstream_pattern or not downstream_pattern:
            pair_data.append(None)
            continue
        downstream_matched = [f for f in changed_files if _matches_pattern(f, downstream_pattern)]
        upstream_matched = [f for f in changed_files if _matches_pattern(f, upstream_pattern)]
        pair_data.append({
            "upstream_pattern": upstream_pattern,
            "downstream_pattern": downstream_pattern,
            "downstream_matched": downstream_matched,
            "upstream_matched": upstream_matched,
        })

    # Step 5: Check each pair
    for i, pd in enumerate(pair_data):
        if pd is None:
            continue
        upstream_pattern = pd["upstream_pattern"]
        downstream_pattern = pd["downstream_pattern"]
        downstream_matched = pd["downstream_matched"]
        upstream_matched = pd["upstream_matched"]

        if not downstream_matched:
            # No downstream changes — no issue
            continue

        if upstream_matched:
            # Both sides changed — no issue
            continue

        # Downstream changed but upstream not changed.
        # Chain-change suppression: if any of the downstream files ALSO appears as upstream
        # in another pair (pair M) where pair M's downstream IS also changed — suppress WARN.
        # This handles cases like domain→roles→runbooks where you update roles+runbooks together.
        suppressed_by_chain = False
        for j, other_pd in enumerate(pair_data):
            if j == i or other_pd is None:
                continue
            # Check if any downstream_matched file is an upstream in pair j
            other_up_pattern = other_pd["upstream_pattern"]
            for f in downstream_matched:
                if _matches_pattern(f, other_up_pattern):
                    # This file is also an upstream of pair j
                    # If pair j's downstream is also changed → suppress
                    if other_pd["downstream_matched"]:
                        suppressed_by_chain = True
                        break
            if suppressed_by_chain:
                break

        if suppressed_by_chain:
            continue

        # Downstream changed but upstream not changed
        if bypass_active and bypass_reason_stripped:
            events.append({
                "level": "INFO",
                "message": (
                    f"drift-check bypassed: {bypass_reason_stripped}. "
                    f"Pair {upstream_pattern}→{downstream_pattern} skipped."
                ),
            })
            continue

        # No valid bypass — emit WARN
        events.append({
            "level": "WARN",
            "message": (
                f"drift detected: {downstream_matched} changed without paired upstream "
                f"{upstream_pattern}. Fix upstream first, or add 'skip-drift: <reason>' "
                f"to commit message."
            ),
            "downstream_files": downstream_matched,
            "upstream_pattern": upstream_pattern,
            "downstream_pattern": downstream_pattern,
        })

    return events


def parse_bypass_from_commits(repo_path: str = ".", base_ref: str = "public") -> str | None:
    """Extract 'skip-drift: <reason>' trailer from commits between base_ref..HEAD.

    Primary format: trailer line 'skip-drift: <reason>' in any commit message.
    Fallback: 'Drift: skip — <reason>' line in last commit body.

    Returns the reason string, or None if no bypass found.
    """
    try:
        result = subprocess.run(
            ["git", "log", f"{base_ref}..HEAD", "--format=%B", "--"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None
        log_body = result.stdout

        # Primary: skip-drift: <reason>
        for line in log_body.splitlines():
            stripped = line.strip()
            if stripped.startswith("skip-drift:"):
                reason = stripped[len("skip-drift:"):].strip()
                return reason  # may be empty string — caller validates

        # Fallback: "Drift: skip — <reason>"
        for line in log_body.splitlines():
            stripped = line.strip()
            if stripped.startswith("Drift: skip —") or stripped.startswith("Drift: skip -"):
                separator = "—" if "—" in stripped else "-"
                parts = stripped.split(separator, 1)
                if len(parts) == 2:
                    return parts[1].strip()

        return None

    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _main(argv: list[str]) -> int:
    """CLI entry point for /pm-review and publish-public.sh (гейт 6d).

    Реализует таблицу шести состояний ADR-007 Д3 и exit-таксономию Д2. Оба YAML-входа
    читаются через _validate_common.parse_yaml_file: подстановка плейсхолдеров идёт до
    парсинга, поэтому не инициализированный `{{...}}`-шаблон — не «сломан» (иначе гейт
    6d обрывал бы публикацию на дереве самого шаблона), а настоящая ошибка YAML
    приходит как MalformedYamlError с причиной.
    """
    parser = argparse.ArgumentParser(description="drift-check for /pm-review")
    parser.add_argument("--changed-files", nargs="*", default=[], metavar="FILE",
                        help="List of changed files (from git diff --name-only)")
    parser.add_argument("--manifest", metavar="PATH",
                        help="Path to profile manifest.yaml with drift_pairs")
    parser.add_argument("--doc-root", metavar="PATH",
                        help="Path to <catalog>/.doc-root.yaml. Профиль читается из поля "
                             "profile:, манифест резолвится как "
                             "<profiles-dir>/<profile>/manifest.yaml. Взаимоисключим с --manifest")
    parser.add_argument("--profiles-dir", metavar="PATH", default="docs/overlays/profiles",
                        help="Корень профилей для резолва --doc-root "
                             "(default: docs/overlays/profiles)")
    parser.add_argument("--zones-manifest", metavar="PATH",
                        help="Путь к docs/zones.yaml. Строит drift_pairs из kind: derived зон "
                             "(кроме тех, у которых gate целиком состоит из 'НЕТ') и передаёт "
                             "их в check_drift() без изменений. Взаимоисключим с --manifest и "
                             "--doc-root (ADR-010 Д3)")
    parser.add_argument("--bypass-reason", default=None,
                        help="Bypass reason (from skip-drift: trailer)")
    parser.add_argument("--base-ref", default="public",
                        help="Git base ref for commit log parsing (default: public)")
    args = parser.parse_args(argv)

    # Взаимоисключимость флагов — usage, поэтому exit 2, а не 1 (ADR-007 Д4 / ADR-010 Д3).
    # Тихий приоритет одного над другим — тот же класс дефекта, что чинит этот гейт. Любые
    # ДВА из трёх (--manifest, --doc-root, --zones-manifest) → parser.error.
    provided_flags = []
    if args.manifest:
        provided_flags.append("--manifest")
    if args.doc_root:
        provided_flags.append("--doc-root")
    if args.zones_manifest:
        provided_flags.append("--zones-manifest")
    if len(provided_flags) > 1:
        parser.error(
            f"{' and '.join(provided_flags)} are mutually exclusive: pass exactly one of "
            f"--manifest (direct manifest path), --doc-root (resolved from the 'profile:' "
            f"marker), or --zones-manifest (repo zone map, ADR-010)"
        )

    bypass = args.bypass_reason
    if bypass is None:
        bypass = parse_bypass_from_commits(base_ref=args.base_ref)

    # --zones-manifest — отдельная ветка (ADR-010 Д3, spec §2): читает docs/zones.yaml,
    # строит drift_pairs из derived-зон и передаёт check_drift() без изменения сигнатуры.
    # Возвращается независимо от манифест/doc-root резолва ниже — флаги взаимоисключимы.
    if args.zones_manifest:
        zones_path = Path(args.zones_manifest)
        # Существование проверяется ЯВНО, как у --manifest (ADR-010 spec §2): путь называет
        # проверяемый артефакт, а не место, где декларация МОЖЕТ лежать (это --doc-root).
        if not zones_path.exists():
            print(f"[ERROR] {zones_path}: zones manifest not found — drift-check not "
                  f"performed (restore docs/zones.yaml, or drop --zones-manifest)")
            return 1
        try:
            zones_doc = parse_yaml_file(zones_path)
        except MalformedYamlError as e:
            print(f"[ERROR] {e} — drift-check not performed (fix the YAML)")
            return 1

        zones = zones_doc.get("zones") if isinstance(zones_doc, dict) else None
        if not zones:
            print(f"[INFO] {zones_path}: no zones declared, skipping drift-check")
            return 0

        drift_pairs: list[dict] = []
        hard_fail = False
        for z in zones:
            if not isinstance(z, dict) or z.get("kind") != "derived":
                continue
            zpath = z.get("path", "<unnamed>")
            gate = z.get("gate")
            gate_list = gate if isinstance(gate, list) else [gate]
            if gate_list and all(g == "НЕТ" for g in gate_list):
                print(f"[INFO] {zpath}: gate declared НЕТ, skipping drift-check for this zone")
                continue
            # `pairs` — несколько узких инстансов одного паттерна (examples/ в
            # docs/zones.yaml); singular derived_from/path — обычная одна пара.
            instances = z.get("pairs") or [
                {"derived_from": z.get("derived_from"), "path": z.get("path")}
            ]
            for inst in instances:
                if not isinstance(inst, dict):
                    inst = {}
                derived_from, path = inst.get("derived_from"), inst.get("path")
                if not derived_from or not path:
                    print(
                        f"[ERROR] {zpath}: kind=derived, gate={gate!r}, но derived_from/path "
                        f"(прямо или внутри pairs) не заданы — drift-check для зоны не выполнен"
                    )
                    hard_fail = True
                    continue
                drift_pairs.append({"upstream": derived_from, "downstream": path})

        if hard_fail:
            # «Не смог проверить» перевешивает любой исход ниже — ADR-007 Д1, безусловно.
            return 1

        events = check_drift(args.changed_files, drift_pairs, bypass)
        for event in events:
            level = event.get("level", "INFO")
            msg = event.get("message", "")
            print(f"[{level}] {msg}")
        # WARN здесь тоже soft-fail — та же политика ADR-007 Д1, эта ветка её не меняет.
        return 0

    manifest_path: Path | None = None

    if args.doc_root:
        doc_root_path = Path(args.doc_root)
        # Существование НЕ проверяется намеренно: parse_yaml_file отдаёт {} на
        # несуществующем пути, и это и есть «нечего проверять». --doc-root называет МЕСТО,
        # где декларация может лежать, а не сам проверяемый артефакт (ADR-007 Д1).
        try:
            doc_root = parse_yaml_file(doc_root_path)
        except MalformedYamlError as e:
            # Д3, строка 6. Иначе вывод «профиля нет» был бы добыт из ошибки чтения —
            # ровно то, что запрещает BR-003.
            print(f"[ERROR] {e} — cannot resolve profile, drift-check not performed "
                  f"(fix the YAML, or drop --doc-root if this catalog declares no profile)")
            return 1

        # Тоже строка 6 по существу: YAML валиден, но это не отображение. Частая опечатка —
        # `profile` без двоеточия: safe_load отдаёт строку, и .get() ниже дал бы
        # AttributeError с traceback вместо вердикта гейта (NFR-002).
        if not isinstance(doc_root, dict):
            print(f"[ERROR] {doc_root_path}: YAML is not a mapping "
                  f"({type(doc_root).__name__}) — cannot resolve profile, drift-check not "
                  f"performed (expected 'key: value' lines, e.g. 'profile: project')")
            return 1

        if "profile" not in doc_root:
            # Д3, строки 1-2: файла нет / поля нет. Оба — «объявления нет», объявленный
            # отказ: INFO + exit 0, но со строкой в выводе, а не молча.
            reason = "file not found" if not doc_root_path.exists() else "no 'profile:' marker"
            print(f"[INFO] {doc_root_path}: {reason} — no profile declared, skipping drift-check")
            return 0

        profile = doc_root.get("profile")
        if not isinstance(profile, str) or not profile.strip():
            # Д3, строка 5. Источник истины — таблица, а не сокращённая формулировка Д2:
            # не-строка (list/int) попадает в ту же ветку, что и `profile:` без значения.
            print(f"[ERROR] {doc_root_path}: 'profile:' declared without a usable value "
                  f"({profile!r}) — cannot resolve manifest, drift-check not performed "
                  f"(name the profile, e.g. 'profile: project', or remove the line entirely)")
            return 1

        manifest_path = Path(args.profiles_dir) / profile.strip() / "manifest.yaml"
    elif args.manifest:
        manifest_path = Path(args.manifest)

    drift_pairs: list[dict] | None = None

    if manifest_path is not None:
        # Существование проверяется ЯВНО (асимметрия с --doc-root, ADR-007 Д1/Д4):
        # parse_yaml_file вернул бы {} и склеил «файла нет» с «файл пустой».
        if not manifest_path.exists():
            # Д3, строка 4: конфигурация назвала артефакт, а его нет.
            print(f"[ERROR] {manifest_path}: manifest not found — drift-check not performed "
                  f"(restore the manifest, or drop the 'profile:' marker in .doc-root.yaml)")
            return 1
        try:
            manifest = parse_yaml_file(manifest_path)
        except MalformedYamlError as e:
            print(f"[ERROR] {e} — drift-check not performed (fix the YAML, or drop the "
                  f"'profile:' marker in .doc-root.yaml)")
            return 1
        # Тот же класс, что и у .doc-root.yaml выше: валидный YAML, но не отображение.
        if not isinstance(manifest, dict):
            print(f"[ERROR] {manifest_path}: YAML is not a mapping "
                  f"({type(manifest).__name__}) — cannot read drift_pairs, drift-check not "
                  f"performed (fix the manifest, or drop the 'profile:' marker in .doc-root.yaml)")
            return 1
        # None, если ключа нет: законный INFO-skip внутри check_drift (AC-006
        # spdd-integration, backward-compat для pre-SPDD потомков).
        drift_pairs = manifest.get("drift_pairs")

    events = check_drift(args.changed_files, drift_pairs, bypass)

    for event in events:
        level = event.get("level", "INFO")
        msg = event.get("message", "")
        print(f"[{level}] {msg}")

    # Проверка ВЫПОЛНЕНА — exit 0, даже если найдено расхождение: WARN остаётся soft-fail
    # (ADR-007 Д1, развилка 1). Расхождение — суждение, а не факт: skip-drift-trailer,
    # hotfix-исключение и chain-suppression существуют потому, что часть расхождений
    # легальна. Hard-fail на WARN потребует нового ADR и кода 3.
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
