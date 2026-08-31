"""Таблица «операция × режим авторизации -> путь + scope» (FR-6) + примитивы
подстановки в путь. Вынесено из `auth.py` (гейт C13 — самая длинная top-level
декларация модуля превысила порог при росте таблицы ADR-010/ADR-011).

`auth.py` реэкспортирует эти имена — расположение импорта не влияет на
видимость атрибута модуля, тот же приём, что `client.py` уже применяет к
`auth.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from ktalk_cli.config import AuthMode

OPERATION_LABELS = {
    "list_archive": "архив",
    "get_participants_full": "полный состав участников",
    "get_participants_report": "отчёт по участникам встречи",
    "get_room": "чтение комнаты",
    "get_calendar": "чтение календаря",
    "create_meeting": "создание встречи",
    "search_contacts": "поиск контактов",
    "cancel_meeting": "отмена встречи",
}


def quote_path_param(value: object) -> str:
    """SEC-001: квотирует значение перед подстановкой в `path_template.format(...)` —
    без этого "../" в recording_key/conference_key меняет фактический путь запроса
    (например, "../admin" схлопывает /api/recordings/../admin в /api/admin)."""
    return quote(str(value), safe="")


@dataclass(frozen=True)
class EndpointProfile:
    """Путь + требуемый scope одной операции для одного режима авторизации."""

    path_template: str
    required_scope: str | None
    mutating: bool = False  # ADR-008: session-режим шлёт доп. Authorization-заголовок


# Таблица «операция × режим -> путь + scope» (FR-6). Отсутствие записи для режима
# (значение None) — управляемый отказ до сети, не голый 401/403.
OPERATION_PROFILES: dict[str, dict[AuthMode, EndpointProfile | None]] = {
    "list_recordings": {
        AuthMode.SESSION: EndpointProfile("/api/recordings", None),
        AuthMode.API_KEY: EndpointProfile(
            "/api/Domain/recordings/v2", "application.recording.read"
        ),
    },
    "get_recording": {
        AuthMode.SESSION: EndpointProfile("/api/recordings/{key}", None),
        AuthMode.API_KEY: EndpointProfile(
            "/api/Domain/recordings/{key}", "application.recording.read"
        ),
    },
    "get_transcript": {
        AuthMode.SESSION: EndpointProfile("/api/recordings/{key}/transcript", None),
        AuthMode.API_KEY: EndpointProfile(
            "/api/recordings/{key}/transcript", "application.recording.read"
        ),
    },
    "get_summary": {
        AuthMode.SESSION: EndpointProfile("/api/recordings/v2/{key}/summary", None),
        AuthMode.API_KEY: EndpointProfile(
            "/api/recordings/v2/{key}/summary", "application.recording.read"
        ),
    },
    "get_summary_by_type": {
        AuthMode.SESSION: EndpointProfile("/api/recordings/{key}/summary/{summary_type}", None),
        AuthMode.API_KEY: EndpointProfile(
            "/api/recordings/{key}/summary/{summary_type}", "application.recording.read"
        ),
    },
    "list_archive": {
        AuthMode.SESSION: None,
        AuthMode.API_KEY: EndpointProfile(
            "/api/domain/conferencesHistory", "application.reporting.read"
        ),
    },
    "get_conference": {
        AuthMode.SESSION: EndpointProfile("/api/conferencesHistory/{key}", None),
        AuthMode.API_KEY: EndpointProfile(
            "/api/ConferencesHistory/v2/{key}", "application.reporting.read"
        ),
    },
    "get_participants_full": {
        # Session-режим дообогащает дуальным источником (get_recording + get_conference),
        # не через выделенный путь — см. KTalkClient.get_full_participants.
        AuthMode.SESSION: None,
        AuthMode.API_KEY: EndpointProfile(
            "/api/Domain/recordings/{key}/participants", "application.recording.read"
        ),
    },
    "get_participants_report": {
        AuthMode.SESSION: None,
        AuthMode.API_KEY: EndpointProfile(
            "/api/ConferenceReports/{key}/participants", "application.reporting.read"
        ),
    },
    "get_room": {
        # FR-17: внутренний путь, вне спеки, регистронезависим (постановка §5, живой GET).
        AuthMode.SESSION: EndpointProfile("/api/rooms/{room_name}", None),
        # ADR-004, таблица «Подтверждённость»: api-key не проверен вовсе — fail-closed (FR-17 AC3).
        AuthMode.API_KEY: None,
    },
    "get_calendar": {
        # FR-18: внутренний путь, вне спеки, подтверждён исчерпывающе под session
        # (Ф-17–Ф-31 RES-003).
        AuthMode.SESSION: EndpointProfile("/api/calendar", None),
        # ADR-004 п.2: 200 наблюдался под api-key (Ф-34), но необъяснимо (расходится с Ф-33/Ф-35
        # тем же ключом) — не "рабочая" запись несмотря на живой позитивный результат.
        # Ревизуемо отдельной задачей при появлении объяснения, не тихой правкой этой строки.
        AuthMode.API_KEY: None,
    },
    "create_meeting": {
        # ГИПОТЕЗА (mainpart-ktalk-mcp.md:192-193, RES-003 Ф-38, не проверено живым POST):
        # путь с префиксом /api — mainpart документирует base_url = f"{space_url}/api" и
        # использует /calendar относительно него; предыдущая запись без /api была ошибкой
        # прочтения этого источника (ADR-007), не проверенным решением. Следующий боевой
        # POST под новой санкцией владельца — единственная проверка.
        # ГИПОТЕЗА (ADR-008, DEV-005 §5, не проверено живым POST): запись в session-режиме
        # может требовать доп. заголовок Authorization: Session <token> — mutating=True
        # добавляет его поверх query, не вместо. Следующий боевой POST — единственная проверка.
        AuthMode.SESSION: EndpointProfile("/api/calendar", None, mutating=True),
        # ФАКТ (ADR-004 п.2): api-key не проверен вовсе -> fail-closed.
        AuthMode.API_KEY: None,
    },
    "search_contacts": {
        # ADR-010 §1: путь наблюдён живым HAR (RES-003 §5, Ф-53), read-операция.
        AuthMode.SESSION: EndpointProfile("/api/contacts", None),
        # ADR-010: api-key-режим не проверен вовсе (нет выданных scope, Р-4) -> fail-closed.
        AuthMode.API_KEY: None,
    },
    "cancel_meeting": {
        # ADR-011 §1: симметрично create_meeting — Ф-50, mutating=True, тот же транспорт,
        # что ADR-009 подтвердил живым POST создания.
        AuthMode.SESSION: EndpointProfile("/api/calendar/{id}/cancel", None, mutating=True),
        # ADR-011: api-key-режим для мутаций календаря не проверен ни разу -> fail-closed.
        AuthMode.API_KEY: None,
    },
}
