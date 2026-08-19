"""FR-13 CLI: `create-meeting-preview`/`cancel-meeting-preview` — предпросмотр без сети.

Подтверждающие команды переехали в `cli_meeting_confirm.py` (ADR-016 §6): обе ветки
подтверждения в одном файле с аргументами перевалили бы порог гейта C13 (350 строк).
Общие аргументы и печать ошибок — `cli_meeting_args.py`.

ADR-016 §2: `confirmation_id` снова выводится в `--json`. Решение ADR-015 его не
выводить следовало из хранилища в памяти («не переживает границу процессов») и
отменено вместе с причиной — хранилище персистентно, и именно id связывает
предъявленное оператору тело с фактической записью.
"""

from __future__ import annotations

import argparse

from ktalk_mcp.cli_meeting_args import (
    add_cancel_args,
    add_meeting_args,
    meeting_kwargs,
    print_error,
)
from ktalk_mcp.confirmation import ConfirmationStore
from ktalk_mcp.formatters import (
    format_cancel_preview,
    format_meeting_preview,
    format_raw,
    render_tool_output,
)
from ktalk_mcp.meeting_body import MissingFieldError, TimezoneFormatError
from ktalk_mcp.meeting_cancel import CancelPreviewService
from ktalk_mcp.meeting_scheduling import PreviewService


def register_subparsers(sub) -> None:
    p_create_preview = sub.add_parser("create-meeting-preview", help="Предпросмотр встречи (FR-13)")
    add_meeting_args(p_create_preview)
    p_create_preview.add_argument("--json", action="store_true")

    p_cancel_preview = sub.add_parser(
        "cancel-meeting-preview", help="Предпросмотр отмены (ADR-011)"
    )
    add_cancel_args(p_cancel_preview)
    p_cancel_preview.add_argument("--json", action="store_true")


def cmd_create_meeting_preview(_reg, args: argparse.Namespace) -> int:
    """Без сети — только валидация и предпросмотр."""
    service = PreviewService(ConfirmationStore())
    try:
        body, confirmation_id = service.preview(**meeting_kwargs(args))
    except (MissingFieldError, TimezoneFormatError) as exc:
        print_error(str(exc))
        return 1
    data = {"body": body, "confirmation_id": confirmation_id}
    print(format_raw(data) if args.json else render_tool_output(data, "markdown",
                                                               format_meeting_preview))
    return 0


def cmd_cancel_meeting_preview(_reg, args: argparse.Namespace) -> int:
    """Без сети — только предпросмотр (ADR-011-spec §4)."""
    service = CancelPreviewService(ConfirmationStore())
    payload, confirmation_id = service.preview(id=args.id, reason=args.reason)
    data = {"payload": payload, "confirmation_id": confirmation_id}
    print(format_raw(data) if args.json else render_tool_output(data, "markdown",
                                                               format_cancel_preview))
    return 0
