"""ADR-016 §1: `create-meeting-confirm`/`cancel-meeting-confirm` — два канала.

| Канал | Признак | Требуется | Не требуется |
|---|---|---|---|
| `tty` | `isatty()` на stdin и stdout | слово подтверждения | санкция, `--confirmation-id` |
| `sanctioned` | терминала нет | санкция + валидный `--confirmation-id` | слово подтверждения |

Канал выбирается по факту наличия терминала, не флагом: флаг был бы параметром,
который вызывающий выставляет сам, — ровно та ошибка, которую ADR-005 отклонил для
подтверждения-параметра.

Порядок проверок в санкционном канале: санкция -> подтверждение -> журнал -> сеть.
Санкция раньше подтверждения намеренно: иначе перебор `--confirmation-id` различал
бы состояния санкции по коду возврата.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from ktalk_mcp import write_sanction
from ktalk_mcp.cli_meeting_args import (
    NO_RESPONSE_BODY,
    add_cancel_args,
    add_meeting_args,
    meeting_kwargs,
    print_error,
)
from ktalk_mcp.client import KTalkClient
from ktalk_mcp.config import Settings
from ktalk_mcp.confirmation import ConfirmationStore
from ktalk_mcp.formatters import (
    format_cancel_preview,
    format_meeting_preview,
    render_tool_output,
)
from ktalk_mcp.meeting_body import MissingFieldError, TimezoneFormatError, canonical_body_hash
from ktalk_mcp.meeting_cancel import CancelPreviewService, build_cancel_confirmation_payload
from ktalk_mcp.meeting_scheduling import PreviewService, cancel_meeting, create_meeting
from ktalk_mcp.write_journal import JournalUnavailableError, append_attempt, append_outcome

# Слово подтверждения не зафиксировано ни спекой, ни ADR — рабочая гипотеза
# QA-author (at-design.md «Допущения»), подтверждена здесь как решение Dev.
_CONFIRM_WORD = "да"

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_NO_SANCTION = 40
EXIT_SANCTION_EXPIRED = 41
EXIT_SANCTION_EXHAUSTED = 42
EXIT_BAD_CONFIRMATION = 44

_SANCTION_EXIT = {
    "absent": EXIT_NO_SANCTION,
    "expired": EXIT_SANCTION_EXPIRED,
    "exhausted": EXIT_SANCTION_EXHAUSTED,
}


def register_subparsers(sub) -> None:
    # DEV-009 оставлял `*-confirm` без `--json` («их не вызывают программно»).
    # ADR-016 это отменяет: теперь вызывают, и разбирать надо машиночитаемо.
    p_create = sub.add_parser("create-meeting-confirm", help="Создать встречу (ADR-016)")
    add_meeting_args(p_create)
    _add_confirm_args(p_create)

    p_cancel = sub.add_parser("cancel-meeting-confirm", help="Отменить встречу (ADR-016)")
    add_cancel_args(p_cancel)
    _add_confirm_args(p_cancel)


def _add_confirm_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--confirmation-id",
        default=None,
        help="id из соответствующего *-preview; обязателен вне интерактивного терминала",
    )
    parser.add_argument("--json", action="store_true")


def _interactive() -> bool:
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def _ask_confirmation(prompt: str) -> bool:
    print(f'\nВведите "{_CONFIRM_WORD}" для подтверждения {prompt}: ', end="", flush=True)
    return sys.stdin.readline().strip().lower() == _CONFIRM_WORD


def _authorize(operation: str, args: argparse.Namespace, store, body_hash: str):
    """Возвращает `(channel, confirmation_id, remaining, exit_code)`; `exit_code`
    не `None` — отказ, сетевого вызова не будет."""
    if _interactive():
        return "tty", None, None, None

    state = write_sanction.read_state(operation)
    if not state.active:
        print_error(
            f"Нет действующей санкции на операцию «{operation}» (состояние: {state.status}). "
            f"Выдать её может только человек в своём терминале: "
            f"ktalk sanction grant {operation.replace('_', '-')}",
        )
        return "sanctioned", None, None, _SANCTION_EXIT[state.status]

    confirmation_id = args.confirmation_id
    if not confirmation_id or not store.match(confirmation_id, body_hash):
        print_error(
            "Подтверждение недействительно: нужен --confirmation-id из свежего "
            "*-preview с теми же параметрами (ADR-016 §2)."
        )
        return "sanctioned", None, None, EXIT_BAD_CONFIRMATION

    store.consume(confirmation_id)  # до сетевой попытки — повтор требует нового предпросмотра
    remaining = write_sanction.consume(operation)
    return "sanctioned", confirmation_id, remaining, None


def _report(args: argparse.Namespace, payload: dict, text: str) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(text)


def _run_confirm(operation, args, *, preview, formatter, prompt, network, describe) -> int:
    store = ConfirmationStore()
    try:
        body, own_confirmation_id = preview(store)
    except (MissingFieldError, TimezoneFormatError) as exc:
        print_error(str(exc))
        return EXIT_ERROR

    body_hash = canonical_body_hash(body)
    channel, confirmation_id, remaining, refusal = _authorize(operation, args, store, body_hash)
    if refusal is not None:
        return refusal

    # Предпросмотр печатается в обоих каналах: в `tty` — перед вопросом человеку,
    # в `sanctioned` — как след в выводе команды рядом с журнальной записью.
    print(render_tool_output({**describe(body), "confirmation_id": own_confirmation_id},
                             "markdown", formatter))
    if channel == "tty":
        if not _ask_confirmation(prompt):
            print("Отменено — подтверждение не получено.", file=sys.stderr)
            return EXIT_ERROR
        if not store.match(own_confirmation_id, body_hash):
            print_error("Подтверждение истекло или недействительно — начните заново.")
            return EXIT_BAD_CONFIRMATION
        store.consume(own_confirmation_id)
        confirmation_id = own_confirmation_id

    try:
        append_attempt(
            operation=operation,
            channel=channel,
            confirmation_id=confirmation_id or "",
            body_sha256=body_hash,
            body=body,
            sanction_remaining=remaining,
        )
    except JournalUnavailableError as exc:
        print_error(f"{exc} — запись в контур не выполнена (ADR-016 §5).")
        return EXIT_ERROR

    try:
        result = asyncio.run(network(body))
    except Exception as exc:  # noqa: BLE001 - любая ошибка = "исход неизвестен", без retry
        status_code = getattr(exc, "status_code", None)
        _outcome(
            operation, channel, confirmation_id, body_hash,
            "failed" if status_code is not None else "unknown", status_code,
        )
        _print_failure(args, exc, status_code, operation)
        return EXIT_ERROR

    _outcome(operation, channel, confirmation_id, body_hash, "ok", 200)
    _report(args, {"status": "ok", "operation": operation, "result": result},
            f"{'Встреча создана' if operation == 'create_meeting' else 'Встреча отменена'}: "
            f"{result.get('id', result) if isinstance(result, dict) else result}")
    return EXIT_OK


def _outcome(operation, channel, confirmation_id, body_hash, result, status_code) -> None:
    try:
        append_outcome(
            operation=operation,
            channel=channel,
            confirmation_id=confirmation_id or "",
            body_sha256=body_hash,
            result=result,
            status_code=status_code,
        )
    except JournalUnavailableError as exc:
        # Откатывать нечем — операция уже выполнена; молчать нельзя.
        print(f"Внимание: исход не записан в журнал ({exc}).", file=sys.stderr)


def _print_failure(args, exc, status_code, operation) -> None:
    base_message = str(exc)
    if status_code is not None and f"HTTP {status_code}" not in base_message:
        base_message = f"{base_message} (HTTP {status_code})"
    command = f"{operation.replace('_meeting', '-meeting').replace('_', '-')}-confirm"
    message = (
        f"{base_message} — исход неизвестен, проверьте `ktalk list-calendar` перед "
        f"повторной попыткой (повторный запуск {command} не выполняет автоматический "
        "retry, NFR-22; подтверждение и единица бюджета санкции уже потрачены)."
    )
    control_probe = getattr(exc, "control_probe", None)
    if control_probe:
        message = f"{message}\n{control_probe}"
    if getattr(args, "json", False):
        print(json.dumps({"status": "unknown", "operation": operation, "message": message},
                         ensure_ascii=False))
    print_error(message, getattr(exc, "response_body", NO_RESPONSE_BODY))


async def _create_over_network(body: dict) -> dict:
    async with KTalkClient.from_settings(Settings()) as client:
        return await create_meeting(client, body)


def cmd_create_meeting_confirm(_reg, args: argparse.Namespace) -> int:
    service_kwargs = meeting_kwargs(args)
    return _run_confirm(
        "create_meeting",
        args,
        preview=lambda store: PreviewService(store).preview(**service_kwargs),
        formatter=format_meeting_preview,
        prompt="создания встречи",
        network=_create_over_network,
        describe=lambda body: {"body": body},
    )


async def _cancel_over_network(id: str, reason: str) -> dict:
    async with KTalkClient.from_settings(Settings()) as client:
        return await cancel_meeting(client, id=id, reason=reason)


def cmd_cancel_meeting_confirm(_reg, args: argparse.Namespace) -> int:
    return _run_confirm(
        "cancel_meeting",
        args,
        preview=lambda store: CancelPreviewService(store).preview(id=args.id, reason=args.reason),
        formatter=format_cancel_preview,
        prompt="отмены встречи",
        network=lambda _body: _cancel_over_network(args.id, args.reason),
        describe=lambda payload: {"payload": payload},
    )


def build_cancel_payload(args: argparse.Namespace) -> dict:
    return build_cancel_confirmation_payload(id=args.id, reason=args.reason)
