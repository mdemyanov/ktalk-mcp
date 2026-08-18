"""CLI-эквиваленты оставшихся читающих MCP-инструментов (DEV-002 волны 3, ADR-012
§2а): `list-archive` (FR-9), `get-chat-messages` (FR-10), `list-calendar` (FR-18),
`get-room` (FR-17) — те же операции, что `tools_meetings.py`/`tools_rooms.py`,
вторая обёртка над тем же клиентом/форматтерами.

Все команды — `_REGISTRY_FREE_COMMANDS` (не открывают SQLite, читают только сеть).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date

from ktalk_mcp.calendar_reader import get_calendar_window
from ktalk_mcp.client import KTalkClient
from ktalk_mcp.config import Settings, redact_secrets
from ktalk_mcp.formatters import (
    format_archive_list,
    format_calendar,
    format_chat_messages,
    format_room,
    render_tool_output,
)
from ktalk_mcp.rooms import get_room


def register_subparsers(sub) -> None:
    p_arch = sub.add_parser("list-archive", help="Архив встреч за окно дат (сеть, FR-9)")
    p_arch.add_argument("--from", dest="from_date", required=True)
    p_arch.add_argument("--to", dest="to_date", required=True)
    p_arch.add_argument("--room-name", action="append", default=None)
    p_arch.add_argument("--json", action="store_true")

    p_chat = sub.add_parser("get-chat-messages", help="Сообщения чата встречи (сеть, FR-10)")
    p_chat.add_argument("--recording-key", default=None)
    p_chat.add_argument("--conference-key", default=None)
    p_chat.add_argument("--channel", default=None)
    p_chat.add_argument("--json", action="store_true")

    p_cal = sub.add_parser("list-calendar", help="Календарь встреч (сеть, FR-18)")
    p_cal.add_argument("--start", required=True)
    p_cal.add_argument("--end", required=True)
    p_cal.add_argument("--room-name", default=None)
    p_cal.add_argument("--json", action="store_true")

    p_room = sub.add_parser(
        "get-room",
        help="Детали комнаты (сеть, FR-17 — ПОБОЧНЫЙ ЭФФЕКТ: создаёт комнату, если имя новое)",
    )
    p_room.add_argument("room_name")
    p_room.add_argument("--json", action="store_true")


def _run(coro, formatter, *, json_flag: bool, **formatter_kwargs) -> int:
    try:
        data = asyncio.run(coro)
    except Exception as exc:  # noqa: BLE001 - surface as CLI error, NFR-5 маскирует
        print(f"Ошибка: {redact_secrets(str(exc))}", file=sys.stderr)
        return 1
    fmt = "raw" if json_flag else "markdown"
    print(render_tool_output(data, fmt, formatter, **formatter_kwargs))
    return 0


async def _list_archive(args: argparse.Namespace) -> list[dict]:
    async with KTalkClient.from_settings(Settings()) as client:
        return await client.list_archive(
            from_date=args.from_date, to_date=args.to_date, room_names=args.room_name
        )


def cmd_list_archive(_reg, args: argparse.Namespace) -> int:
    return _run(_list_archive(args), format_archive_list, json_flag=args.json)


async def _get_chat_messages(args: argparse.Namespace) -> list[dict]:
    async with KTalkClient.from_settings(Settings()) as client:
        return await client.get_chat_messages(
            recording_key=args.recording_key,
            conference_key=args.conference_key,
            channel=args.channel,
        )


def cmd_get_chat_messages(_reg, args: argparse.Namespace) -> int:
    return _run(_get_chat_messages(args), format_chat_messages, json_flag=args.json)


async def _list_calendar(args: argparse.Namespace) -> dict:
    async with KTalkClient.from_settings(Settings()) as client:
        result = await get_calendar_window(
            client, date.fromisoformat(args.start), date.fromisoformat(args.end),
            room_name=args.room_name,
        )
    return {
        "items": result.items,
        "incomplete_segments": [
            [s.isoformat(), e.isoformat()] for s, e in result.incomplete_segments
        ],
    }


def cmd_list_calendar(_reg, args: argparse.Namespace) -> int:
    return _run(_list_calendar(args), format_calendar, json_flag=args.json)


async def _get_room(args: argparse.Namespace) -> dict:
    async with KTalkClient.from_settings(Settings()) as client:
        return await get_room(client, args.room_name)


def cmd_get_room(_reg, args: argparse.Namespace) -> int:
    return _run(_get_room(args), format_room, json_flag=args.json)
