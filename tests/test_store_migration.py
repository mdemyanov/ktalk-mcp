"""AT-design: NFR-12 — миграция реестра в централизованное хранилище — явный
обратимый шаг (не побочный эффект установки/первого запуска).

Покрывает контракт с QA-author ADR-013-central-transcript-store-spec.md,
«Контракт команды миграции»: copy -> построчная сверка дампа -> backup-переименование
источника; несовпадение дампа -> отказ, источник не тронут, целевой файл удалён;
повторный вызов не должен тихо перезаписать более новые данные назначения.

Отдельный модуль от `tests/test_migration.py` (тот покрывает `ktalk migrate
<vault>` — импорт из markdown-архивов, ADR-002, другая команда) — не путать.

NFR-12 AC-3 (откат) — ручная проверка по runbook (OPS-001), не автоматизируется по
AC; здесь не покрывается (см. at-design «Не покрываем»).

Красные по замыслу: команда миграции хранилища ещё не существует — рабочее имя и
точная сигнатура (модуль-функция vs CLI-команда) уточняет Dev (ADR-013-spec,
«Реализовать»). Стаб называет функцию `migrate_to_central_store(source, target)`
как рабочую гипотезу; переименование — точечная правка импорта.
"""

from __future__ import annotations

from pathlib import Path


def _seed_registry(db_path: Path):
    from ktalk_mcp.registry import Registry

    with Registry(db_path) as reg:
        reg.upsert_recording(
            {"recording_id": "a", "name": "Standup", "date": "2026-06-24"},
            now="2026-06-24",
        )
        reg.upsert_recording(
            {"recording_id": "b", "name": "1-1", "date": "2026-06-20"},
            now="2026-06-20",
        )
        reg.set_status("b", "done")
    return db_path


# --- NFR-12 AC-1: установка/открытие реестра само по себе не переносит файл -------


def test_ac_nfr12_1_opening_registry_alone_does_not_move_or_copy_source_file(
    tmp_path,
):
    from ktalk_mcp.registry import Registry

    source = tmp_path / "95_TRANSCRIPTS" / ".registry.db"
    source.parent.mkdir(parents=True)
    _seed_registry(source)

    with Registry(source):
        pass  # обычная операция реестра — не команда миграции

    assert source.exists(), "TODO: NFR-12 AC-1 — файл реестра остаётся на прежнем пути"


# --- NFR-12 AC-2: миграция без потерь и без изменения значений --------------------


def test_ac_nfr12_2_migration_preserves_all_records_without_loss_or_value_change(
    tmp_path,
):
    from ktalk_mcp.registry import Registry
    from ktalk_mcp.store_migration import migrate_to_central_store

    source = tmp_path / "source" / ".registry.db"
    source.parent.mkdir(parents=True)
    _seed_registry(source)
    target = tmp_path / "target" / "registry.db"

    migrate_to_central_store(source, target)

    with Registry(target) as reg:
        a = reg.get_recording("a")
        b = reg.get_recording("b")
    assert a is not None and a["name"] == "Standup" and a["date"] == "2026-06-24"
    assert b is not None and b["status"] == "done"


def test_migration_success_renames_source_to_backup_suffix_not_deleted(tmp_path):
    from ktalk_mcp.store_migration import migrate_to_central_store

    source = tmp_path / "source" / ".registry.db"
    source.parent.mkdir(parents=True)
    _seed_registry(source)
    target = tmp_path / "target" / "registry.db"

    migrate_to_central_store(source, target)

    assert not source.exists(), "источник переименован, не остаётся на прежнем имени"
    backups = list(source.parent.glob(".registry.db*"))
    assert backups, "TODO: NFR-12 — источник переименован в backup-суффикс, не удалён"


def test_migration_dump_mismatch_aborts_source_untouched_target_removed(
    tmp_path, monkeypatch
):
    """Boundary: если построчная сверка дампа источник<->копия не совпала —
    команда завершается ошибкой, источник остаётся без изменений, целевой файл не
    остаётся частичной копией."""
    import ktalk_mcp.store_migration as store_migration

    source = tmp_path / "source" / ".registry.db"
    source.parent.mkdir(parents=True)
    _seed_registry(source)
    target = tmp_path / "target" / "registry.db"

    # Форсируем расхождение дампа — deliberate injection, а не реальный баг копирования.
    monkeypatch.setattr(
        store_migration, "_dumps_match", lambda src, dst: False, raising=False
    )

    import pytest

    with pytest.raises(store_migration.MigrationVerificationError):
        store_migration.migrate_to_central_store(source, target)

    assert source.exists(), "источник не тронут при несовпадении сверки"
    assert not target.exists(), "целевой файл удалён, не остаётся частичной копией"


def test_migration_repeated_call_does_not_silently_overwrite_newer_target_data(
    tmp_path,
):
    """Boundary (ADR-013-spec edge case): повторный вызов команды при уже
    существующем файле по целевому пути — не должен тихо перезаписать более новые
    данные централизованного хранилища."""
    from ktalk_mcp.registry import Registry
    from ktalk_mcp.store_migration import (
        MigrationTargetExistsError,
        migrate_to_central_store,
    )

    source = tmp_path / "source" / ".registry.db"
    source.parent.mkdir(parents=True)
    _seed_registry(source)
    target = tmp_path / "target" / "registry.db"
    migrate_to_central_store(source, target)

    # Целевой файл получает новую запись ПОСЛЕ первой миграции (другой проект).
    with Registry(target) as reg:
        reg.upsert_recording(
            {"recording_id": "c", "name": "После миграции", "date": "2026-07-01"},
            now="2026-07-01",
        )

    # Второй источник (например, другой vault) мигрирует на тот же target.
    second_source = tmp_path / "second-source" / ".registry.db"
    second_source.parent.mkdir(parents=True)
    _seed_registry(second_source)

    import pytest

    with pytest.raises(MigrationTargetExistsError):
        migrate_to_central_store(second_source, target)

    with Registry(target) as reg:
        assert reg.get_recording("c") is not None, (
            "TODO: NFR-12 — повторная миграция не должна тихо стереть запись 'c'"
        )


# --- BLOCK-01 (security review SEC-003): NFR-15-права на цель независимо от источника ---


def test_block01_target_gets_owner_only_permissions_regardless_of_source_mode(
    tmp_path, monkeypatch
):
    """Воспроизведение из отчёта (security-review-ktalk-plugin.md, BLOCK-01):
    ambient umask 0o022, resolve_store_root() не вызывается (миграция — отдельный
    вызов, не обязана полагаться на то, что кто-то ранее в процессе позвал
    resolve_store_root()). Источник — обычный (0644/0755) файл vault'а. Цель
    обязана получить 0600/0700 независимо от режима источника."""
    import stat

    from ktalk_mcp.store_migration import migrate_to_central_store

    monkeypatch.setattr("os.umask", lambda mask: 0o022)  # ambient, не 0o077

    source = tmp_path / "vault" / ".registry.db"
    source.parent.mkdir(parents=True)
    _seed_registry(source)
    source.chmod(0o644)
    source.parent.chmod(0o755)

    target = tmp_path / "central" / "registry.db"

    migrate_to_central_store(source, target)

    target_mode = stat.S_IMODE(target.stat().st_mode)
    parent_mode = stat.S_IMODE(target.parent.stat().st_mode)
    assert target_mode == 0o600, (
        f"TODO: BLOCK-01 — целевой файл должен быть 0600, получено {oct(target_mode)}"
    )
    assert parent_mode == 0o700, (
        f"TODO: BLOCK-01 — родительский каталог цели должен быть 0700, получено {oct(parent_mode)}"
    )


def test_min01_target_creation_is_atomic_not_check_then_act(tmp_path):
    """MIN-01: между проверкой существования и созданием файла не должно быть
    окна для check-then-act — второй вызов на уже занятый target обязан упасть
    ДО того, как что-либо запишется, без полагания на предварительный
    `target.exists()`. Регрессионно фиксируется тем же наблюдаемым эффектом,
    что и `test_migration_repeated_call_does_not_silently_overwrite_newer_target_data`
    (уже покрыт), плюс явная проверка: `target` не остаётся пустым/частичным
    файлом-«меткой» при отказе — либо не создан, либо содержит только пришедшие
    ранее валидные данные."""
    from ktalk_mcp.registry import Registry
    from ktalk_mcp.store_migration import (
        MigrationTargetExistsError,
        migrate_to_central_store,
    )

    source = tmp_path / "source" / ".registry.db"
    source.parent.mkdir(parents=True)
    _seed_registry(source)
    target = tmp_path / "target" / "registry.db"
    migrate_to_central_store(source, target)

    with Registry(target) as reg:
        before = reg.get_recording("a")
    assert before is not None

    second_source = tmp_path / "second-source" / ".registry.db"
    second_source.parent.mkdir(parents=True)
    _seed_registry(second_source)

    import pytest

    with pytest.raises(MigrationTargetExistsError):
        migrate_to_central_store(second_source, target)

    with Registry(target) as reg:
        after = reg.get_recording("a")
    assert after == before, "цель не должна быть перезаписана/повреждена отклонённой попыткой"
