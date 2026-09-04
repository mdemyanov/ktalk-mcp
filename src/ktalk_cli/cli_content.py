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
import json
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
    resolve_chunk_range,
)
from ktalk_cli.transcript_identity import check_identity


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
    p_tr.add_argument(
        "--no-verify-identity",
        action="store_true",
        help="Отключить сверку идентичности спикеров с участниками записи (NFR-17, "
        "по умолчанию включена)",
    )

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


async def _verify_transcript_identity(client: KTalkClient, recording_key: str, transcript: dict) -> dict:
    """Оркестрация NFR-17 (ADR-023 §1, ред. 2a2f6e3): независимый вызов
    `get_recording`; отказ вызова -> `not_checked` (маскирование той же функцией,
    что и основная ошибка, NFR-5), не исключение наружу — основной результат
    транскрипта возвращается в любом случае."""
    try:
        recording = await client.get_recording(recording_key)
    except Exception as exc:  # noqa: BLE001 - not_checked, не отказ команды
        return {"result": "not_checked", "reason": redact_secrets(str(exc))}
    return check_identity(transcript, recording)


def _render_transcript_with_identity(
    output_text: str, identity_check: dict | None, *, json_flag: bool, in_range: bool = True
) -> str:
    """Сборка вывода `get-transcript` (companion-спека «Оркестрация», шаг 5).
    `identity_check is None` -> сверка отключена (`--no-verify-identity`), выводим
    как раньше. `in_range` — валидность `--chunk` уже известна вызывающей стороне
    (`resolve_chunk_range`, ADR-024 §Д3) — на пути вне диапазона JSON-конверт
    собирается явно (`{"error": …}`), без `try/except JSONDecodeError`."""
    if identity_check is None:
        return output_text

    if not json_flag:
        line = f"[identity-check] {identity_check['result']}"
        if "reason" in identity_check:
            line += f" ({identity_check['reason']})"
        return f"{output_text}\n{line}"

    if not in_range:
        return json.dumps(
            {"error": output_text, "identity_check": identity_check},
            ensure_ascii=False,
            indent=2,
        )

    parsed = json.loads(output_text)
    return json.dumps(
        {"transcript": parsed, "identity_check": identity_check}, ensure_ascii=False, indent=2
    )


def cmd_get_transcript(_reg, args: argparse.Namespace) -> int:
    fmt = "raw" if args.json else "markdown"

    async def _fetch() -> tuple[dict, dict | None, bool]:
        async with KTalkClient.from_settings(Settings()) as client:
            data = await client.get_transcript(args.recording_key)
            in_range, _total_chunks = resolve_chunk_range(data, fmt, args.chunk, args.chunk_size)
            identity_check = None
            if not args.no_verify_identity:
                if in_range:
                    identity_check = await _verify_transcript_identity(
                        client, args.recording_key, data
                    )
                else:
                    # ADR-024 §Д3: чанк заведомо вне диапазона — сверка не
                    # оплачивается сетевым вызовом, `not_checked` формируется
                    # локально, переиспользуя словарь исходов ADR-023.
                    identity_check = {"result": "not_checked", "reason": "chunk_out_of_range"}
            return data, identity_check, in_range

    try:
        data, identity_check, in_range = asyncio.run(_fetch())
    except Exception as exc:  # noqa: BLE001 - surface as CLI error, NFR-5 маскирует
        print(f"Ошибка: {redact_secrets(str(exc))}", file=sys.stderr)
        return 1
    output_text = render_transcript_output(data, fmt, args.chunk, args.chunk_size)
    print(
        _render_transcript_with_identity(
            output_text, identity_check, json_flag=args.json, in_range=in_range
        )
    )
    if identity_check is not None and identity_check.get("result") == "mismatch":
        # ADR-024 §Д1: отказ становится громким — код 3, отдельный от 0/1/2.
        return 3
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
