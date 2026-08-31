"""Режим авторизации, профиль эндпоинтов, нормализованная форма страницы (ADR-003).

Вынесено из `client.py` для гейта C13 (объём кода): таблицы/DTO здесь — данные,
не поведение сети, `KTalkClient` остаётся единственным потребителем. Публичные
имена, ожидаемые тестами через `ktalk_cli.client` (`AuthStatus`,
`normalize_list_session`, `normalize_list_apikey`), реэкспортируются оттуда.

`OPERATION_PROFILES`/`OPERATION_LABELS`/`EndpointProfile`/`quote_path_param` —
в `endpoints.py` (тот же гейт: таблица профилей переросла порог top-level
декларации при добавлении ADR-010/ADR-011), реэкспортированы ниже — тесты и
остальной код по-прежнему видят их как `ktalk_cli.auth.*`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ktalk_cli.config import AuthMode, KTalkConfigError
from ktalk_cli.endpoints import (  # noqa: F401 - реэкспорт публичного контракта модуля
    OPERATION_LABELS,
    OPERATION_PROFILES,
    EndpointProfile,
    quote_path_param,
)
from ktalk_cli.pagination import paginate_pages, skip_pages

if TYPE_CHECKING:
    from ktalk_cli.client import KTalkClient

logger = logging.getLogger(__name__)

SCOPE_LABELS = {
    "application.recording.read": "Записи (только чтение)",
    "application.reporting.read": "Отчётность (только чтение)",
    "application.applications.read": "Информация по API-ключам (только чтение)",
}


class KTalkError(Exception):
    """Base error for KTalk API."""


class KTalkAuthError(KTalkError):
    """Session token or personal API key expired or invalid."""


class KTalkScopeError(KTalkAuthError):
    """API key valid, but lacks the required scope for the operation."""


class KTalkWriteAuthMismatchError(KTalkAuthError):
    """401/403 на операции, credential которой в ту же секунду подтверждён рабочим
    независимой проверкой (ADR-008) — обновление токена не помогает."""


class KTalkNotFoundError(KTalkError):
    """Recording not found."""


class OperationNotAvailableError(KTalkError):
    """Operation has no endpoint profile for the currently active auth mode."""


def _auth_error(message: str, status_code: int, cls: type[KTalkAuthError] = KTalkAuthError):
    """ADR-008 §2: код ответа — отдельный атрибут исключения (`status_code`), читает
    его `_status_hint` в `contour_diagnostics.py` без парсинга текста сообщения."""
    exc = cls(message)
    exc.status_code = status_code
    return exc


def classify_response(
    mode: AuthMode, response: object, required_scope: str | None
) -> None:
    """Вынесено из `KTalkClient._classify` (гейт C13) — не зависит от `self`, только
    от режима, статус-кода и требуемого scope. ADR-003: коды 401/403 разводятся по
    смыслу (истёк vs. запрещён), ADR-008: код ответа — атрибут `status_code` на
    исключении, читает `contour_diagnostics._status_hint`."""
    status = response.status_code  # type: ignore[attr-defined]
    if status == 401:
        if mode is AuthMode.API_KEY:
            raise _auth_error(
                "Ключ авторизации истёк или невалиден. "
                "Обновите KTALK_PERSONAL_API_KEY (см. README).",
                401,
            )
        raise _auth_error(
            "Токен сессии истёк или невалиден. Обновите его: `ktalk token set -` (или переменную KTALK_SESSION_TOKEN, если она задана) — см. README.", 401
        )
    if status == 403:
        if mode is AuthMode.API_KEY:
            if required_scope:
                label = SCOPE_LABELS.get(required_scope, required_scope)
                raise _auth_error(
                    f"Ключу не хватает разрешения «{label}» ({required_scope}). "
                    "Добавьте его ключу в настройках Толка (администратор домена).",
                    403,
                    KTalkScopeError,
                )
            raise _auth_error("Доступ запрещён. Обратитесь к администратору Толка.", 403)
        # Session-режим: у токена нет понятия scope, но 403 — это не 401. Раньше оба
        # кода давали одно сообщение «токен истёк» — ADR-003 разводит их по смыслу.
        raise _auth_error(
            "Доступ запрещён: у текущей сессии нет прав на эту операцию. "
            "Токен при этом рабочий — обновлять его не нужно.",
            403,
        )
    if status == 404:
        raise KTalkNotFoundError("Ресурс не найден.")
    if status >= 400:
        raise KTalkError(f"Ошибка API Контур.Толк: HTTP {status}.")


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
