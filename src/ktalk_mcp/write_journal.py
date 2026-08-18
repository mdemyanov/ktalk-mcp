"""ADR-016 §4/§5: журнал пишущих операций — прослеживаемость каждой попытки.

Две строки на операцию, не одна: `attempt` без парной `outcome` — машинный след
«процесс не дожил до ответа», отличимый от «ответа не было» (`result: unknown`).
Именно этот класс исходов стоил волне 0.6.0 четырёх разборов вручную.

Отказ записи `attempt` — fail-closed: сетевого вызова не будет. Иначе
прослеживаемость исчезает ровно тогда, когда она нужна.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from ktalk_mcp.config import redact_secrets


class JournalUnavailableError(OSError):
    """Журнал недоступен для записи — пишущая операция не выполняется."""


def journal_path() -> Path:
    xdg_state_home = os.environ.get("XDG_STATE_HOME") or None
    root = Path(xdg_state_home) if xdg_state_home else Path.home() / ".local" / "state"
    return root / "ktalk" / "write-ops.jsonl"


def _append(record: dict) -> None:
    path = journal_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        existed = path.exists()
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        if not existed:
            os.chmod(path, 0o600)
    except OSError as exc:
        raise JournalUnavailableError(f"Журнал операций недоступен для записи: {exc}") from exc


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def append_attempt(
    *,
    operation: str,
    channel: str,
    confirmation_id: str,
    body_sha256: str,
    body: dict,
    sanction_remaining: int | None,
) -> None:
    """Тело проходит `redact_secrets` тем же вызовом, что и вывод ошибок — новой
    точки маскирования не вводится (NFR-21)."""
    _append(
        {
            "ts": _now(),
            "event": "attempt",
            "operation": operation,
            "channel": channel,
            "confirmation_id": confirmation_id,
            "body_sha256": body_sha256,
            "body": json.loads(redact_secrets(json.dumps(body, ensure_ascii=False))),
            "sanction_remaining": sanction_remaining,
        }
    )


def append_outcome(
    *,
    operation: str,
    channel: str,
    confirmation_id: str,
    body_sha256: str,
    result: str,
    status_code: int | None,
) -> None:
    _append(
        {
            "ts": _now(),
            "event": "outcome",
            "operation": operation,
            "channel": channel,
            "confirmation_id": confirmation_id,
            "body_sha256": body_sha256,
            "result": result,
            "status_code": status_code,
        }
    )
