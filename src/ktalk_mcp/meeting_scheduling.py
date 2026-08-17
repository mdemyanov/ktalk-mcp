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
    от обычного auth/сетевого сбоя без контрольного вызова."""
    profile = client._profile_for("create_meeting")  # noqa: SLF001
    try:
        response = await client._client.post(profile.path_template, json=body)  # noqa: SLF001
    except TRANSIENT_ERRORS as exc:
        await diagnose_undocumented_failure(client, "create_meeting", exc)
        raise  # недостижимо

    if response.status_code >= 400:
        logger.warning(
            "create_meeting: HTTP %s, тело: %s", response.status_code, response.text
        )

    try:
        client._classify(response, profile.required_scope)  # noqa: SLF001
    except TRANSIENT_ERRORS as exc:
        await diagnose_undocumented_failure(client, "create_meeting", exc)
        raise  # недостижимо
    return response.json()
