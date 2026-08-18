"""ADR-016 §2: файловая санкция контура записи — срок, бюджет, независимые ключи.

Механика ADR-014 §2 (fail-closed чтение, атомарная запись, права 0700/0600)
переиспользована целиком; отличия продиктованы предметом — запись в боевой контур,
а не установка пакета: срок и бюджет обязательны и конечны, ключ на каждую операцию.

Проверки интерактивного терминала здесь нет намеренно: она живёт в `cli_sanction.py`.
Модуль остаётся тестируемым, барьер — непроходимым из кода, потому что единственный
путь к `grant()` снаружи пакета проходит через CLI.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

OPERATIONS = ("create_meeting", "cancel_meeting")

# Дизайн-выбор, не измеренная величина (тот же класс решения, что CONFIRMATION_TTL):
# обоснование и правило пересмотра — ADR-016-agent-executed-writes-spec.md §2.
DEFAULT_HOURS = 8
MAX_HOURS = 24 * 7
DEFAULT_OPERATIONS = 3
MAX_OPERATIONS = 20


class SanctionError(Exception):
    """Санкция не действует — код возврата несёт вызывающий CLI (ADR-016-spec §3)."""

    def __init__(self, status: str) -> None:
        super().__init__(f"Санкция на запись не действует: {status}")
        self.status = status


@dataclass(frozen=True)
class SanctionState:
    """`status`: active | absent | expired | exhausted. `absent` — общий исход для
    отсутствия, отзыва и любой порчи файла (fail-closed, ADR-016 §4)."""

    operation: str
    status: str
    expires_at: str | None = None
    remaining: int | None = None

    @property
    def active(self) -> bool:
        return self.status == "active"


def sanction_path() -> Path:
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME") or None
    root = Path(xdg_config_home) if xdg_config_home else Path.home() / ".config"
    return root / "ktalk" / "write-sanction.toml"


def _read_raw() -> dict:
    path = sanction_path()
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _parse_utc(raw: object) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def read_state(operation: str, *, now: datetime | None = None) -> SanctionState:
    """Все условия обязаны выполниться одновременно; любое иное состояние — `absent`.
    Различаются только `expired` и `exhausted`: они полезны оператору на его
    собственной машине и не являются секретом (ADR-016-spec §2)."""
    _check_operation(operation)
    section = _read_raw().get(operation)
    if not isinstance(section, dict) or section.get("allowed") is not True:
        return SanctionState(operation, "absent")

    expires_at = _parse_utc(section.get("expires_at"))
    remaining = section.get("remaining")
    if expires_at is None or not isinstance(remaining, int) or isinstance(remaining, bool):
        return SanctionState(operation, "absent")

    iso = expires_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if expires_at <= (now or datetime.now(timezone.utc)):
        return SanctionState(operation, "expired", iso, remaining)
    if remaining <= 0:
        return SanctionState(operation, "exhausted", iso, remaining)
    return SanctionState(operation, "active", iso, remaining)


def _check_operation(operation: str) -> None:
    if operation not in OPERATIONS:
        raise ValueError(f"Неизвестная операция: {operation!r}; допустимы {OPERATIONS}")


def _write_raw(data: dict) -> None:
    path = sanction_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    lines: list[str] = []
    for operation in OPERATIONS:
        section = data.get(operation)
        if not isinstance(section, dict):
            continue
        lines.append(f"[{operation}]")
        for key, value in section.items():
            if isinstance(value, bool):
                lines.append(f"{key} = {str(value).lower()}")
            elif isinstance(value, int):
                lines.append(f"{key} = {value}")
            else:
                lines.append(f'{key} = "{value}"')
        lines.append("")
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text("\n".join(lines), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def grant(
    operation: str,
    *,
    hours: int = DEFAULT_HOURS,
    operations: int = DEFAULT_OPERATIONS,
    now: datetime | None = None,
) -> SanctionState:
    """Запрос за потолком отклоняется, а не усекается молча: усечение выдало бы
    мандат, о котором оператор не просил и о котором он не знает."""
    _check_operation(operation)
    if not 1 <= hours <= MAX_HOURS:
        raise ValueError(f"Срок санкции — от 1 до {MAX_HOURS} часов, получено: {hours}")
    if not 1 <= operations <= MAX_OPERATIONS:
        raise ValueError(
            f"Бюджет санкции — от 1 до {MAX_OPERATIONS} операций, получено: {operations}"
        )

    moment = now or datetime.now(timezone.utc)
    data = _read_raw()
    data[operation] = {
        "allowed": True,
        "expires_at": _iso(moment + timedelta(hours=hours)),
        "remaining": operations,
        "granted_at": _iso(moment),
    }
    _write_raw(data)
    return read_state(operation)


def revoke(operation: str) -> None:
    """Секция не удаляется — отзыв обязан быть наблюдаем в `status` (ADR-014 §2)."""
    _check_operation(operation)
    data = _read_raw()
    section = data.get(operation)
    data[operation] = {**(section if isinstance(section, dict) else {}), "allowed": False}
    _write_raw(data)


def consume(operation: str) -> int:
    """Списание — до сетевой попытки, независимо от исхода (NFR-22)."""
    state = read_state(operation)
    if not state.active:
        raise SanctionError(state.status)
    data = _read_raw()
    remaining = int(state.remaining or 0) - 1
    data[operation] = {**data[operation], "remaining": remaining}
    _write_raw(data)
    return remaining


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
