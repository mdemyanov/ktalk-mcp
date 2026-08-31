"""CLI-обвязка миграции в централизованное хранилище (NFR-12, MAJ-04 security
review SEC-003).

Отдельная явная команда — `migrate_to_central_store` (`store_migration.py`) не
запускается неявно ни из установки, ни из первого открытия реестра
(ADR-013-central-transcript-store-spec.md, «Контракт команды миграции»).
Не путать с `ktalk migrate <vault>` (`registry.py::migrate_from_vault`, импорт
markdown-архивов ADR-002) — разные команды, разные модули.

Команда не входит в `_REGISTRY_FREE_COMMANDS` (cli.py) в смысле "не открывает
БД вообще" — она открывает и путь-источник, и путь-цель сама, вручную, минуя
`Registry(resolve_db_path(...))`, поэтому регистрируется отдельным хендлером,
принимающим `reg=None` не глядя.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from ktalk_cli.config import redact_secrets
from ktalk_cli.store import resolve_store_root
from ktalk_cli.store_migration import (
    MigrationTargetExistsError,
    MigrationVerificationError,
    migrate_to_central_store,
)


def register_subparsers(sub) -> None:
    p = sub.add_parser(
        "migrate-to-central-store",
        help="Перенести SQLite-реестр в централизованное хранилище (NFR-12)",
    )
    p.add_argument("source", help="Путь к существующему registry.db (vault)")
    p.add_argument(
        "--target",
        default=None,
        help="Путь назначения (по умолчанию — машинный дефолт store.resolve_store_root())",
    )
    p.add_argument("--json", action="store_true")


def cmd_migrate_to_central_store(reg, args) -> int:  # noqa: ARG001 - reg не используется (см. модуль)
    source = Path(args.source)
    target = Path(args.target) if args.target else resolve_store_root() / "registry.db"

    try:
        migrate_to_central_store(source, target)
    except (MigrationTargetExistsError, MigrationVerificationError) as exc:
        print(f"Ошибка: {redact_secrets(str(exc))}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"source": str(source), "target": str(target)}, ensure_ascii=False))
    else:
        print(f"Перенесено: {source} -> {target}")
    return 0
