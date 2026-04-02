from __future__ import annotations

import httpx


class KTalkError(Exception):
    """Base error for KTalk API."""


class KTalkAuthError(KTalkError):
    """Session token expired or invalid."""


class KTalkNotFoundError(KTalkError):
    """Recording not found."""


class KTalkClient:
    """Async HTTP client for KTalk API.

    Usage::

        async with KTalkClient(base_url, session_token) as client:
            recordings = await client.list_recordings()
    """

    def __init__(self, base_url: str, session_token: str) -> None:
        self._session_token = session_token
        self._client = httpx.AsyncClient(
            base_url=base_url,
            params={"sessionToken": session_token},
            timeout=30.0,
        )

    async def __aenter__(self) -> KTalkClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self._client.aclose()

    def _check_response(self, response: httpx.Response, context: str = "") -> None:
        if response.status_code in (401, 403):
            raise KTalkAuthError(
                "Токен сессии истёк или невалиден. "
                "Обновите KTALK_SESSION_TOKEN (см. README)."
            )
        if response.status_code == 404:
            raise KTalkNotFoundError(f"Ресурс не найден: {context}")
        response.raise_for_status()

    async def list_recordings(
        self,
        *,
        query: str | None = None,
        start_from: str | None = None,
        start_to: str | None = None,
        top: int = 30,
        order_mode: str = "byTimeNewFirst",
        page_token: str | None = None,
        title: str | None = None,
    ) -> dict:
        params: dict = {"top": top, "orderMode": order_mode}
        if query is not None:
            params["query"] = query
        if start_from is not None:
            params["startFrom"] = start_from
        if start_to is not None:
            params["startTo"] = start_to
        if page_token is not None:
            params["pageTokenString"] = page_token
        if title is not None:
            params["title"] = title

        response = await self._client.get("/api/recordings", params=params)
        self._check_response(response, "список записей")
        return response.json()

    async def get_recording(self, recording_key: str) -> dict:
        response = await self._client.get(
            f"/api/recordings/{recording_key}",
        )
        self._check_response(response, f"запись {recording_key}")
        return response.json()

    async def get_transcript(self, recording_key: str) -> dict:
        response = await self._client.get(
            f"/api/recordings/{recording_key}/transcript"
        )
        self._check_response(response, f"транскрипт {recording_key}")
        return response.json()

    async def get_summary(self, recording_key: str) -> dict:
        response = await self._client.get(
            f"/api/recordings/v2/{recording_key}/summary"
        )
        self._check_response(response, f"саммари {recording_key}")
        return response.json()

    async def get_summary_by_type(self, recording_key: str, summary_type: str) -> dict:
        response = await self._client.get(
            f"/api/recordings/{recording_key}/summary/{summary_type}"
        )
        self._check_response(response, f"саммари {summary_type} для {recording_key}")
        return response.json()
