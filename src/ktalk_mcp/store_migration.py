"""Миграция реестра в централизованное хранилище — явный обратимый шаг (NFR-12).

Companion-спека: `content/40-architecture/ADR-013-central-transcript-store-spec.md`,
«Контракт команды миграции». Отдельно от `ktalk migrate <vault>` (`registry.py`,
`migrate_from_vault`) — та импортирует markdown-архивы (ADR-002), эта копирует
существующий SQLite-реестр на новый путь. Read-only использование `registry.py`
(построчный дамп через `sqlite3.iterdump`), не расширяет его.
"""

from __future__ import annotations

import shutil
import sqlite3
from datetime import date
from pathlib import Path


class MigrationVerificationError(Exception):
    """Построчная сверка дампа источник<->копия не совпала — миграция отменена,
    источник не тронут, целевой файл удалён (не остаётся частичной копией)."""


class MigrationTargetExistsError(Exception):
    """Целевой файл уже существует — повторный вызов не перезаписывает данные,
    добавленные в централизованное хранилище другим проектом после первой
    миграции."""


def _dump_lines(db_path: Path) -> list[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        return list(conn.iterdump())
    finally:
        conn.close()


def _dumps_match(source: Path, target: Path) -> bool:
    return _dump_lines(source) == _dump_lines(target)


def migrate_to_central_store(source: str | Path, target: str | Path) -> Path:
    """Copy -> построчная сверка дампа -> backup-переименование источника.

    Источник не удаляется — переименовывается в `<имя>.pre-migration-<дата>`
    только после совпадения сверки. Не запускается неявно (NFR-12 AC-1) — вызов
    только явный, из отдельной CLI-команды/скрипта, не из `Registry.__init__`.
    """
    source = Path(source)
    target = Path(target)

    if target.exists():
        raise MigrationTargetExistsError(
            f"Целевой файл уже существует: {target} — повторная миграция не "
            "перезаписывает данные, добавленные после предыдущей миграции"
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)

    if not _dumps_match(source, target):
        target.unlink(missing_ok=True)
        raise MigrationVerificationError(
            f"Сверка дампа не совпала: {source} != {target}; источник не тронут, "
            "целевой файл удалён"
        )

    backup = source.with_name(f"{source.name}.pre-migration-{date.today().isoformat()}")
    source.rename(backup)
    return target
