"""CLI-эквиваленты MCP-инструментов сущности «Запись» (DEV-002 волны 3, ADR-012
§2а): `list-recordings`, `get-recording`, `get-transcript`, `get-summary`,
`get-summary-type`, `get-participants`, `download-recording` — те же операции,
что `tools_recordings.py`, вторая обёртка над тем же клиентом/форматтерами (не
дублирует логику: `render_tool_output`/`render_transcript_output` общие с MCP).

Все команды — `_REGISTRY_FREE_COMMANDS` (не открывают SQLite, читают только сеть).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable

from ktalk_cli.client import KTalkClient
from ktalk_cli.config import Settings, redact_secrets
from ktalk_cli.download import download_recording_file
from ktalk_cli.formatters import (
    format_download_result,
    format_participants,
    format_recording,
    format_recordings_list,
    format_summary,
    format_summary_by_type,
    render_tool_output,
    render_transcript_output,
)


def register_subparsers(sub) -> None:
    p_list = sub.add_parser("list-recordings", help="Список записей KTalk (сеть)")
    p_list.add_argument("--query", default=None)
    p_list.add_argument("--start-from", default=None)
    p_list.add_argument("--start-to", default=None)
    p_list.add_argument("--top", type=int, default=30)
    p_list.add_argument("--order", default="byTimeNewFirst")
    p_list.add_argument("--page-token", default=None)
    p_list.add_argument("--json", action="store_true")

    p_get = sub.add_parser("get-recording", help="Детали записи (сеть)")
    p_get.add_argument("recording_key")
    p_get.add_argument("--json", action="store_true")

    p_tr = sub.add_parser("get-transcript", help="Транскрипт записи (сеть, с чанкингом)")
    p_tr.add_argument("recording_key")
    p_tr.add_argument("--chunk", type=int, default=0)
    p_tr.add_argument("--chunk-size", type=int, default=30000)
    p_tr.add_argument("--json", action="store_true")

    p_sum = sub.add_parser("get-summary", help="Полное саммари записи (сеть)")
    p_sum.add_argument("recording_key")
    p_sum.add_argument("--json", action="store_true")

    p_sum_type = sub.add_parser("get-summary-type", help="Саммари одного типа (сеть)")
    p_sum_type.add_argument("recording_key")
    p_sum_type.add_argument("--type", dest="summary_type", required=True)
    p_sum_type.add_argument("--json", action="store_true")

    p_part = sub.add_parser("get-participants", help="Полный состав участников (сеть, FR-8)")
    p_part.add_argument("recording_key")
    p_part.add_argument("--json", action="store_true")

    p_dl = sub.add_parser("download-recording", help="Скачать видеофайл записи (сеть, FR-7)")
    p_dl.add_argument("recording_key")
    p_dl.add_argument("--target", required=True, help="Путь для записи файла")
    p_dl.add_argument("--quality", default=None)
    p_dl.add_argument("--json", action="store_true")


def _run(
    coro: Awaitable[object],
    formatter: Callable[..., str],
    *,
    json_flag: bool,
    **formatter_kwargs: object,
) -> int:
    try:
        data = asyncio.run(coro)
    except Exception as exc:  # noqa: BLE001 - surface as CLI error, NFR-5 маскирует
        print(f"Ошибка: {redact_secrets(str(exc))}", file=sys.stderr)
        return 1
    fmt = "raw" if json_flag else "markdown"
    print(render_tool_output(data, fmt, formatter, **formatter_kwargs))
    return 0


async def _list_recordings(args: argparse.Namespace) -> dict:
    async with KTalkClient.from_settings(Settings()) as client:
        return await client.list_recordings(
            query=args.query,
            start_from=args.start_from,
            start_to=args.start_to,
            top=args.top,
            order_mode=args.order,
            page_token=args.page_token,
        )


def cmd_list_recordings(_reg, args: argparse.Namespace) -> int:
    return _run(_list_recordings(args), format_recordings_list, json_flag=args.json)


async def _get_recording(args: argparse.Namespace) -> dict:
    async with KTalkClient.from_settings(Settings()) as client:
        return await client.get_recording(args.recording_key)


def cmd_get_recording(_reg, args: argparse.Namespace) -> int:
    return _run(_get_recording(args), format_recording, json_flag=args.json)


def cmd_get_transcript(_reg, args: argparse.Namespace) -> int:
    async def _fetch() -> dict:
        async with KTalkClient.from_settings(Settings()) as client:
            return await client.get_transcript(args.recording_key)

    try:
        data = asyncio.run(_fetch())
    except Exception as exc:  # noqa: BLE001 - surface as CLI error, NFR-5 маскирует
        print(f"Ошибка: {redact_secrets(str(exc))}", file=sys.stderr)
        return 1
    fmt = "raw" if args.json else "markdown"
    print(render_transcript_output(data, fmt, args.chunk, args.chunk_size))
    return 0


async def _get_summary(args: argparse.Namespace) -> dict:
    async with KTalkClient.from_settings(Settings()) as client:
        return await client.get_summary(args.recording_key)


def cmd_get_summary(_reg, args: argparse.Namespace) -> int:
    return _run(_get_summary(args), format_summary, json_flag=args.json)


async def _get_summary_by_type(args: argparse.Namespace) -> dict:
    async with KTalkClient.from_settings(Settings()) as client:
        return await client.get_summary_by_type(args.recording_key, args.summary_type)


def cmd_get_summary_type(_reg, args: argparse.Namespace) -> int:
    return _run(
        _get_summary_by_type(args),
        format_summary_by_type,
        json_flag=args.json,
        summary_type=args.summary_type,
    )


async def _get_participants(args: argparse.Namespace) -> dict:
    async with KTalkClient.from_settings(Settings()) as client:
        return await client.get_full_participants(args.recording_key)


def cmd_get_participants(_reg, args: argparse.Namespace) -> int:
    return _run(_get_participants(args), format_participants, json_flag=args.json)


async def _download_recording(args: argparse.Namespace) -> dict:
    async with KTalkClient.from_settings(Settings()) as client:
        return await download_recording_file(client, args.recording_key, args.target, args.quality)


def cmd_download_recording(_reg, args: argparse.Namespace) -> int:
    return _run(_download_recording(args), format_download_result, json_flag=args.json)
