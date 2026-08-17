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
from ktalk_mcp.formatters import format_cancel_preview, format_meeting_preview, render_tool_output
from ktalk_mcp.meeting_body import MissingFieldError, canonical_body_hash
from ktalk_mcp.meeting_cancel import CancelPreviewService, build_cancel_confirmation_payload
from ktalk_mcp.meeting_scheduling import PreviewService, cancel_meeting, create_meeting

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
    # ADR-009 §5: `--required-user-key` (логин) переименован в `--required-attendee-key`
    # (числовой id) — резолюция логина в id не реализуется этим ADR, оператор
    # передаёт значение явно (см. Бриф для Dev spec §5).
    parser.add_argument("--required-attendee-key", action="append", default=None)
    parser.add_argument(
        "--no-required-attendees",
        action="store_true",
        help="Явное «без обязательных участников» (не то же самое, что отсутствие флага)",
    )
    parser.add_argument("--description", default=None)
    parser.add_argument("--enable-auto-recording", type=_tri_bool, default=None)
    parser.add_argument("--pin-code", default=None)
    parser.add_argument(
        "--no-pin-code",
        action="store_true",
        help='Явное «без PIN» (JSON null) — не то же самое, что отсутствие флага (ADR-009 §2)',
    )
    parser.add_argument("--allow-anonymous", type=_tri_bool, default=None)
    parser.add_argument(
        "--anonymous-access-expiration",
        default=None,
        help=(
            "Обязателен, если --allow-anonymous true (ADR-009 §3 — нет вычисляемого "
            "дефолта, значение указывается явно)"
        ),
    )


def _add_cancel_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--id",
        required=True,
        help="Base64 id встречи (Ф-56, из ответа create-meeting-confirm или чтения "
        "календаря); не хранится проектом",
    )
    parser.add_argument(
        "--reason",
        default="",
        help='Причина отмены (опционально, дефолт "" — единственный подтверждённый '
        "рабочий образец, Ф-50)",
    )


def register_subparsers(sub) -> None:
    _add_meeting_args(sub.add_parser("create-meeting-preview", help="Предпросмотр встречи (FR-13)"))
    _add_meeting_args(sub.add_parser("create-meeting-confirm", help="Создать встречу (только TTY)"))
    _add_cancel_args(sub.add_parser("cancel-meeting-preview", help="Предпросмотр отмены (ADR-011)"))
    _add_cancel_args(sub.add_parser("cancel-meeting-confirm", help="Отменить встречу (только TTY)"))


def _required_attendee_keys(args: argparse.Namespace) -> list[str] | None:
    """`--no-required-attendees` побеждает при одновременной передаче обоих
    флагов — порядок не специфицирован спекой, зафиксирован здесь и тестом."""
    if args.no_required_attendees:
        return []
    return args.required_attendee_key


def _meeting_kwargs(args: argparse.Namespace) -> dict:
    return {
        "subject": args.subject,
        "start": args.start,
        "end": args.end,
        "timezone": args.timezone,
        "room_name": args.room_name,
        "required_attendee_keys": _required_attendee_keys(args),
        "description": args.description,
        "enable_auto_recording": args.enable_auto_recording,
        "pin_code": args.pin_code,
        "pin_code_explicit_none": args.no_pin_code,
        "allow_anonymous": args.allow_anonymous,
        "anonymous_access_expiration": args.anonymous_access_expiration,
    }


# DEV-008: сентинел, а не `None` по умолчанию — различает "response_body не
# прикреплён вовсе" (нет ответа сервера, печатать нечего) и "прикреплён пустой"
# (тело ответа сервера фактически пустое — это наблюдение о контуре, не потеря
# кода). Оба раньше давали одно и то же "ничего не печатать".
_NO_RESPONSE_BODY = object()


def _print_error(message: str, response_body: object = _NO_RESPONSE_BODY) -> None:
    """ADR-008 §3: тело ответа сервера (если было прикреплено к исключению) печатается
    вместе с основным текстом, тем же проходом `redact_secrets` — новой точки
    маскирования не вводится. Пустое тело печатается явно как факт (DEV-008), не
    опускается."""
    if response_body is _NO_RESPONSE_BODY:
        text = message
    elif response_body:
        text = f"{message}\nТело ответа сервера: {response_body}"
    else:
        text = f"{message}\nТело ответа сервера: (пусто)"
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
        # DEV-008: код ответа исходного отказа виден всегда, не только в ветках,
        # чей текст сам его упоминает (ADR-008 KTalkWriteAuthMismatchError уже
        # называет код — дублировать не нужно, но "сырое" 401/403 без правки текста
        # (когда контроль тоже упал) кода не называет вовсе).
        status_code = getattr(exc, "status_code", None)
        base_message = str(exc)
        if status_code is not None and f"HTTP {status_code}" not in base_message:
            base_message = f"{base_message} (HTTP {status_code})"

        message = (
            f"{base_message} — исход неизвестен, проверьте `ktalk_list_calendar` перед "
            "повторной попыткой (повторный запуск create-meeting-confirm не выполняет "
            "автоматический retry, NFR-9/RES-003 §3)."
        )
        # DEV-008: исход контрольного вызова (если он тоже падал) — видим отдельной
        # строкой, не проглочен молча (contour_diagnostics.diagnose_undocumented_failure).
        control_probe = getattr(exc, "control_probe", None)
        if control_probe:
            message = f"{message}\n{control_probe}"

        _print_error(message, getattr(exc, "response_body", _NO_RESPONSE_BODY))
        return 1

    print(f"Встреча создана: {result.get('id', result)}")
    return 0


async def _cancel_over_network(id: str, reason: str) -> dict:
    async with KTalkClient.from_settings(Settings()) as client:
        return await cancel_meeting(client, id=id, reason=reason)


def cmd_cancel_meeting_preview(_reg, args: argparse.Namespace) -> int:
    """Без TTY-барьера, без сети — только предпросмотр (ADR-011-spec §4)."""
    service = CancelPreviewService(ConfirmationStore())
    payload, confirmation_id = service.preview(id=args.id, reason=args.reason)
    data = {"payload": payload, "confirmation_id": confirmation_id}
    print(render_tool_output(data, "markdown", format_cancel_preview))
    return 0


def cmd_cancel_meeting_confirm(_reg, args: argparse.Namespace) -> int:
    """TTY-барьер первым делом (§4) — тот же порядок, что `create-meeting-confirm`."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("Нужен интерактивный терминал (см. README).", file=sys.stderr)
        return 1

    store = ConfirmationStore()
    service = CancelPreviewService(store)
    payload, confirmation_id = service.preview(id=args.id, reason=args.reason)

    preview_data = {"payload": payload, "confirmation_id": confirmation_id}
    print(render_tool_output(preview_data, "markdown", format_cancel_preview))
    print(f'\nВведите "{_CONFIRM_WORD}" для подтверждения отмены встречи: ', end="", flush=True)
    answer = sys.stdin.readline().strip()
    if answer.lower() != _CONFIRM_WORD:
        print("Отменено — подтверждение не получено.", file=sys.stderr)
        return 1

    recomputed_hash = canonical_body_hash(
        build_cancel_confirmation_payload(id=args.id, reason=args.reason)
    )
    if not store.match(confirmation_id, recomputed_hash):
        _print_error("Подтверждение истекло или недействительно — начните заново.")
        return 1
    store.consume(confirmation_id)  # до сетевой попытки — повтор требует нового вызова

    try:
        result = asyncio.run(_cancel_over_network(args.id, args.reason))
    except Exception as exc:  # noqa: BLE001 - любая ошибка = "исход неизвестен", без retry
        status_code = getattr(exc, "status_code", None)
        base_message = str(exc)
        if status_code is not None and f"HTTP {status_code}" not in base_message:
            base_message = f"{base_message} (HTTP {status_code})"

        message = (
            f"{base_message} — исход неизвестен, проверьте `ktalk_list_calendar` перед "
            "повторной попыткой (повторный запуск cancel-meeting-confirm не выполняет "
            "автоматический retry, NFR-9/ADR-005 п.2)."
        )
        control_probe = getattr(exc, "control_probe", None)
        if control_probe:
            message = f"{message}\n{control_probe}"

        _print_error(message, getattr(exc, "response_body", _NO_RESPONSE_BODY))
        return 1

    print(f"Встреча отменена: {result}")
    return 0
