"""Централизованное машинное хранилище (ADR-013): корень, права, детекция
облачной синхронизации.

Companion-спека: `content/40-architecture/ADR-013-central-transcript-store-spec.md`.
Отдельный модуль от `registry.py` (грандфазер заморожен на 562 строках).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_STORE_DIR_NAME = "ktalk"

# NFR-14: маркеры известных каталогов облачной синхронизации. Сегментация по
# границе каталога, не substring — `MyDropboxBackup/` не должен ложно
# сработать на `Dropbox` (ADR-013-spec, boundary).
_SYNC_MULTI_SEGMENT_MARKERS: tuple[tuple[str, str], ...] = (
    ("Library", "Mobile Documents"),
    ("Library", "CloudStorage"),
)
_SYNC_SINGLE_SEGMENT_MARKERS: tuple[str, ...] = (
    "Dropbox",
    "Google Drive",
    "OneDrive",
    "Nextcloud",
    "ownCloud",
)


def resolve_store_root() -> Path:
    """Резолвит и создаёт корень централизованного хранилища (ADR-013 §1).

    `${XDG_DATA_HOME:-$HOME/.local/share}/ktalk`. `$XDG_DATA_HOME=""` (пустая
    строка) трактуется как «не задано», не как путь `""` (boundary case).

    Права `0700` на каталог и, transitively, `0600` на файлы, создаваемые этим
    процессом впоследствии (в т.ч. `registry.db` через `sqlite3.connect`) —
    обеспечивается процессным `umask`, применённым здесь один раз, а не
    ретроактивным `chmod` (NFR-15: «без окна между созданием и ограничением
    прав»). Побочный эффект осознанный: с момента первого разрешения корня
    хранилища процесс создаёт любые файлы владелец-only до конца своего цикла
    жизни — это соответствует всей раскладке хранилища (`registry.db`, `-wal`,
    `-shm`, `transcripts/`, `eval/reports/`), не только одному файлу.
    """
    xdg_data_home = os.environ.get("XDG_DATA_HOME") or None
    if xdg_data_home:
        base = Path(xdg_data_home)
    else:
        home = os.environ.get("HOME") or str(Path.home())
        base = Path(home) / ".local" / "share"
    root = base / _STORE_DIR_NAME
    os.umask(0o077)
    root.mkdir(parents=True, exist_ok=True)
    # MAJ-03 (security review SEC-003): `mkdir(exist_ok=True)` не чинит режим уже
    # существующего каталога — безусловный `chmod`, не только при первом создании,
    # закрывает случай «каталог остался с ослабленными правами от более ранней
    # версии/ручного создания/восстановления из бэкапа».
    os.chmod(root, 0o700)
    return root


def detect_sync_dir(path: str | Path) -> tuple[bool, str]:
    """Эвристика NFR-14: путь внутри известного каталога облачной синхронизации.

    Не платформенный API (нет надёжного), а сегментированная проверка частей
    пути — не гарантия, известное ограничение (ADR-013, Consequences).
    """
    parts = [p.lower() for p in Path(path).parts]
    for seg1, seg2 in _SYNC_MULTI_SEGMENT_MARKERS:
        s1, s2 = seg1.lower(), seg2.lower()
        for i in range(len(parts) - 1):
            if parts[i] == s1 and parts[i + 1] == s2:
                return True, f"путь внутри каталога облачной синхронизации ({seg1}/{seg2})"
    for marker in _SYNC_SINGLE_SEGMENT_MARKERS:
        if marker.lower() in parts:
            return True, f"путь внутри каталога облачной синхронизации ({marker})"
    return False, "путь вне известных каталогов облачной синхронизации"


def warn_if_sync_dir(path: str | Path) -> bool:
    """NFR-14 AC-2: путь внутри каталога синхронизации -> предупреждение в
    stderr, работа продолжается (не блокировка)."""
    is_sync, reason = detect_sync_dir(path)
    if is_sync:
        print(f"Предупреждение: {reason}: {path}", file=sys.stderr)
    return is_sync
