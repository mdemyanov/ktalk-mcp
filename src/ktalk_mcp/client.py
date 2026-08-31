"""Async HTTP client for KTalk API — режимы авторизации, профиль эндпоинтов,
диагностика 401/403, диагностика ключа/токена (ADR-003).

Таблица профиля/DTO/нормализаторы вынесены в `ktalk_mcp.auth` (гейт C13); публичные
имена, которые тесты и остальной код ожидают именно из `ktalk_mcp.client`
(`AuthStatus`, `normalize_list_session`, `normalize_list_apikey`, ...), реэкспортированы
ниже — расположение импорта не влияет на видимость атрибута модуля.
"""

from __future__ import annotations

import httpx

from ktalk_mcp.auth import (  # noqa: F401 - реэкспорт публичного контракта модуля
    OPERATION_LABELS,
    OPERATION_PROFILES,
    SCOPE_LABELS,
    AuthContext,
    AuthStatus,
    EndpointProfile,
    KTalkAuthError,
    KTalkError,
    KTalkNotFoundError,
    KTalkScopeError,
    KTalkWriteAuthMismatchError,
    OperationNotAvailableError,
    classify_response,
    full_participants_apikey,
    merge_participants,
    normalize_list_apikey,
    normalize_list_session,
    quote_path_param,
    resolve_chat_channel,
)
from ktalk_mcp.config import AuthMode, Settings
from ktalk_mcp.pagination import paginate_pages, skip_pages


class KTalkClient:
    """Async HTTP client for KTalk API.

    Usage::

        async with KTalkClient(base_url, session_token=..., personal_api_key=...) as client:
            recordings = await client.list_recordings()

    Ровно один из `session_token`/`personal_api_key` определяет режим (ADR-003):
    ключ побеждает, если задано и то, и другое; ни один из двух не отправляется
    вместе с механизмом другого режима — заголовок либо query-параметр настраиваются
    один раз при конструировании, не проверяются на каждый запрос.
    """

    def __init__(
        self,
        base_url: str,
        session_token: str | None = None,
        personal_api_key: str | None = None,
    ) -> None:
        self._auth = AuthContext.resolve(
            session_token=session_token, personal_api_key=personal_api_key
        )
        # Авторизация в этом клиенте — только заголовок/query (ADR-003), cookie-jar
        # нигде не читается. Без явной зачистки httpx.AsyncClient по умолчанию копит
        # Set-Cookie между запросами одного инстанса (httpx не даёт конструктору
        # флага "без cookie" — `cookies=` принимает jar/dict, не bool) — контрольный
        # вызов ADR-004/diagnose_undocumented_failure после проваленного мутирующего
        # POST унаследовал бы cookie именно этого провала (DEV-007), теряя
        # независимость диагностики от отказа, который она проверяет.
        if self._auth.mode is AuthMode.API_KEY:
            self._client = httpx.AsyncClient(
                base_url=base_url,
                headers={"X-Auth-Token": self._auth.credential},
                timeout=30.0,
            )
        else:
            self._client = httpx.AsyncClient(
                base_url=base_url,
                params={"sessionToken": self._auth.credential},
                timeout=30.0,
            )
        # Хук ставится после конструирования — сам себе замыкание на `self._client`,
        # httpx извлекает Set-Cookie до вызова response-хуков (`Cookies.extract_cookies`
        # в `_send_single_request` отрабатывает раньше), поэтому зачистка здесь не
        # мешает уже полученному ответу — снимает cookie только со следующего запроса.
        self._client.event_hooks["response"] = [self._forget_response_cookies]

    async def _forget_response_cookies(self, _response: httpx.Response) -> None:
        self._client.cookies.clear()

    @classmethod
    def from_settings(cls, settings: Settings) -> KTalkClient:
        return cls(
            base_url=settings.ktalk_base_url,
            session_token=settings.ktalk_session_token,
            personal_api_key=settings.ktalk_personal_api_key,
        )

    async def __aenter__(self) -> KTalkClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self._client.aclose()

    @property
    def auth_mode(self) -> AuthMode:
        return self._auth.mode

    def stream(self, method: str, url: str):
        """Потоковый запрос без буферизации целиком (FR-7 AC4) — для `download.py`."""
        return self._client.stream(method, url)

    def check_response(self, response: httpx.Response, required_scope: str | None = None) -> None:
        """Публичная обёртка над `_classify` — для потоковых вызовов вне `_call`."""
        self._classify(response, required_scope)

    def _profile_for(self, operation: str) -> EndpointProfile:
        """Code review (epic-capability-pairing, Р1/Р2): текст отказа обязан называть
        режим, реально подтверждённый для операции (`OPERATION_PROFILES`), не
        зашитый заранее «режим ключа» — верно ровно для `list_archive`, для
        `get_room`/`get_calendar`/`create_meeting`/`cancel_meeting`/`search_contacts`
        (все пять подтверждены только под session, `AuthMode.API_KEY: None`)
        пользователю с ключом раньше советовали включить ключ, которым он уже
        пользуется."""
        profiles = OPERATION_PROFILES.get(operation, {})
        profile = profiles.get(self._auth.mode)
        if profile is None:
            label = OPERATION_LABELS.get(operation, operation)
            required_mode = next(
                (mode for mode, candidate in profiles.items() if candidate is not None),
                None,
            )
            if required_mode is AuthMode.SESSION:
                raise OperationNotAvailableError(
                    f"Операция «{label}» доступна только в режиме сессии "
                    "(переменная KTALK_SESSION_TOKEN)."
                )
            if required_mode is AuthMode.API_KEY:
                raise OperationNotAvailableError(
                    f"Операция «{label}» доступна только в режиме персонального ключа "
                    "(переменная KTALK_PERSONAL_API_KEY)."
                )
            # Операция вне OPERATION_PROFILES вовсе (например, update_meeting,
            # ADR-011 п.5) — ни один режим её не подтверждает, называть конкретный
            # режим было бы неверно.
            raise OperationNotAvailableError(
                f"Операция «{label}» недоступна ни в одном режиме авторизации."
            )
        return profile

    def _classify(self, response: httpx.Response, required_scope: str | None) -> None:
        """Логика вынесена в `auth.classify_response` (гейт C13) — не зависит от
        `self`, только от режима/статус-кода/scope."""
        classify_response(self._auth.mode, response, required_scope)

    async def _call(self, operation: str, params: dict) -> dict:
        profile = self._profile_for(operation)
        path = profile.path_template.format(**{k: quote_path_param(v) for k, v in params.items()})
        response = await self._client.get(path)
        self._classify(response, profile.required_scope)
        return response.json()

    async def list_recordings(
        self,
        *,
        query: str | None = None,
        start_from: str | None = None,
        start_to: str | None = None,
        top: int = 30,
        skip: int = 0,
        order_mode: str = "byTimeNewFirst",
        page_token: str | None = None,
        title: str | None = None,
    ) -> dict:
        profile = self._profile_for("list_recordings")
        params: dict = {"top": top, "orderMode": order_mode}
        if query is not None:
            params["query"] = query
        if start_from is not None:
            params["startFrom"] = start_from
        if start_to is not None:
            params["startTo"] = start_to
        if title is not None:
            params["title"] = title
        if self._auth.mode is AuthMode.API_KEY:
            if page_token is not None:
                params["pageTokenString"] = page_token
        elif skip:
            params["skip"] = skip
        response = await self._client.get(profile.path_template, params=params)
        self._classify(response, profile.required_scope)
        return response.json()

    async def get_recording(self, recording_key: str) -> dict:
        return await self._call("get_recording", {"key": recording_key})

    async def get_transcript(self, recording_key: str) -> dict:
        return await self._call("get_transcript", {"key": recording_key})

    async def get_summary(self, recording_key: str) -> dict:
        return await self._call("get_summary", {"key": recording_key})

    async def get_summary_by_type(self, recording_key: str, summary_type: str) -> dict:
        return await self._call(
            "get_summary_by_type", {"key": recording_key, "summary_type": summary_type}
        )

    async def list_archive(
        self,
        *,
        from_date: str,
        to_date: str,
        room_names: list[str] | None = None,
        page_size: int = 100,
    ) -> list[dict]:
        profile = self._profile_for("list_archive")

        async def raw_fetch(skip: int, top: int) -> dict:
            params: dict = {"fromDate": from_date, "toDate": to_date, "skip": skip, "take": top}
            if room_names:
                params["roomName"] = room_names
            response = await self._client.get(profile.path_template, params=params)
            self._classify(response, profile.required_scope)
            return response.json()

        fetch_page = skip_pages(raw_fetch, page_size=page_size, items_key="conferences")
        out: list[dict] = []
        async for page in paginate_pages(fetch_page):
            out.extend(page)
        return out

    async def get_conference(self, conference_key: str) -> dict:
        return await self._call("get_conference", {"key": conference_key})

    async def get_full_participants(self, recording_key: str) -> dict:
        """Полный состав участников (FR-8): api-key — паджинированный путь профиля,
        session — объединение get_recording + get_conference (ADR-003-spec, п.2
        «Закрытые открытые вопросы BA»), с явным `incomplete`, если всё равно короче
        `participantsCount`."""
        if self._auth.mode is AuthMode.API_KEY:
            return await full_participants_apikey(self, recording_key)
        detail = await self.get_recording(recording_key)
        conference_key = detail.get("conferenceKey") or recording_key
        conference = await self.get_conference(conference_key)
        conf_participants = (conference.get("artifacts") or {}).get("participants") or []
        merged = merge_participants(detail.get("participants") or [], conf_participants)
        count = detail.get("participantsCount", len(merged))
        return {"participants": merged, "incomplete": len(merged) < count}

    async def get_chat_messages(
        self,
        recording_key: str | None = None,
        conference_key: str | None = None,
        channel: str | None = None,
    ) -> list[dict]:
        """Оркестрация FR-10: recording_key -> conferenceKey -> канал -> сообщения."""
        if conference_key is None:
            if recording_key is None:
                raise ValueError("Нужен recording_key или conference_key")
            detail = await self.get_recording(recording_key)
            conference_key = detail.get("conferenceKey") or recording_key
        if channel is None:
            channel = await resolve_chat_channel(self, conference_key)
        return await self._fetch_chat_messages(conference_key, channel)

    async def _fetch_chat_messages(self, conference_key: str, channel: str) -> list[dict]:
        key = quote_path_param(conference_key)
        if self._auth.mode is AuthMode.API_KEY:
            path = f"/api/ConferenceReports/{key}/messages"
            scope = "application.reporting.read"
        else:
            path = f"/api/conferencesHistory/{key}/chat/messages"
            scope = None
        response = await self._client.get(path, params={"channel": channel})
        if response.status_code == 403:
            raise KTalkError(
                f"Нет прав на получение сообщений чат-канала «{channel}» (см. README)."
            )
        self._classify(response, scope)
        return response.json().get("messages", [])

    async def get_participants_report(self, conference_key: str) -> dict:
        return await self._call("get_participants_report", {"key": conference_key})

    async def get_auth_status(self) -> AuthStatus:
        if self._auth.mode is AuthMode.API_KEY:
            return await self._auth_status_apikey()
        return await self._auth_status_session()

    async def _auth_status_apikey(self) -> AuthStatus:
        response = await self._client.get("/api/domain/applications/access-info")
        if response.status_code == 401:
            return AuthStatus(
                alive=False,
                scopes=None,
                expired_at=None,
                note="Ключ авторизации истёк или невалиден.",
            )
        if response.status_code == 403:
            # Зонд Ф-12: 403 на access-info значит «ключ жив», не «ключ мёртв» — сам
            # запрос диагностики требует application.applications.read.
            return AuthStatus(
                alive=True,
                scopes=None,
                expired_at=None,
                note=(
                    "Ключ валиден, но не хватает разрешения application.applications.read "
                    "для просмотра списка scope'ов."
                ),
            )
        if response.status_code != 200:
            raise KTalkError(
                f"Ошибка API Контур.Толк при диагностике ключа: HTTP {response.status_code}."
            )
        data = response.json()
        return AuthStatus(
            alive=True, scopes=data.get("scopes"), expired_at=data.get("expiredAt"), note=None
        )

    async def _auth_status_session(self) -> AuthStatus:
        try:
            await self.list_recordings(top=1)
        except KTalkAuthError:
            return AuthStatus(
                alive=False,
                scopes=None,
                expired_at=None,
                note="Токен сессии не прошёл проверку (пробный запрос списка записей).",
            )
        return AuthStatus(
            alive=True,
            scopes=None,
            expired_at=None,
            note=(
                "У сессионного токена нет понятия scope/срока действия — выполнена "
                "пробная проверка list_recordings(top=1), а не имитация без сети."
            ),
        )


_shared_client: KTalkClient | None = None


def get_shared_client() -> KTalkClient:
    """Singleton клиента для MCP-инструментов (было `server.py::_get_client`)."""
    global _shared_client
    if _shared_client is None:
        _shared_client = KTalkClient.from_settings(Settings())
    return _shared_client
