"""FR-13 §6.2: хранилище подтверждений — TTL, single-use, привязка к хешу тела
(ADR-005-spec «Форма подтверждения»/«Сценарии отказа»).

`ConfirmationStore` инстанцируется заново на каждый вызов предпросмотра/подтверждения,
не синглтон уровня процесса — пара (хеш, срок) живёт только в памяти вызывающего пути
(§6.3 rooms-calendar-spec).
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# Дизайн-выбор, не измеренная величина (тот же класс решения, что concurrency=5 в
# enrichment.py) — обоснование в rooms-calendar-spec §6.2.
CONFIRMATION_TTL = timedelta(minutes=10)


@dataclass(frozen=True)
class ConfirmationRecord:
    body_hash: str
    expires_at: datetime  # UTC-aware


class ConfirmationStore:
    def __init__(
        self, *, clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)
    ) -> None:
        self._clock = clock
        self._records: dict[str, ConfirmationRecord] = {}

    def issue(self, body_hash: str) -> str:
        """Непредсказуемый одноразовый идентификатор, не производный от `body_hash`
        — иначе агент вычислил бы его локально, минуя факт вызова предпросмотра."""
        confirmation_id = secrets.token_urlsafe(24)
        self._records[confirmation_id] = ConfirmationRecord(
            body_hash=body_hash, expires_at=self._clock() + CONFIRMATION_TTL
        )
        return confirmation_id

    def match(self, confirmation_id: str, body_hash: str) -> bool:
        """id неизвестен/потреблён/TTL истёк/хеш не совпал -> одно и то же `False`
        (не различаем причины наружу — ничего из этого не должно ускользать в
        подсказку "как обойти")."""
        record = self._records.get(confirmation_id)
        if record is None:
            return False
        if self._clock() >= record.expires_at:
            return False
        return record.body_hash == body_hash

    def consume(self, confirmation_id: str) -> None:
        """Вызывается ДО сетевой попытки — повтор после сбоя требует нового
        предпросмотра и нового подтверждения, не автоматического retry."""
        self._records.pop(confirmation_id, None)
