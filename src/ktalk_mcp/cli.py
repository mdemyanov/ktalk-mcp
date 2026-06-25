"""Command-line interface for the KTalk recordings registry."""

from __future__ import annotations

import argparse
import json
import sys

from ktalk_mcp.config import resolve_db_path
from ktalk_mcp.registry import Registry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ktalk", description="Реестр записей Kontur Talk")
    parser.add_argument("--db", default=None, help="Путь к SQLite-базе реестра")
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="Список записей")
    p_list.add_argument("--status", default=None)
    p_list.add_argument("--json", action="store_true")

    p_show = sub.add_parser("show", help="Детали записи")
    p_show.add_argument("id")
    p_show.add_argument("--json", action="store_true")

    return parser


def _print_json(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _cmd_list(reg: Registry, args) -> int:
    recs = reg.list_recordings(status=args.status)
    if args.json:
        _print_json({"recordings": recs})
        return 0
    if not recs:
        print("Записей не найдено.")
        return 0
    for r in recs:
        dur = f"{r['duration_min']} мин" if r["duration_min"] else "—"
        print(f"{r['recording_id']}  [{r['status']}]  {r['date']}  {dur}  {r['name']}")
    return 0


def _cmd_show(reg: Registry, args) -> int:
    rec = reg.get_recording(args.id)
    if rec is None:
        print(f"Запись не найдена: {args.id}", file=sys.stderr)
        return 1
    rec = dict(rec)
    rec["participants"] = reg.get_participants(args.id)
    if args.json:
        _print_json(rec)
        return 0
    print(f"# {rec['name']}")
    print(f"- ID: {rec['recording_id']}")
    print(f"- Статус: {rec['status']}")
    print(f"- Дата: {rec['date']}")
    print(f"- Длительность: {rec['duration_min']} мин")
    print(f"- Транскрипт: {rec['transcript_path'] or '—'}")
    print(f"- Протокол: {rec['protocol_path'] or '—'}")
    print("- Участники:")
    for p in rec["participants"]:
        vault = f" -> {p['vault_id']}" if p["vault_id"] else ""
        print(f"  - {p['name']} (ktalk:{p['ktalk_id']}){vault}")
    return 0


_HANDLERS = {
    "list": _cmd_list,
    "show": _cmd_show,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    db_path = resolve_db_path(args.db)
    handler = _HANDLERS.get(args.command)
    if handler is None:
        parser.print_help()
        return 2
    try:
        with Registry(db_path) as reg:
            return handler(reg, args)
    except Exception as exc:  # noqa: BLE001 - surface as CLI error
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
