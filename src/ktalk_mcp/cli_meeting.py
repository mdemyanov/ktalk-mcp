"""FR-13 CLI: `create-meeting-preview`/`create-meeting-confirm` (§6.5–6.6).

`create-meeting-confirm` не принимает `--id` от предыдущего `preview` — межпроцессной
связки физически нет (ADR-005 §6.3). Оно самодостаточно: строит тело из своих
аргументов, порождает свой собственный confirmation через тот же
`PreviewService`/`ConfirmationStore`, что и превью-путь, печатает предпросмотр,
синхронно запрашивает подтверждение с реального терминала, затем выполняет ровно
один сетевой POST без retry.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from ktalk_mcp.client import KTalkClient
from ktalk_mcp.config import Settings, redact_secrets
from ktalk_mcp.confirmation import ConfirmationStore
from ktalk_mcp.formatters import format_meeting_preview, render_tool_output
from ktalk_mcp.meeting_body import MissingFieldError, canonical_body_hash
from ktalk_mcp.meeting_scheduling import PreviewService, create_meeting

# Слово подтверждения не зафиксировано ни спекой, ни ADR — рабочая гипотеза
# QA-author (at-design.md «Допущения»), подтверждена здесь как решение Dev.
_CONFIRM_WORD = "да"


def _tri_bool(value: str) -> bool:
    """NFR-9: явный `true|false`, не `store_true` — `store_true` дал бы молчаливый
    `False` при отсутствии флага, ровно тихий дефолт, который NFR-9 запрещает."""
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise argparse.ArgumentTypeError(f'Ожидается "true" или "false", получено: {value!r}')


def _add_meeting_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--subject", default=None)
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument("--timezone", default=None)
    parser.add_argument("--room-name", default=None)
    parser.add_argument("--required-user-key", action="append", default=None)
    parser.add_argument(
        "--no-required-users",
        action="store_true",
        help="Явное «без обязательных участников» (не то же самое, что отсутствие флага)",
    )
    parser.add_argument("--description", default=None)
    parser.add_argument("--enable-auto-recording", type=_tri_bool, default=None)
    parser.add_argument("--enable-sip", type=_tri_bool, default=None)
    parser.add_argument("--pin-code", default=None)
    parser.add_argument("--allow-anonymous", type=_tri_bool, default=None)


def register_subparsers(sub) -> None:
    _add_meeting_args(sub.add_parser("create-meeting-preview", help="Предпросмотр встречи (FR-13)"))
    _add_meeting_args(sub.add_parser("create-meeting-confirm", help="Создать встречу (только TTY)"))


def _required_user_keys(args: argparse.Namespace) -> list[str] | None:
    """`--no-required-users` побеждает при одновременной передаче обоих флагов —
    порядок не специфицирован спекой, зафиксирован здесь и тестом."""
    if args.no_required_users:
        return []
    return args.required_user_key


def _meeting_kwargs(args: argparse.Namespace) -> dict:
    return {
        "subject": args.subject,
        "start": args.start,
        "end": args.end,
        "timezone": args.timezone,
        "room_name": args.room_name,
        "required_user_keys": _required_user_keys(args),
        "description": args.description,
        "enable_auto_recording": args.enable_auto_recording,
        "enable_sip": args.enable_sip,
        "pin_code": args.pin_code,
        "allow_anonymous": args.allow_anonymous,
    }


def _print_error(message: str, response_body: str | None = None) -> None:
    """ADR-008 §3: тело ответа сервера (если было прикреплено к исключению) печатается
    вместе с основным текстом, тем же проходом `redact_secrets` — новой точки
    маскирования не вводится."""
    text = message if not response_body else f"{message}\nТело ответа сервера: {response_body}"
    print(f"Ошибка: {redact_secrets(text)}", file=sys.stderr)


async def _create_over_network(body: dict) -> dict:
    async with KTalkClient.from_settings(Settings()) as client:
        return await create_meeting(client, body)


def cmd_create_meeting_preview(_reg, args: argparse.Namespace) -> int:
    """Без TTY-барьера, без сети — только валидация и предпросмотр."""
    service = PreviewService(ConfirmationStore())
    try:
        body, confirmation_id = service.preview(**_meeting_kwargs(args))
    except MissingFieldError as exc:
        _print_error(str(exc))
        return 1
    data = {"body": body, "confirmation_id": confirmation_id}
    print(render_tool_output(data, "markdown", format_meeting_preview))
    return 0


def cmd_create_meeting_confirm(_reg, args: argparse.Namespace) -> int:
    """TTY-барьер первым делом — до `ConfirmationStore`, до построения тела, до
    сети (§6.5): провал здесь не тратит ничего лишнего."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("Нужен интерактивный терминал (см. README).", file=sys.stderr)
        return 1

    store = ConfirmationStore()
    service = PreviewService(store)
    try:
        body, confirmation_id = service.preview(**_meeting_kwargs(args))
    except MissingFieldError as exc:
        _print_error(str(exc))
        return 1

    preview_data = {"body": body, "confirmation_id": confirmation_id}
    print(render_tool_output(preview_data, "markdown", format_meeting_preview))
    print(f'\nВведите "{_CONFIRM_WORD}" для подтверждения создания встречи: ', end="", flush=True)
    answer = sys.stdin.readline().strip()
    if answer.lower() != _CONFIRM_WORD:
        print("Отменено — подтверждение не получено.", file=sys.stderr)
        return 1

    # Тело пересчитывается заново тем же компоновщиком, хеш сверяется с выданным
    # при этом же preview — здесь это защита от TTL, не от дрейфа между процессами
    # (которого физически нет, ADR-005 §6.3).
    if not store.match(confirmation_id, canonical_body_hash(body)):
        _print_error("Подтверждение истекло или недействительно — начните заново.")
        return 1
    store.consume(confirmation_id)  # до сетевой попытки — повтор требует нового вызова

    try:
        result = asyncio.run(_create_over_network(body))
    except Exception as exc:  # noqa: BLE001 - любая ошибка = "исход неизвестен", без retry
        _print_error(
            f"{exc} — исход неизвестен, проверьте `ktalk_list_calendar` перед повторной "
            "попыткой (повторный запуск create-meeting-confirm не выполняет автоматический "
            "retry, NFR-9/RES-003 §3).",
            getattr(exc, "response_body", None),
        )
        return 1

    print(f"Встреча создана: {result.get('id', result)}")
    return 0
