"""Миграция реестра в централизованное хранилище — явный обратимый шаг (NFR-12).

Companion-спека: `content/40-architecture/ADR-013-central-transcript-store-spec.md`,
«Контракт команды миграции». Отдельно от `ktalk migrate <vault>` (`registry.py`,
`migrate_from_vault`) — та импортирует markdown-архивы (ADR-002), эта копирует
существующий SQLite-реестр на новый путь. Read-only использование `registry.py`
(построчный дамп через `sqlite3.iterdump`), не расширяет его.
"""

from __future__ import annotations

import os
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

    # BLOCK-01/MAJ-03 (security review SEC-003): права цели — NFR-15 (0700/0600)
    # независимо от прав источника и от ambient umask, безусловно, не только при
    # первом создании каталога — `mkdir(exist_ok=True)` не чинит уже существующий
    # каталог со слабыми правами.
    target.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(target.parent, 0o700)

    # MIN-01: check-then-act между `target.exists()` и созданием файла закрыт —
    # `O_EXCL` делает проверку-и-создание одной атомарной операцией ОС, не двумя
    # раздельными шагами. Явный `mode=0o600` при создании — права заданы с
    # рождения файла, не пост-хок `chmod`/`copy2` (который перенёс бы биты
    # источника поверх).
    try:
        fd = os.open(str(target), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise MigrationTargetExistsError(
            f"Целевой файл уже существует: {target} — повторная миграция не "
            "перезаписывает данные, добавленные после предыдущей миграции"
        ) from exc

    try:
        with os.fdopen(fd, "wb") as dst_f, open(source, "rb") as src_f:
            shutil.copyfileobj(src_f, dst_f)
        os.chmod(target, 0o600)  # copyfileobj не переносит metadata — явный chmod всё равно
    except BaseException:
        target.unlink(missing_ok=True)
        raise

    if not _dumps_match(source, target):
        target.unlink(missing_ok=True)
        raise MigrationVerificationError(
            f"Сверка дампа не совпала: {source} != {target}; источник не тронут, "
            "целевой файл удалён"
        )

    backup = source.with_name(f"{source.name}.pre-migration-{date.today().isoformat()}")
    source.rename(backup)
    return target
