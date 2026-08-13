#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyyaml>=6.0,<7.0",
# ]
# ///
"""_apply_profile.py — читает profile manifest.yaml, эмиттит JSON ops plan на stdout.

Используется apply-overlay.sh в --profile режиме как one-shot helper
(вместо ×5 subprocess shells per operation в Wave 2).

CLI:
    python3 scripts/_apply_profile.py <profile-dir> [--init]

Output (stdout): JSON {"profile": str, "init": bool, "ops": [{"op": ..., ...}]}
Exit codes: 0 — clean; 1 — error (manifest invalid, mutation failure); 2 — pyyaml missing.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _validate_common import MalformedYamlError, parse_yaml_file, require_yaml  # noqa: E402

# A6: named constant вместо magic 500.
# 500B: scaffold _index.md entries обычно <200B; threshold даёт 2× headroom
# до перехода в "real content" зону.
BASELINE_CONTENT_MAX_BYTES = 500


class ProfileError(Exception):
    """Profile manifest load/parse/mutation error — caller should catch and exit cleanly."""


# Backwards-compat alias (W4a callers использовали ManifestError)
ManifestError = ProfileError


def load_manifest(profile_dir: Path) -> dict:
    """Читает manifest.yaml; raises ProfileError если parse failed или manifest отсутствует."""
    manifest_path = profile_dir / "manifest.yaml"
    if not manifest_path.exists():
        raise ProfileError(f"{manifest_path} не найден")
    try:
        return parse_yaml_file(manifest_path)
    except MalformedYamlError as e:
        # Мутатор прерывается — работать по нечитаемому входу нельзя (ADR-007 Д5).
        raise ProfileError(str(e)) from e


def is_baseline_file(path: Path) -> bool:
    """Файл считается baseline если: пустой, имеет placeholder, или _index.md < BASELINE_CONTENT_MAX_BYTES.

    A6: symlinks count as content (не baseline) если не _index.md/.gitkeep.
    """
    if not path.exists():
        return True
    if path.is_symlink():
        # A6: symlink — non-baseline (избегаем follow-чужих-указателей)
        return path.name in (".gitkeep",)  # symlink на .gitkeep допустим
    if path.is_file():
        try:
            size = path.stat().st_size
        except OSError:
            return False
        if size == 0:
            return True
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            return False
        if "{{" in text:
            return True
        if path.name == "_index.md" and size < BASELINE_CONTENT_MAX_BYTES:
            return True
        return False
    return False


def is_safe_to_delete(target: Path) -> bool:
    """Папка safe to delete если содержит только baseline content (_index.md + .gitkeep)."""
    if not target.exists():
        return True  # уже нет — OK
    if target.is_file():
        return is_baseline_file(target)
    if not target.is_dir():
        return False
    for entry in target.rglob("*"):
        if entry.is_dir():
            continue
        name = entry.name
        if name == ".gitkeep":
            continue
        if name == "_index.md" and is_baseline_file(entry):
            continue
        return False
    return True


def compute_verdict(op: dict, init: bool) -> str:
    """Возвращает verdict: 'add', 'replace', 'safe' или 'refuse'.

    Других значений функция не возвращает: гейт двухпозиционный — либо операция
    разрешена, либо отклонена, а обход делается флагом `--force` на стороне
    apply-overlay.sh, а не третьим вердиктом.
    """
    op_type = op.get("op")
    if op_type in ("add", "replace"):
        return op_type  # просто маркер, без safety check
    if op_type == "delete":
        raw_target = op.get("target", "")
        if not raw_target:
            print(f"WARNING: delete op missing 'target': {op}", file=sys.stderr)
            return "refuse"
        target = Path(raw_target)
        if init:
            return "safe"  # init mode skip strict check (передаст --force в op_delete)
        if is_safe_to_delete(target):
            return "safe"
        return "refuse"
    return "unknown"


def apply_on_value_mutations(manifest: dict) -> None:
    """Применяет on_value мутации к manifest in-memory.

    Читает INIT_PROMPT_<id> env vars, ищет соответствующий init_prompt,
    проверяет value против choices, применяет mutations (dotted path → value).

    Mutations НЕ персистятся в файл — только in-memory.
    """
    init_prompts = manifest.get("init_prompts") or []
    if not isinstance(init_prompts, list):
        return

    for prompt in init_prompts:
        if not isinstance(prompt, dict):
            continue
        prompt_id = prompt.get("id")
        if not prompt_id:
            continue

        env_key = f"INIT_PROMPT_{prompt_id}"
        value = os.environ.get(env_key)
        if value is None or value == "":
            value = prompt.get("default", "")

        if not value:
            continue

        # Validate enum choices
        prompt_type = prompt.get("type", "string")
        if prompt_type == "enum":
            choices = prompt.get("choices") or []
            if value not in choices:
                raise ProfileError(
                    f"{env_key}={value!r} не в choices {choices}"
                )

        on_value = prompt.get("on_value") or {}
        if not isinstance(on_value, dict):
            continue
        mutations = on_value.get(value)
        if not isinstance(mutations, dict):
            continue

        for dotted_path, new_value in mutations.items():
            apply_dotted_mutation(manifest, dotted_path, new_value)


def apply_dotted_mutation(manifest: dict, dotted_path: str, new_value) -> None:
    """Применяет mutation по dotted-path (например 'subagents.compliance' → 'core').

    Raises ProfileError если path не существует (защита от typo в manifest).
    """
    parts = dotted_path.split(".")
    if len(parts) < 2:
        raise ProfileError(
            f"invalid dotted path '{dotted_path}' (нужно минимум section.key)"
        )
    section_name, key = parts[0], ".".join(parts[1:])
    section = manifest.get(section_name)
    if not isinstance(section, dict):
        raise ProfileError(
            f"section '{section_name}' не существует в manifest или не dict"
        )
    if key not in section:
        raise ProfileError(
            f"'{dotted_path}' не существует в manifest (нет ключа '{key}' в '{section_name}')"
        )
    section[key] = new_value


def emit_plan(manifest: dict, init: bool) -> dict:
    """Формирует ops plan структуру для последующего вывода JSON."""
    ops = manifest.get("operations") or []
    plan_ops = []
    for op_decl in ops:
        if not isinstance(op_decl, dict):
            continue
        op_type = op_decl.get("op")
        if not op_type:
            # Skip malformed op entry; warn to stderr
            print(f"WARNING: skipping op without 'op' field: {op_decl}", file=sys.stderr)
            continue
        # Strip newlines: multiline reason ломает \x1f TSV separator в bash consume
        reason = (op_decl.get("reason") or "").replace("\n", " ").replace("\r", " ").strip()
        plan_ops.append({
            "op": op_type,
            "source": op_decl.get("source", ""),
            "target": op_decl.get("target", ""),
            "reason": reason,
            "verdict": compute_verdict(op_decl, init),
        })
    # Шаг 4 PT-EPIC-14: op `resolve_agents` больше не эмитится. Он писал слитые промты
    # в `.claude/plugins/<slug>/agents/` -- каталог локальной копии плагина, удалённой
    # этим шагом. Второго приёмника у резолвера не было, а сама копия была выключена в
    # поставке с `0e80830`, поэтому per-profile override не действовал ни у одного
    # потомка ещё до удаления: снимается инертный механизм, не работающий.
    # Оживление на платформенном пути (`.claude/agents/`, лестница приоритетов PD-27)
    # требует зонда -- PD-27 наполовину опровергнут живым замером, см. TPL-104.
    return {
        "profile": manifest.get("name", ""),
        "init": init,
        "ops_count": len(plan_ops),
        "ops": plan_ops,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Profile apply helper — emits JSON ops plan")
    parser.add_argument("profile_dir", help="Path to docs/overlays/profiles/<name>/")
    parser.add_argument("--init", action="store_true", help="Fresh init mode (relax strict delete check)")
    args = parser.parse_args(argv)

    require_yaml()

    profile_dir = Path(args.profile_dir)
    if not profile_dir.is_dir():
        print(f"ERROR: profile dir не существует: {profile_dir}", file=sys.stderr)
        return 1

    try:
        manifest = load_manifest(profile_dir)
        apply_on_value_mutations(manifest)  # T6: env-driven mutations
    except ProfileError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    plan = emit_plan(manifest, args.init)

    print(json.dumps(plan, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
