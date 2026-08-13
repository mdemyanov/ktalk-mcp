#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyyaml>=6.0,<7.0",
# ]
# ///
"""validate-profile.py — валидатор manifest'ов профилей.

Проверяет docs/overlays/profiles/*/manifest.yaml на соответствие schema (M1-M10).
Exit codes: 0 — clean; 1 — есть errors; 2 — pyyaml не установлен.
"""
from __future__ import annotations

import argparse
import json as _json
import os as _os
import re as _re
import sys
from pathlib import Path

# Добавляем scripts/ в path для импорта _validate_common
sys.path.insert(0, str(Path(__file__).parent))

from _validate_common import (  # noqa: E402
    Issue,
    MalformedYamlError,
    issue_from_yaml_error,
    parse_frontmatter,
    parse_yaml_file,
    require_yaml,
    format_issues,
)

SECTION_HEADING_RE = _re.compile(r"^## (.+)$", _re.MULTILINE)

PROFILES_ROOT_DEFAULT = Path("docs/overlays/profiles")


def _resolve_plugin_slug(repo_root: Path = Path(".")) -> str:
    """Resolve current plugin slug. Precedence: env PLUGIN_SLUG > marketplace.json > 'project'.

    Inlined (вместо импорта из _init_helpers) чтобы не плодить cycles в тестах.
    """
    env_slug = _os.environ.get("PLUGIN_SLUG", "").strip()
    if env_slug:
        return env_slug
    mf = repo_root / ".claude-plugin" / "marketplace.json"
    if mf.exists():
        try:
            data = _json.loads(mf.read_text(encoding="utf-8"))
            slug = data.get("plugins", [{}])[0].get("name", "")
            if slug:
                return slug
        except (ValueError, KeyError, IndexError):
            pass
    return "project"


def check_m1_manifest_present(profile_dir: Path) -> list[Issue]:
    """M1: профиль содержит manifest.yaml."""
    manifest_path = profile_dir / "manifest.yaml"
    if not manifest_path.exists():
        return [Issue(
            level="error",
            path=str(profile_dir) + "/",
            message="manifest.yaml not found",
        )]
    return []


REQUIRED_FIELDS = [
    "schema_version",
    "name",
    "description",
    "status",
    "subagents",
    "pipelines",
    "content_scaffold",
    "doc_root",
    "operations",
    "compatible_stacks",
]

SUBAGENT_STATUSES = {"core", "optional", "disabled"}
PIPELINE_STATUSES = {"enabled", "optional", "disabled"}


def load_manifest(profile_dir: Path) -> dict | None:
    """Возвращает распарсенный manifest или None, если файла нет.

    MalformedYamlError пропускается наверх: валидатор агрегирует, поэтому Issue
    собирает main() — ошибка на профиль, а не на прогон (ADR-007 Д5).
    """
    manifest_path = profile_dir / "manifest.yaml"
    if not manifest_path.exists():
        return None
    return parse_yaml_file(manifest_path)


def check_m2_required_fields(profile_dir: Path, manifest: dict | None) -> list[Issue]:
    """M2: обязательные поля присутствуют."""
    if manifest is None:
        return []  # M1 уже сообщил
    issues = []
    manifest_path = profile_dir / "manifest.yaml"
    for field in REQUIRED_FIELDS:
        if field not in manifest:
            issues.append(Issue(
                level="error",
                path=str(manifest_path),
                message=f"required field missing: {field}",
            ))
    return issues


SUPPORTED_SCHEMA_VERSIONS = {1}


def check_schema_version_enum(profile_dir: Path, manifest: dict | None) -> list[Issue]:
    """A4: schema_version должен быть из enum {1}."""
    if manifest is None:
        return []
    sv = manifest.get("schema_version")
    if sv is None:
        return []  # M2 уже сообщил
    if sv not in SUPPORTED_SCHEMA_VERSIONS:
        return [Issue(
            level="error",
            path=str(profile_dir / "manifest.yaml"),
            message=f"schema_version: {sv} не поддерживается (ожидается одно из {sorted(SUPPORTED_SCHEMA_VERSIONS)})",
        )]
    return []


def check_m3_name_matches_dir(profile_dir: Path, manifest: dict) -> list[Issue]:
    """M3: name в manifest совпадает с именем папки."""
    name = manifest.get("name")
    if name is None:
        return []  # M2 уже сообщил
    if name != profile_dir.name:
        return [Issue(
            level="error",
            path=str(profile_dir / "manifest.yaml"),
            message=f"name '{name}' не совпадает с именем папки '{profile_dir.name}'",
        )]
    return []


def collect_known_roles(repo_root: Path) -> tuple[set[str], list[Issue]]:
    """Парсит AGENTS.md таблицу 'Каталог ролей'.

    Returns (roles, issues). Issues содержит warning если AGENTS.md exists,
    но '## Каталог ролей' heading не парсится — это сигнал поломанного anchor'а
    (M4 silently skipping — раньше было).
    """
    agents_md = repo_root / "AGENTS.md"
    issues: list[Issue] = []
    if not agents_md.exists():
        return set(), issues  # M4 skipped silently — это OK, AGENTS.md просто нет
    text = agents_md.read_text(encoding="utf-8")
    match = _re.search(r"##\s*Каталог ролей\s*\n(.*?)(?=\n##|\Z)", text, _re.DOTALL)
    if not match:
        # A3: эмит warning — heading anchor сломан, M4 не работает
        issues.append(Issue(
            level="warning",
            path=str(agents_md),
            message="AGENTS.md exists, но '## Каталог ролей' heading не найден; M4 (subagent name validation) skipped",
        ))
        return set(), issues
    table = match.group(1)
    roles = set()
    for line in table.splitlines():
        line = line.strip()
        if not line.startswith("|") or "---" in line or not line.endswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if not cells or cells[0].lower() in ("имя", "name"):
            continue
        roles.add(cells[0])
    if not roles:
        # Heading нашёлся но table пустая — это тоже сигнал
        issues.append(Issue(
            level="warning",
            path=str(agents_md),
            message="'## Каталог ролей' heading найден, но table пуст или не парсится; M4 skipped",
        ))
    return roles, issues


def check_m4_subagent_names(profile_dir: Path, manifest: dict, known_roles: set[str]) -> list[Issue]:
    """M4: имена ролей в subagents объявлены в AGENTS.md."""
    if not known_roles:
        return []  # AGENTS.md отсутствует или без таблицы — M4 пропускаем
    subagents = manifest.get("subagents") or {}
    if not isinstance(subagents, dict):
        return []
    issues = []
    for role in subagents:
        if role not in known_roles:
            issues.append(Issue(
                level="error",
                path=str(profile_dir / "manifest.yaml"),
                message=f"роль '{role}' не объявлена в AGENTS.md (Каталог ролей)",
            ))
    return issues


def collect_known_pipelines(repo_root: Path) -> set[str] | None:
    """Множество pipeline names из commands/pipelines/*.md, либо None -- «не смог проверить».

    Шаг 4 PT-EPIC-14 снял локальную копию плагина, а `commands/pipelines/` живёт в `nauta`,
    до которого валидатор не дотягивается (кэш плагина -- не путь репозитория). Пустое
    множество здесь означало бы «ни один pipeline не существует» и красило бы все семь
    профилей, объявляющих pipelines: три исхода вместо двух, ADR-007 Д1 -- «не смог
    проверить» отличается от «проверил, чисто».
    """
    pipelines_dir = repo_root / ".claude" / "plugins" / _resolve_plugin_slug(repo_root) / "commands" / "pipelines"
    if not pipelines_dir.is_dir():
        return None
    return {p.stem for p in pipelines_dir.glob("*.md")}


def check_m5_pipeline_names(profile_dir: Path, manifest: dict,
                            known_pipelines: set[str] | None) -> list[Issue]:
    """M5: pipelines существуют в commands/pipelines/ или явно disabled."""
    pipelines = manifest.get("pipelines") or {}
    if not isinstance(pipelines, dict):
        return []
    if known_pipelines is None:
        # Реестр pipeline'ов недостижим (нет локальной копии плагина, Шаг 4 PT-EPIC-14).
        # Громко, но не блокирующе: молчание здесь читалось бы как «имена проверены».
        declared = [p for p, s in pipelines.items() if s != "disabled"]
        if not declared:
            return []
        return [Issue(
            level="warning",
            path=str(profile_dir / "manifest.yaml"),
            message=(f"M5 не выполнена: реестр pipeline'ов недостижим "
                     f"(`commands/pipelines/` живёт в плагине `nauta`, локальной копии нет) "
                     f"-- имена {sorted(declared)} НЕ проверены, это не «0 нарушений»"),
        )]
    issues = []
    for pipe, status in pipelines.items():
        if status == "disabled":
            continue  # disabled = stub, OK без файла
        if pipe not in known_pipelines:
            issues.append(Issue(
                level="error",
                path=str(profile_dir / "manifest.yaml"),
                message=f"pipeline '{pipe}' не существует (нет commands/pipelines/{pipe}.md)",
            ))
    return issues


def check_m6_status_enums(profile_dir: Path, manifest: dict) -> list[Issue]:
    """M6: статусы subagents и pipelines — из enum'а."""
    issues = []
    manifest_path = str(profile_dir / "manifest.yaml")
    subagents = manifest.get("subagents") or {}
    if isinstance(subagents, dict):
        for role, status in subagents.items():
            if status not in SUBAGENT_STATUSES:
                issues.append(Issue(
                    level="error",
                    path=manifest_path,
                    message=f"subagents.{role} = '{status}' (ожидается одно из {sorted(SUBAGENT_STATUSES)})",
                ))
    pipelines = manifest.get("pipelines") or {}
    if isinstance(pipelines, dict):
        for pipe, status in pipelines.items():
            if status not in PIPELINE_STATUSES:
                issues.append(Issue(
                    level="error",
                    path=manifest_path,
                    message=f"pipelines.{pipe} = '{status}' (ожидается одно из {sorted(PIPELINE_STATUSES)})",
                ))
    return issues


def check_m7_paths_exist(profile_dir: Path, manifest: dict) -> list[Issue]:
    """M7: content_scaffold и doc_root paths существуют (для status != stub)."""
    if manifest.get("status") == "stub":
        return []  # для stub'ов не проверяем
    issues = []
    manifest_path = str(profile_dir / "manifest.yaml")
    for field in ["content_scaffold", "doc_root"]:
        path_str = manifest.get(field)
        if not path_str or path_str == "./":
            continue  # ./ — допустимый плейсхолдер для stub'ов
        target = profile_dir / path_str
        if not target.exists():
            issues.append(Issue(
                level="error",
                path=manifest_path,
                message=f"{field} '{path_str}' не существует (искал: {target})",
            ))
    return issues


def check_m8_on_value_targets(profile_dir: Path, manifest: dict) -> list[Issue]:
    """M8 (warning): on_value мутации указывают на существующие ключи манифеста."""
    issues = []
    manifest_path = str(profile_dir / "manifest.yaml")
    subagents = manifest.get("subagents") or {}
    pipelines = manifest.get("pipelines") or {}
    init_prompts = manifest.get("init_prompts") or []
    if not isinstance(init_prompts, list):
        return []
    for p in init_prompts:
        if not isinstance(p, dict):
            continue
        on_value = p.get("on_value") or {}
        if not isinstance(on_value, dict):
            continue
        for choice, mutations in on_value.items():
            if not isinstance(mutations, dict):
                continue
            for key in mutations:
                if "." not in key:
                    continue
                section, name = key.split(".", 1)
                if section == "subagents" and name not in subagents:
                    issues.append(Issue(
                        level="warning",
                        path=manifest_path,
                        message=f"init_prompts.{p.get('id', '?')}.on_value.{choice}: '{key}' мутирует unknown subagent '{name}'",
                    ))
                elif section == "pipelines" and name not in pipelines:
                    issues.append(Issue(
                        level="warning",
                        path=manifest_path,
                        message=f"init_prompts.{p.get('id', '?')}.on_value.{choice}: '{key}' мутирует unknown pipeline '{name}'",
                    ))
    return issues


def check_m9_compatible_stacks(profile_dir: Path, manifest: dict, repo_root: Path) -> list[Issue]:
    """M9 (warning): compatible_stacks упоминают существующие overlay'и."""
    stacks = manifest.get("compatible_stacks") or []
    if not isinstance(stacks, list):
        return []
    issues = []
    overlays_root = repo_root / "docs" / "overlays"
    manifest_path = str(profile_dir / "manifest.yaml")
    for s in stacks:
        if s == "*":
            continue
        if not (overlays_root / s).is_dir():
            issues.append(Issue(
                level="warning",
                path=manifest_path,
                message=f"compatible_stacks: '{s}' не существует ({overlays_root}/{s} не найдена)",
            ))
    return issues


def check_m10_status_mismatch(profile_dir: Path, manifest: dict) -> list[Issue]:
    """M10 (warning): status: stable + пустой content_scaffold ИЛИ status: stub + непустой."""
    status = manifest.get("status")
    scaffold = manifest.get("content_scaffold")
    if not scaffold or scaffold == "./":
        scaffold_empty = True
    else:
        target = profile_dir / scaffold
        scaffold_empty = not target.is_dir() or not any(target.iterdir())
    manifest_path = str(profile_dir / "manifest.yaml")
    if status == "stable" and scaffold_empty:
        return [Issue(
            level="warning",
            path=manifest_path,
            message=f"status: stable, но content_scaffold пустой — несоответствие",
        )]
    if status == "stub" and not scaffold_empty:
        return [Issue(
            level="warning",
            path=manifest_path,
            message=f"status: stub, но content_scaffold непустой — возможно status должен быть stable",
        )]
    return []


def _md_body(text: str) -> str:
    """Return markdown body without YAML frontmatter."""
    if not text.startswith("---"):
        return text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return text
    return parts[2]


def _section_names(path: Path) -> set[str]:
    """Return set of '## Heading' names found in markdown body."""
    text = path.read_text(encoding="utf-8")
    body = _md_body(text)
    return {m.group(1).strip() for m in SECTION_HEADING_RE.finditer(body)}


def _super_sections(path: Path) -> set[str]:
    """Return set of section heading names that contain {{super}} in body."""
    text = path.read_text(encoding="utf-8")
    body = _md_body(text)
    sections: list[tuple[str, list[str]]] = []
    for line in body.split("\n"):
        m = SECTION_HEADING_RE.match(line)
        if m:
            sections.append((m.group(1).strip(), []))
        elif sections:
            sections[-1][1].append(line)
    return {name for name, content in sections if "{{super}}" in "\n".join(content)}


def check_m11_overrides(profile_dir: Path, manifest: dict, repo_root: Path) -> list[Issue]:
    """M11: agent_overrides sanity (5 sub-checks).

    M11.1: base prompt exists for each declared override
    M11.2: override source path exists
    M11.3: extends frontmatter matches role name
    M11.4: role not disabled in subagents
    M11.5: {{super}} only in sections that exist in base
    """
    issues: list[Issue] = []
    overrides = manifest.get("agent_overrides") or {}
    if not isinstance(overrides, dict):
        return issues
    base_dir = repo_root / ".claude" / "plugins" / _resolve_plugin_slug(repo_root) / "agents"
    manifest_path = str(profile_dir / "manifest.yaml")
    subagents = manifest.get("subagents") or {}

    for role, override_spec in overrides.items():
        # M11.1: base exists
        base_path = base_dir / f"{role}-agent.md"
        if not base_path.exists():
            issues.append(Issue(
                level="error",
                path=manifest_path,
                message=(
                    f"M11: agent_overrides.{role} declared, but base file not found at "
                    f"{base_path}. Check role name in extends, or create base prompt."
                ),
            ))
            continue

        # M11.2: source path exists
        source = override_spec.get("source") if isinstance(override_spec, dict) else None
        if not source:
            issues.append(Issue(
                level="error",
                path=manifest_path,
                message=f"M11: agent_overrides.{role} missing 'source' field in manifest.",
            ))
            continue
        source_path = profile_dir / source
        if not source_path.exists():
            issues.append(Issue(
                level="error",
                path=manifest_path,
                message=(
                    f"M11: agent_overrides.{role}.source not found: {source_path}. "
                    f"Did you forget to commit the override file?"
                ),
            ))
            continue

        # M11.3: extends matches role
        try:
            fm = parse_frontmatter(source_path)
        except MalformedYamlError as e:
            issues.append(issue_from_yaml_error(e))
            continue
        if fm is None:
            issues.append(Issue(
                level="error",
                path=str(source_path),
                message=f"M11: override at {source_path} has no frontmatter block; 'extends' is required.",
            ))
            continue
        extends_value = fm.get("extends")
        if extends_value != role:
            issues.append(Issue(
                level="error",
                path=str(source_path),
                message=(
                    f"M11: override at {source_path} declares 'extends: {extends_value}', "
                    f"but role is '{role}'. Set extends to '{role}' or move file under "
                    f"agent-overrides/{extends_value}.md."
                ),
            ))

        # M11.4: role not disabled
        if subagents.get(role) == "disabled":
            issues.append(Issue(
                level="error",
                path=manifest_path,
                message=(
                    f"M11: agent_overrides.{role} declared, but subagents.{role}=disabled. "
                    f"Either remove override or set subagents.{role} to core/optional."
                ),
            ))

        # M11.5: {{super}} only in sections that exist in base
        base_sections = _section_names(base_path)
        for section_name in _super_sections(source_path):
            if section_name not in base_sections:
                issues.append(Issue(
                    level="error",
                    path=str(source_path),
                    message=(
                        f"M11: section '## {section_name}' uses {{{{super}}}} but base has "
                        f"no such section. Either remove {{{{super}}}} or rename heading to "
                        f"match base."
                    ),
                ))

    return issues


def check_drift_pairs_schema(profile_dir: Path, manifest: dict) -> list[Issue]:
    """Validates drift_pairs field schema (optional — absence is OK, backward-compat).

    If present:
    - Must be a list
    - Each item must be a dict with 'upstream' (str, len>=1) and 'downstream' (str, len>=1)
    - Optional 'note' (str)
    - No extra keys allowed
    """
    if "drift_pairs" not in manifest:
        return []  # optioanl field — absence is OK
    dp = manifest["drift_pairs"]
    if dp is None:
        return []  # YAML null treated same as absent
    manifest_path = str(profile_dir / "manifest.yaml")
    if not isinstance(dp, list):
        return [Issue(
            level="error",
            path=manifest_path,
            message=f"drift_pairs: должен быть списком (list), получено {type(dp).__name__}",
        )]
    issues = []
    allowed_keys = {"upstream", "downstream", "note"}
    for i, pair in enumerate(dp):
        if not isinstance(pair, dict):
            issues.append(Issue(
                level="error",
                path=manifest_path,
                message=f"drift_pairs[{i}]: должен быть dict, получено {type(pair).__name__}",
            ))
            continue
        for required_key in ("upstream", "downstream"):
            val = pair.get(required_key)
            if val is None:
                issues.append(Issue(
                    level="error",
                    path=manifest_path,
                    message=f"drift_pairs[{i}]: отсутствует обязательный ключ '{required_key}'",
                ))
            elif not isinstance(val, str) or len(val) < 1:
                issues.append(Issue(
                    level="error",
                    path=manifest_path,
                    message=f"drift_pairs[{i}].{required_key}: должен быть непустой строкой",
                ))
        extra_keys = set(pair.keys()) - allowed_keys
        if extra_keys:
            issues.append(Issue(
                level="error",
                path=manifest_path,
                message=f"drift_pairs[{i}]: недопустимые ключи {sorted(extra_keys)} (разрешены: upstream, downstream, note)",
            ))
        note = pair.get("note")
        if note is not None and not isinstance(note, str):
            issues.append(Issue(
                level="error",
                path=manifest_path,
                message=f"drift_pairs[{i}].note: должен быть строкой, получено {type(note).__name__}",
            ))
    return issues


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Validate profile manifests")
    parser.add_argument(
        "profile_dir",
        nargs="?",
        default=None,
        help="Path to single profile dir, or omit to validate all in docs/overlays/profiles/",
    )
    args = parser.parse_args(argv)

    require_yaml()

    if args.profile_dir:
        profile_dirs = [Path(args.profile_dir)]
    else:
        if not PROFILES_ROOT_DEFAULT.is_dir():
            print(f"ERROR: {PROFILES_ROOT_DEFAULT} не существует", file=sys.stderr)
            return 2
        profile_dirs = sorted(p for p in PROFILES_ROOT_DEFAULT.iterdir() if p.is_dir())

    if not profile_dirs:
        print(f"{PROFILES_ROOT_DEFAULT}/: OK (профилей нет — нечего валидировать)")
        return 0

    repo_root = Path.cwd()  # запуск из корня репо
    issues: list[Issue] = []
    known_roles, m4_issues = collect_known_roles(repo_root)
    issues.extend(m4_issues)
    known_pipelines = collect_known_pipelines(repo_root)
    for pd in profile_dirs:
        m1 = check_m1_manifest_present(pd)
        issues.extend(m1)
        if m1:
            continue  # без manifest нечего проверять
        try:
            manifest = load_manifest(pd)
        except MalformedYamlError as e:
            issues.append(Issue(
                level="error",
                path=str(e.path),
                message=f"manifest.yaml is not valid YAML (parse failed) — {e.reason}",
            ))
            continue
        if manifest is None:
            continue  # M1 уже сообщил «manifest.yaml not found»
        issues.extend(check_m2_required_fields(pd, manifest))
        issues.extend(check_schema_version_enum(pd, manifest))
        issues.extend(check_m3_name_matches_dir(pd, manifest))
        issues.extend(check_m4_subagent_names(pd, manifest, known_roles))
        issues.extend(check_m5_pipeline_names(pd, manifest, known_pipelines))
        issues.extend(check_m6_status_enums(pd, manifest))
        issues.extend(check_m7_paths_exist(pd, manifest))
        issues.extend(check_m8_on_value_targets(pd, manifest))
        issues.extend(check_m9_compatible_stacks(pd, manifest, repo_root))
        issues.extend(check_m10_status_mismatch(pd, manifest))
        issues.extend(check_m11_overrides(pd, manifest, repo_root))
        issues.extend(check_drift_pairs_schema(pd, manifest))

    if issues:
        print(format_issues(issues))
        errors = [i for i in issues if i.level == "error"]
        warnings = [i for i in issues if i.level == "warning"]
        print(f"\nErrors: {len(errors)} | Warnings: {len(warnings)}")
        return 1 if errors else 0

    print(f"Profiles: OK ({len(profile_dirs)} проверено)")
    print("\nErrors: 0 | Warnings: 0")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
