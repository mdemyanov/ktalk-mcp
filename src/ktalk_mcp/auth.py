"""Режим авторизации, профиль эндпоинтов, нормализованная форма страницы (ADR-003).

Вынесено из `client.py` для гейта C13 (объём кода): таблицы/DTO здесь — данные,
не поведение сети, `KTalkClient` остаётся единственным потребителем. Публичные
имена, ожидаемые тестами через `ktalk_mcp.client` (`AuthStatus`,
`normalize_list_session`, `normalize_list_apikey`), реэкспортируются оттуда.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING
from urllib.parse import quote

from ktalk_mcp.config import AuthMode, KTalkConfigError
from ktalk_mcp.pagination import paginate_pages, skip_pages

if TYPE_CHECKING:
    from ktalk_mcp.client import KTalkClient

logger = logging.getLogger(__name__)

SCOPE_LABELS = {
    "application.recording.read": "Записи (только чтение)",
    "application.reporting.read": "Отчётность (только чтение)",
    "application.applications.read": "Информация по API-ключам (только чтение)",
}

OPERATION_LABELS = {
    "list_archive": "архив",
    "get_participants_full": "полный состав участников",
    "get_participants_report": "отчёт по участникам встречи",
    "get_room": "чтение комнаты",
    "get_calendar": "чтение календаря",
    "create_meeting": "создание встречи",
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
        AuthMode.SESSION: EndpointProfile("/api/calendar", None),
        # ФАКТ (ADR-004 п.2): api-key не проверен вовсе -> fail-closed.
        AuthMode.API_KEY: None,
    },
}


@dataclass(frozen=True)
class AuthContext:
    """Неизменяемая пара (режим, credential) — вычисляется один раз."""

    mode: AuthMode
    credential: str

    def __repr__(self) -> str:  # NFR-5: значение секрета никогда не в repr
        return f"AuthContext(mode={self.mode!r}, credential='***')"

    @staticmethod
    def resolve(*, session_token: str | None, personal_api_key: str | None) -> AuthContext:
        if personal_api_key:
            if session_token:
                logger.warning(
                    "Заданы обе переменные — используется KTALK_PERSONAL_API_KEY, "
                    "KTALK_SESSION_TOKEN игнорируется."
                )
            return AuthContext(AuthMode.API_KEY, personal_api_key)
        if session_token:
            return AuthContext(AuthMode.SESSION, session_token)
        raise KTalkConfigError(
            "Не задана ни KTALK_PERSONAL_API_KEY, ни KTALK_SESSION_TOKEN. "
            "Укажите одну из переменных (см. README)."
        )


@dataclass(frozen=True)
class SkipCursor:
    skip: int
    top: int


@dataclass(frozen=True)
class TokenCursor:
    token: str


@dataclass
class NormalizedPage:
    items: list[dict]
    cursor: SkipCursor | TokenCursor | None


def normalize_list_session(raw: dict, *, skip: int, top: int) -> NormalizedPage:
    """`{"recordings": [...]}` (без токена страницы) -> единая форма.

    Конец страницы — короткая/пустая страница (не полагается на отсутствующее в этой
    форме поле пагинации, зонд Ф-3): курсор есть только когда страница ровно полная.
    """
    items = raw.get("recordings") or []
    cursor = SkipCursor(skip + len(items), top) if items and len(items) == top else None
    return NormalizedPage(items=items, cursor=cursor)


def normalize_list_apikey(raw: dict) -> NormalizedPage:
    """`{"entities": [...], "nextPageToken": ...}` -> единая форма.

    `nextPageToken: null` явно в JSON и отсутствующее поле — эквивалентны.
    """
    items = raw.get("entities") or []
    token = raw.get("nextPageToken")
    cursor = TokenCursor(token) if token else None
    return NormalizedPage(items=items, cursor=cursor)


@dataclass
class AuthStatus:
    """Результат диагностики активного механизма авторизации (FR-11)."""

    alive: bool
    scopes: list[dict] | None
    expired_at: str | None
    note: str | None


def _display_name(info: dict) -> str:
    surname = info.get("surname")
    firstname = info.get("firstname")
    if surname and firstname:
        return f"{surname} {firstname}"
    return surname or firstname or info.get("login") or "Неизвестный"


def normalize_participant(raw: dict) -> dict:
    """`TalkUserBaseInfoRef` -> `{"ktalk_id"|"anonymous_id", "name"}` (FR-8).

    Отдельная схема от `enrichment.map_participants` (там оба случая используют
    ключ `ktalk_id` ради совместимости с `registry.py`) — здесь ключи различны,
    чтобы `get_full_participants` мог дедуплицировать по составному признаку.
    """
    info = raw.get("userInfo")
    if info:
        return {"ktalk_id": info.get("key") or info.get("login"), "name": _display_name(info)}
    return {
        "anonymous_id": raw.get("anonymousId"),
        "name": raw.get("anonymousName") or "Аноним",
    }


def _dedup_key(raw: dict) -> tuple[str, str]:
    info = raw.get("userInfo")
    if info:
        return "user", str(info.get("key") or info.get("login") or "")
    return "anon", str(raw.get("anonymousId") or "")


def merge_participants(*groups: list[dict]) -> list[dict]:
    """Объединяет несколько источников участников без дублей (FR-8 dual-source):
    дедуп по ключу участника (`userInfo.key`/`login` либо `anonymousId`), не по
    позиции в массиве — источники частично пересекаются, не подмножества друг друга.
    """
    seen: set[tuple[str, str]] = set()
    merged: list[dict] = []
    for group in groups:
        for raw in group:
            key = _dedup_key(raw)
            if not key[1] or key in seen:
                continue
            seen.add(key)
            merged.append(normalize_participant(raw))
    return merged


async def full_participants_apikey(client: KTalkClient, recording_key: str) -> dict:
    """Api-key-ветка `KTalkClient.get_full_participants` — вынесена сюда ради гейта
    C13 (объём client.py); использует "приватные" коллаборирующие атрибуты клиента
    осознанно, оба модуля — одна логическая единица (ADR-003)."""
    profile = client._profile_for("get_participants_full")  # noqa: SLF001

    async def raw_fetch(skip: int, top: int) -> dict:
        path = profile.path_template.format(key=quote_path_param(recording_key))
        response = await client._client.get(path, params={"skip": skip, "top": top})  # noqa: SLF001
        client._classify(response, profile.required_scope)  # noqa: SLF001
        return response.json()

    fetch_page = skip_pages(raw_fetch, page_size=100, items_key="entities")
    out: list[dict] = []
    async for page in paginate_pages(fetch_page):
        out.extend(normalize_participant(p) for p in page)
    return {"participants": out, "incomplete": False}


async def resolve_chat_channel(client: KTalkClient, conference_key: str) -> str:
    """Определяет канал по умолчанию из деталей встречи (FR-10 AC-2), а не падает
    с сырым 400 "The channel field is required" (зонд Ф-6)."""
    conference = await client.get_conference(conference_key)
    channels = (conference.get("artifacts") or {}).get("chatChannelHasMessages") or {}
    for name, has_messages in channels.items():
        if has_messages:
            return name
    return "general"
