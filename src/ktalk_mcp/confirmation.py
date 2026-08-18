"""FR-13 §6.2: хранилище подтверждений — TTL, single-use, привязка к хешу тела
(ADR-005-spec «Форма подтверждения»/«Сценарии отказа»).

ADR-016 §2: хранилище переехало из памяти в файл `$XDG_STATE_HOME/ktalk`. Вывод
ADR-015 «`confirmation_id` не переживает границу процессов» был следствием
хранилища в памяти, а не свойством задачи, и снят вместе с причиной: агент теперь
выполняет и предпросмотр, и подтверждение, и именно id связывает предъявленное
оператору тело с фактической записью.

TTL, одноразовость и неразличимость причин отказа (`match` возвращает один `False`)
не пересматриваются. Битый или нечитаемый файл читается как пустое хранилище —
fail-closed: все подтверждения недействительны, а не «проверку пропустить».
"""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Дизайн-выбор, не измеренная величина (тот же класс решения, что concurrency=5 в
# enrichment.py) — обоснование в rooms-calendar-spec §6.2.
CONFIRMATION_TTL = timedelta(minutes=10)


@dataclass(frozen=True)
class ConfirmationRecord:
    body_hash: str
    expires_at: datetime  # UTC-aware


def confirmation_store_path() -> Path:
    """Состояние, а не конфигурация -> `$XDG_STATE_HOME`, не `$XDG_CONFIG_HOME`;
    и не рядом с транскриптами в `$XDG_DATA_HOME` (ADR-013 — данные пользователя,
    переживающие переустановку; подтверждение живёт десять минут)."""
    xdg_state_home = os.environ.get("XDG_STATE_HOME") or None
    root = Path(xdg_state_home) if xdg_state_home else Path.home() / ".local" / "state"
    return root / "ktalk" / "pending-confirmations.json"


class ConfirmationStore:
    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        path: Path | None = None,
    ) -> None:
        self._clock = clock
        self._path = path

    @property
    def path(self) -> Path:
        return self._path if self._path is not None else confirmation_store_path()

    def _load(self) -> dict[str, ConfirmationRecord]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        records: dict[str, ConfirmationRecord] = {}
        if not isinstance(raw, dict):
            return {}
        for confirmation_id, record in raw.items():
            try:
                expires_at = datetime.fromisoformat(record["expires_at"])
                records[confirmation_id] = ConfirmationRecord(
                    body_hash=record["body_hash"], expires_at=expires_at
                )
            except (TypeError, KeyError, ValueError):
                continue
        return records

    def _save(self, records: dict[str, ConfirmationRecord]) -> None:
        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        payload = {
            confirmation_id: {
                "body_hash": record.body_hash,
                "expires_at": record.expires_at.isoformat(),
            }
            for confirmation_id, record in records.items()
        }
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(path)

    def issue(self, body_hash: str) -> str:
        """Непредсказуемый одноразовый идентификатор, не производный от `body_hash`
        — иначе агент вычислил бы его локально, минуя факт вызова предпросмотра.
        Попутно вычищает истёкшие записи: файл не растёт бесконечно, и уборка не
        требует отдельной команды."""
        # Префикс `c` — не украшение: `token_urlsafe` может начаться с `-`, и такой
        # id argparse принимает за флаг (`--confirmation-id -x8Q…` -> «expected one
        # argument»). В памяти это было безразлично, на границе командной строки —
        # плавающий отказ примерно в каждом двадцатом вызове (DEV-012).
        confirmation_id = f"c{secrets.token_urlsafe(24)}"
        now = self._clock()
        records = {
            key: record for key, record in self._load().items() if now < record.expires_at
        }
        records[confirmation_id] = ConfirmationRecord(
            body_hash=body_hash, expires_at=now + CONFIRMATION_TTL
        )
        self._save(records)
        return confirmation_id

    def match(self, confirmation_id: str, body_hash: str) -> bool:
        """id неизвестен/потреблён/TTL истёк/хеш не совпал -> одно и то же `False`
        (не различаем причины наружу — ничего из этого не должно ускользать в
        подсказку "как обойти")."""
        record = self._load().get(confirmation_id)
        if record is None:
            return False
        if self._clock() >= record.expires_at:
            return False
        return record.body_hash == body_hash

    def consume(self, confirmation_id: str) -> None:
        """Вызывается ДО сетевой попытки — повтор после сбоя требует нового
        предпросмотра и нового подтверждения, не автоматического retry."""
        records = self._load()
        if records.pop(confirmation_id, None) is not None:
            self._save(records)
