"""ADR-011 §2: компоновка данных отмены встречи (без сети).

Параллель `meeting_scheduling.PreviewService` — чистые функции, без `KTalkClient`,
физическая невозможность сетевого вызова из этого модуля.
"""

from __future__ import annotations

from ktalk_cli.confirmation import ConfirmationStore
from ktalk_cli.meeting_body import canonical_body_hash


def build_cancel_confirmation_payload(*, id: str, reason: str = "") -> dict:
    """Не тело запроса (то — `{"reason": reason}`), а предмет хеширования
    подтверждения (ADR-011 п.2): `id` — часть пути, не тела, но обязан входить
    в хеш, иначе подтверждение для одной встречи матчится для любой другой.
    `operation` — дискриминатор против путаницы с будущим подтверждением
    `update_meeting` на том же `id`."""
    return {"operation": "cancel_meeting", "id": id, "reason": reason}


class CancelPreviewService:
    """Параллель `PreviewService` (`meeting_scheduling.py`) — тот же
    `ConfirmationStore`, та же `canonical_body_hash`."""

    def __init__(self, store: ConfirmationStore) -> None:
        self._store = store

    def preview(self, *, id: str, reason: str = "") -> tuple[dict, str]:
        payload = build_cancel_confirmation_payload(id=id, reason=reason)
        payload_hash = canonical_body_hash(payload)
        confirmation_id = self._store.issue(payload_hash)
        return payload, confirmation_id
