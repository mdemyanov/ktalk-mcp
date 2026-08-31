"""Security review SEC-003, MAJ-04: NFR-12 требует явную CLI-команду для
`migrate_to_central_store` — до этой правки функция не была достижима из `ktalk`.

Отчёт: content/40-architecture/security-review-ktalk-plugin.md, раздел MAJ-04.
Не путать с `ktalk migrate <vault>` (импорт markdown-архивов, ADR-002) — команда
названа `migrate-to-central-store`, не пересекается по имени.
"""

from __future__ import annotations

import json
import stat


def _seed(db_path):
    from ktalk_cli.registry import Registry

    with Registry(db_path) as reg:
        reg.upsert_recording(
            {"recording_id": "m1", "name": "To migrate", "date": "2026-01-01"},
            now="2026-01-01",
        )


def test_maj04_migrate_to_central_store_command_moves_data_and_backs_up_source(
    tmp_path, monkeypatch, capsys
):
    from ktalk_cli.cli import main
    from ktalk_cli.registry import Registry

    source = tmp_path / "vault" / ".registry.db"
    source.parent.mkdir(parents=True)
    _seed(source)
    target = tmp_path / "central" / "registry.db"

    rc = main(
        ["migrate-to-central-store", str(source), "--target", str(target), "--json"]
    )
    assert rc == 0, "TODO: MAJ-04 — команда migrate-to-central-store должна существовать"

    out = json.loads(capsys.readouterr().out)
    assert out["target"] == str(target)

    with Registry(target) as reg:
        assert reg.get_recording("m1") is not None

    assert not source.exists()
    backups = list(source.parent.glob(".registry.db*"))
    assert backups


def test_maj04_command_is_registry_free_and_target_gets_nfr15_perms(
    tmp_path,
):
    """Команда сама открывает и путь-источник, и путь-цель вручную (не через
    `Registry(resolve_db_path(...))`) — входит в `_REGISTRY_FREE_COMMANDS`,
    иначе main() открыл бы ПОСТОРОННИЙ Registry по машинному дефолту как побочный
    эффект простого запуска этой команды, что прямо нарушает NFR-12 (миграция —
    только явный шаг, без скрытых побочных эффектов). Отклонение от буквальной
    формулировки рекомендации отчёта (security-review-ktalk-plugin.md, MAJ-04) —
    см. обоснование в dev-заметке. Целевой файл миграции обязан получить
    NFR-15-права (BLOCK-01 остаётся закрытым и на CLI-уровне)."""
    from ktalk_cli.cli import _REGISTRY_FREE_COMMANDS, main

    assert "migrate-to-central-store" in _REGISTRY_FREE_COMMANDS

    source = tmp_path / "vault" / ".registry.db"
    source.parent.mkdir(parents=True)
    _seed(source)
    target = tmp_path / "central" / "registry.db"

    rc = main(["migrate-to-central-store", str(source), "--target", str(target), "--json"])
    assert rc == 0

    mode = stat.S_IMODE(target.stat().st_mode)
    assert mode == 0o600


def test_maj04_target_already_exists_nonzero_exit_source_untouched(tmp_path, capsys):
    from ktalk_cli.cli import main

    source = tmp_path / "vault" / ".registry.db"
    source.parent.mkdir(parents=True)
    _seed(source)
    target = tmp_path / "central" / "registry.db"
    target.parent.mkdir(parents=True)
    target.write_text("already here", encoding="utf-8")

    rc = main(["migrate-to-central-store", str(source), "--target", str(target)])
    assert rc != 0
    assert source.exists()


def test_maj04_default_target_is_machine_default_store_root(tmp_path, monkeypatch, capsys):
    from ktalk_cli.cli import main

    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    fake_home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(fake_home))

    source = tmp_path / "vault" / ".registry.db"
    source.parent.mkdir(parents=True)
    _seed(source)

    rc = main(["migrate-to-central-store", str(source), "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)

    from ktalk_cli.store import resolve_store_root

    assert out["target"] == str(resolve_store_root() / "registry.db")
