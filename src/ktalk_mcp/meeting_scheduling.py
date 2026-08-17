"""FR-13 §6.6: предпросмотр (без сети) + создание (ровно одна сетевая попытка).

`create_meeting` — свободная функция вне `client.py` (гейт C13), тем же приёмом,
что `rooms.get_room`/`calendar_reader._fetch_segment`.
"""

from __future__ import annotations

from ktalk_mcp.client import KTalkClient
from ktalk_mcp.confirmation import ConfirmationStore
from ktalk_mcp.meeting_body import build_meeting_body, canonical_body_hash


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
    """Ровно одна сетевая попытка `POST /calendar` (без `/api`), без retry."""
    profile = client._profile_for("create_meeting")  # noqa: SLF001
    response = await client._client.post(profile.path_template, json=body)  # noqa: SLF001
    client._classify(response, profile.required_scope)  # noqa: SLF001
    return response.json()
