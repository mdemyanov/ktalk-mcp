"""Общие аргументы и вывод ошибок пишущих команд встреч (ADR-016 §6).

Выделено из `cli_meeting.py` при расщеплении на предпросмотр и подтверждение:
общий у команд именно набор аргументов, а не операция, поэтому расщепление прошло
по каналу («предпросмотр / подтверждение»), а не по операции.
"""

from __future__ import annotations

import argparse
import sys

from ktalk_mcp.config import redact_secrets


def tri_bool(value: str) -> bool:
    """NFR-9: явный `true|false`, не `store_true` — `store_true` дал бы молчаливый
    `False` при отсутствии флага, ровно тихий дефолт, который NFR-9 запрещает."""
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise argparse.ArgumentTypeError(f'Ожидается "true" или "false", получено: {value!r}')


def add_meeting_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--subject", default=None)
    parser.add_argument("--start", default=None)
    parser.add_argument("--end", default=None)
    parser.add_argument(
        "--timezone",
        default=None,
        help="Формат GMT±N, пример: GMT+3 (единственная подтверждённая форма, FR-40)",
    )
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
    parser.add_argument("--enable-auto-recording", type=tri_bool, default=None)
    parser.add_argument("--pin-code", default=None)
    parser.add_argument(
        "--no-pin-code",
        action="store_true",
        help='Явное «без PIN» (JSON null) — не то же самое, что отсутствие флага (ADR-009 §2)',
    )
    parser.add_argument("--allow-anonymous", type=tri_bool, default=None)
    parser.add_argument(
        "--anonymous-access-expiration",
        default=None,
        help=(
            "Обязателен, если --allow-anonymous true (ADR-009 §3 — нет вычисляемого "
            "дефолта, значение указывается явно)"
        ),
    )


def add_cancel_args(parser: argparse.ArgumentParser) -> None:
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


def required_attendee_keys(args: argparse.Namespace) -> list[str] | None:
    """`--no-required-attendees` побеждает при одновременной передаче обоих
    флагов — порядок не специфицирован спекой, зафиксирован здесь и тестом."""
    if args.no_required_attendees:
        return []
    return args.required_attendee_key


def meeting_kwargs(args: argparse.Namespace) -> dict:
    return {
        "subject": args.subject,
        "start": args.start,
        "end": args.end,
        "timezone": args.timezone,
        "room_name": args.room_name,
        "required_attendee_keys": required_attendee_keys(args),
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
NO_RESPONSE_BODY = object()


def print_error(message: str, response_body: object = NO_RESPONSE_BODY) -> None:
    """ADR-008 §3: тело ответа сервера (если было прикреплено к исключению) печатается
    вместе с основным текстом, тем же проходом `redact_secrets` — новой точки
    маскирования не вводится. Пустое тело печатается явно как факт (DEV-008), не
    опускается."""
    if response_body is NO_RESPONSE_BODY:
        text = message
    elif response_body:
        text = f"{message}\nТело ответа сервера: {response_body}"
    else:
        text = f"{message}\nТело ответа сервера: (пусто)"
    print(f"Ошибка: {redact_secrets(text)}", file=sys.stderr)
