"""FR-13 §6.6: предпросмотр (без сети) + создание (ровно одна сетевая попытка).

`create_meeting` — свободная функция вне `client.py` (гейт C13), тем же приёмом,
что `rooms.get_room`/`calendar_reader._fetch_segment`.
"""

from __future__ import annotations

import logging

from ktalk_mcp.client import KTalkClient
from ktalk_mcp.confirmation import ConfirmationStore
from ktalk_mcp.contour_diagnostics import TRANSIENT_ERRORS, diagnose_undocumented_failure
from ktalk_mcp.meeting_body import build_meeting_body, canonical_body_hash

logger = logging.getLogger(__name__)


class PreviewService:
    def __init__(self, store: ConfirmationStore) -> None:
        self._store = store

    def preview(self, **fields: object) -> tuple[dict, str]:
        """`build_meeting_body` -> `canonical_body_hash` -> `store.issue`. Без сети
        физически — не получает `KTalkClient` (структурная невозможность, не
        поведенческая)."""
        body = build_meeting_body(**fields)
        body_hash = canonical_body_hash(body)
        confirmation_id = self._store.issue(body_hash)
        return body, confirmation_id


async def create_meeting(client: KTalkClient, body: dict) -> dict:
    """Ровно одна сетевая попытка `POST /api/calendar`, без retry. ADR-007 п.3:
    оборачивается корреляционной диагностикой ADR-004, тем же приёмом, что
    `calendar_reader._fetch_segment` — сбой недокументированного пути неотличим
    от обычного auth/сетевого сбоя без контрольного вызова.

    ADR-008: на `profile.mutating` (сегодня только session-режим этой операции)
    добавляется заголовок `Authorization: Session <token>` поверх query-параметра
    (не вместо — ADR-003 инвариант транспорта чтения не трогается). Тело ответа
    4xx/5xx читается до классификации и прикрепляется к перехваченному исключению
    атрибутом `response_body` (обрезано до 500 символов) — переживает прогон
    независимо от конфигурации `logging`, которой в проекте нет."""
    profile = client._profile_for("create_meeting")  # noqa: SLF001
    headers = (
        {"Authorization": f"Session {client._auth.credential}"}  # noqa: SLF001
        if profile.mutating
        else None
    )
    try:
        response = await client._client.post(  # noqa: SLF001
            profile.path_template, json=body, headers=headers
        )
    except TRANSIENT_ERRORS as exc:
        await diagnose_undocumented_failure(client, "create_meeting", exc)
        raise  # недостижимо

    body_text = response.text[:500] if response.status_code >= 400 else None
    if body_text:
        logger.warning("create_meeting: HTTP %s, тело: %s", response.status_code, body_text)

    try:
        client._classify(response, profile.required_scope)  # noqa: SLF001
    except TRANSIENT_ERRORS as exc:
        if body_text:
            exc.response_body = body_text  # атрибут читает CLI/MCP на границе вывода
        await diagnose_undocumented_failure(client, "create_meeting", exc)
        raise  # недостижимо
    return response.json()
