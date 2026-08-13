#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "pyyaml>=6.0,<7.0",
# ]
# ///
"""_init_helpers.py — helper для init.sh: парсинг manifest.yaml, форматирование меню.

Subcommands:
  list-profiles           — JSON-массив профилей {name, description, audience, status}
  menu-max-len            — max длина name из JSON на stdin
  menu-format --max-len N — форматированные строки меню из JSON на stdin
  profile-summary <prof>  — bulleted summary профиля
  init-prompts <prof>     — JSON-массив prompt-объектов
  prompt-field <i> <fld>  — значение поля prompt по индексу (JSON на stdin)
  compat-stacks <prof>    — compatible_stacks через запятую

CLI: uv run scripts/_init_helpers.py <subcommand> [args...]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys


def load_manifest(profile: str) -> dict:
    """Загрузить manifest.yaml для профиля."""
    import yaml  # noqa: PLC0415
    mf = f"docs/overlays/profiles/{profile}/manifest.yaml"
    try:
        with open(mf, encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        print(f"Warning: cannot read manifest for profile {profile!r}: {e}", file=sys.stderr)
        return {}


def cmd_list_profiles(args: argparse.Namespace) -> None:
    """list-profiles: JSON-массив профилей, отсортированных (project first, stable alphabetically)."""
    import yaml  # noqa: PLC0415
    profiles = []
    for mf in glob.glob("docs/overlays/profiles/*/manifest.yaml"):
        try:
            with open(mf, encoding="utf-8") as f:
                m = yaml.safe_load(f) or {}
            profiles.append({
                "name":        m.get("name", os.path.basename(os.path.dirname(mf))),
                "description": m.get("description", ""),
                "audience":    m.get("audience") or "",
                "status":      m.get("status", "stable"),
            })
        except Exception:
            pass  # битый manifest — пропустить без crash

    def sort_key(p: dict) -> tuple:
        if p["name"] == "project":
            return (0, "")
        if p["status"] == "stable":
            return (1, p["name"])
        return (2, p["name"])

    profiles.sort(key=sort_key)
    print(json.dumps(profiles))


def cmd_menu_max_len(args: argparse.Namespace) -> None:
    """menu-max-len: max длина name из JSON на stdin."""
    try:
        ps = json.load(sys.stdin)
        print(max(len(p["name"]) for p in ps) if ps else 7)
    except Exception:
        print(7)


def cmd_menu_format(args: argparse.Namespace) -> None:
    """menu-format --max-len N: форматированные строки меню из JSON на stdin.

    Три исхода различаются (TPL-21): «вот меню» и «профилей нет» — тихо, exit 0;
    «не смог отформатировать» — причина в stderr и exit 1. Прежний `except Exception: pass`
    склеивал их в один — пустой stdout с кодом успеха, из-за чего пользователь `/init`
    видел пустой список и не мог понять, выбирать не из чего или сломался разбор.
    """
    try:
        ps = json.load(sys.stdin)
    except Exception as e:
        print(f"menu-format: не разобрал JSON со списком профилей на stdin: {e}",
              file=sys.stderr)
        sys.exit(1)

    for i, p in enumerate(ps):
        try:
            line = "  {:<{w}} — {}".format(p["name"], p["description"], w=args.max_len)
            if p.get("audience"):
                line += " [для: {}]".format(p["audience"])
        except Exception as e:
            # Частичный вывод особенно опасен: усечённое меню профилей неотличимо от
            # полного, поэтому обрыв на i-м элементе объявляется, а не заминается.
            print(f"menu-format: не отформатировал профиль #{i} ({p!r}): {e}",
                  file=sys.stderr)
            sys.exit(1)
        print(line)


def cmd_profile_summary(args: argparse.Namespace) -> None:
    """profile-summary <profile>: bulleted summary профиля на stdout."""
    profile = args.profile
    m = load_manifest(profile)
    if not m:
        return

    desc = m.get("description", "")
    audience = m.get("audience") or ""
    ops = m.get("operations") or []
    overrides = m.get("agent_overrides") or {}
    subagents = m.get("subagents") or {}
    prompts = m.get("init_prompts") or []

    op_add = sum(1 for o in ops if o.get("op") == "add")
    op_replace = sum(1 for o in ops if o.get("op") == "replace")
    op_resolve = sum(1 for o in ops if o.get("op") == "resolve_agents")
    op_total = len(ops)

    override_names = list(overrides.keys())

    core_count = sum(1 for v in subagents.values() if v == "core")
    optional_count = sum(1 for v in subagents.values() if v == "optional")
    disabled_count = sum(1 for v in subagents.values() if v == "disabled")

    print(f"Profile: {profile} — {desc}")
    print(f"  Description : {desc}")
    if audience:
        print(f"  Audience    : {audience}")
    ops_detail = f"add: {op_add}, replace: {op_replace}"
    if op_resolve:
        ops_detail += f", resolve_agents: {op_resolve}"
    print(f"  Operations  : {op_total} ({ops_detail})")
    if override_names:
        print(f"  Overrides   : {len(override_names)} ({', '.join(override_names)})")
    else:
        print("  Overrides   : 0")
    print(f"  Subagents   : {core_count} core, {optional_count} optional, {disabled_count} disabled")
    print(f"  Init prompts: {len(prompts)}")


def cmd_init_prompts(args: argparse.Namespace) -> None:
    """init-prompts <profile>: JSON-массив prompt-объектов {id, prompt, type, default, choices}."""
    profile = args.profile
    m = load_manifest(profile)
    prompts = m.get("init_prompts") or []
    normalized = []
    for p in prompts:
        normalized.append({
            "id":      p.get("id", ""),
            "prompt":  p.get("prompt", ""),
            "type":    p.get("type", "string"),
            "default": p.get("default", ""),
            "choices": p.get("choices") or [],
        })
    print(json.dumps(normalized))


def cmd_prompt_field(args: argparse.Namespace) -> None:
    """prompt-field <index> <field>: значение поля prompt по индексу из JSON на stdin."""
    try:
        ps = json.load(sys.stdin)
        p = ps[args.index]
        field = args.field
        if field == "choices":
            val = p.get("choices") or []
            print("|".join(val))
        else:
            print(p.get(field, ""))
    except (IndexError, KeyError, json.JSONDecodeError):
        print("")


def cmd_json_count(args: argparse.Namespace) -> None:
    """json-count: длина JSON-массива из stdin (stdlib-only, без PyYAML)."""
    try:
        data = json.load(sys.stdin)
        print(len(data) if isinstance(data, list) else 0)
    except (json.JSONDecodeError, TypeError):
        print(0)


def cmd_compat_stacks(args: argparse.Namespace) -> None:
    """compat-stacks <profile>: compatible_stacks через запятую (или пусто)."""
    profile = args.profile
    m = load_manifest(profile)
    s = m.get("compatible_stacks") or []
    if s and s != ["*"]:
        print(",".join(s))
    else:
        print("")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="_init_helpers.py — helper subcommands для init.sh",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", metavar="<subcommand>")
    sub.required = True

    # list-profiles
    sub.add_parser("list-profiles", help="JSON-массив профилей")

    # menu-max-len (reads JSON from stdin)
    sub.add_parser("menu-max-len", help="max длина name из JSON на stdin")

    # menu-format (reads JSON from stdin)
    p_mf = sub.add_parser("menu-format", help="форматированные строки меню")
    p_mf.add_argument("--max-len", type=int, default=7, help="ширина колонки name")

    # profile-summary
    p_ps = sub.add_parser("profile-summary", help="bulleted summary профиля")
    p_ps.add_argument("profile", help="имя профиля")

    # init-prompts
    p_ip = sub.add_parser("init-prompts", help="JSON-массив prompt-объектов профиля")
    p_ip.add_argument("profile", help="имя профиля")

    # prompt-field
    p_pf = sub.add_parser("prompt-field", help="поле prompt по индексу (JSON на stdin)")
    p_pf.add_argument("index", type=int, help="индекс prompt'а (0-based)")
    p_pf.add_argument("field", help="имя поля: id, prompt, type, default, choices")

    # json-count (reads JSON array from stdin)
    sub.add_parser("json-count", help="длина JSON-массива из stdin")

    # compat-stacks
    p_cs = sub.add_parser("compat-stacks", help="compatible_stacks через запятую")
    p_cs.add_argument("profile", help="имя профиля")


    return parser


COMMANDS = {
    "list-profiles":       cmd_list_profiles,
    "menu-max-len":        cmd_menu_max_len,
    "menu-format":         cmd_menu_format,
    "profile-summary":     cmd_profile_summary,
    "init-prompts":        cmd_init_prompts,
    "prompt-field":        cmd_prompt_field,
    "json-count":          cmd_json_count,
    "compat-stacks":       cmd_compat_stacks,
}


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    fn = COMMANDS.get(args.command)
    if fn is None:
        parser.print_help()
        sys.exit(1)
    fn(args)


if __name__ == "__main__":
    main()
