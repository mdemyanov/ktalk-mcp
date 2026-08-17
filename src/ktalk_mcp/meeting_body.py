"""FR-13/NFR-9: allow-list компоновщик тела встречи + канонический хеш (ADR-005 §Решение).

Единая функция принимает только согласованный постановкой набор полей — без
`**kwargs` и без прохода через произвольный словарь вызывающего. `isRecurring`/
`recurrence` и поля вне этого состава физически не имеют параметра, через который
могли бы попасть в тело — структурная невозможность, не рантайм-фильтр.
"""

from __future__ import annotations

import hashlib
import json

from ktalk_mcp.client import KTalkError

# NFR-9: 8 строк таблицы -> 9 физических полей + subject (обязателен по схеме,
# Ф-37, не входит в NFR-9, но проверяется тем же None-циклом — единый источник
# отказа, не два разных пути валидации).
_REQUIRED = (
    "subject",
    "start",
    "end",
    "timezone",
    "roomName",
    "requiredUserKeys",
    "allowAnonymous",
    "pinCode",
    "enableSip",
    "enableAutoRecording",
)


class MissingFieldError(KTalkError):
    """Поле из `_REQUIRED` не передано явно (`None`) — отказ до сетевого вызова."""

    def __init__(self, field: str) -> None:
        super().__init__(
            f'Поле «{field}» не передано явно вызывающим — запрос на создание встречи '
            "отклонён до сетевого вызова (NFR-9)."
        )
        self.field = field


def build_meeting_body(
    *,
    subject: str | None = None,
    start: str | None = None,
    end: str | None = None,
    timezone: str | None = None,
    room_name: str | None = None,
    required_user_keys: list[str] | None = None,
    description: str | None = None,
    enable_auto_recording: bool | None = None,
    enable_sip: bool | None = None,
    pin_code: str | None = None,
    allow_anonymous: bool | None = None,
) -> dict:
    """Каждое поле `_REQUIRED` проверяется через `is None` (не truthiness) — явный
    пустой список участников/пустой `pinCode`/`False` — валидные явные решения,
    отсутствие значения — нет. `description` — единственное поле с разрешённым
    тихим дефолтом (пустая строка, NFR-9)."""
    body = {
        "subject": subject,
        "start": start,
        "end": end,
        "timezone": timezone,
        "roomName": room_name,
        "requiredUserKeys": required_user_keys,
        "description": description if description is not None else "",
        "enableAutoRecording": enable_auto_recording,
        "enableSip": enable_sip,
        "pinCode": pin_code,
        "allowAnonymous": allow_anonymous,
    }
    for field in _REQUIRED:
        if body[field] is None:
            raise MissingFieldError(field)
    return body


def canonical_body_hash(body: dict) -> str:
    """sha256 канонической (стабильной по порядку ключей) сериализации тела —
    основа привязки подтверждения к содержимому (ADR-005)."""
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
