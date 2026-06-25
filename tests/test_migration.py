from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_participants_field():
    from ktalk_mcp.registry import parse_participants_field

    parts = parse_participants_field(
        "Муратов Алексей (ktalk:412), Демьянов Максим (ktalk:668)"
    )
    assert parts == [
        {"ktalk_id": "412", "name": "Муратов Алексей"},
        {"ktalk_id": "668", "name": "Демьянов Максим"},
    ]
    assert parse_participants_field("") == []


def test_parse_duration_field():
    from ktalk_mcp.registry import parse_duration_field

    assert parse_duration_field("61 мин") == 61
    assert parse_duration_field("1 ч 5 мин") == 65
    assert parse_duration_field("—") is None
    assert parse_duration_field("") is None


def test_parse_unprocessed_table():
    from ktalk_mcp.registry import parse_unprocessed_table

    text = (FIXTURES / "registry.md").read_text(encoding="utf-8")
    rows = parse_unprocessed_table(text)
    assert len(rows) == 2
    first = rows[0]
    assert first["recording_id"] == "OowNhGRNjLOG3MshMC6i"
    assert first["status"] == "processing"
    assert first["date"] == "2026-06-25"
    assert first["duration_min"] == 61
    assert {p["ktalk_id"] for p in first["participants"]} == {"412", "668"}


def test_parse_archive_table():
    from ktalk_mcp.registry import parse_archive_table

    text = (FIXTURES / "registry-archive-2026-04.md").read_text(encoding="utf-8")
    rows = parse_archive_table(text)
    assert len(rows) == 2
    done, skipped = rows
    assert done["status"] == "done"
    assert done["processed_at"] == "2026-04-03"
    assert done["transcript_path"].endswith("_smp.md")
    assert skipped["status"] == "skipped"
    assert skipped["transcript_path"] is None
    assert skipped["protocol_path"] is None


def test_migrate_imports_rows_and_participants(tmp_path: Path):
    from ktalk_mcp.registry import Registry, migrate_from_vault

    vault = tmp_path / "vault"
    tdir = vault / "95_TRANSCRIPTS"
    tdir.mkdir(parents=True)
    (tdir / "registry.md").write_text(
        (FIXTURES / "registry.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tdir / "registry-archive-2026-04.md").write_text(
        (FIXTURES / "registry-archive-2026-04.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    with Registry(tmp_path / "r.db") as reg:
        summary = migrate_from_vault(reg, vault, now="2026-06-25")
        assert summary["recordings"] == 4
        assert summary["by_status"] == {
            "processing": 1,
            "new": 1,
            "done": 1,
            "skipped": 1,
        }
        assert summary["participants"] == 4  # 2 + 2 from the two unprocessed rows
        done = reg.get_recording("RmfKLz7TrOEb8zQRsxka")
        assert done["status"] == "done"
        assert done["transcript_path"].endswith("_smp.md")
        assert done["processed_at"] == "2026-04-03"


def test_migrate_is_idempotent(tmp_path: Path):
    from ktalk_mcp.registry import Registry, migrate_from_vault

    vault = tmp_path / "vault"
    tdir = vault / "95_TRANSCRIPTS"
    tdir.mkdir(parents=True)
    (tdir / "registry.md").write_text(
        (FIXTURES / "registry.md").read_text(encoding="utf-8"), encoding="utf-8"
    )

    with Registry(tmp_path / "r.db") as reg:
        migrate_from_vault(reg, vault, now="2026-06-25")
        migrate_from_vault(reg, vault, now="2026-06-26")
        count = reg._conn.execute("SELECT COUNT(*) FROM recordings").fetchone()[0]
        assert count == 2  # no duplicates


def test_migrate_dry_run_writes_nothing(tmp_path: Path):
    from ktalk_mcp.registry import Registry, migrate_from_vault

    vault = tmp_path / "vault"
    tdir = vault / "95_TRANSCRIPTS"
    tdir.mkdir(parents=True)
    (tdir / "registry.md").write_text(
        (FIXTURES / "registry.md").read_text(encoding="utf-8"), encoding="utf-8"
    )

    with Registry(tmp_path / "r.db") as reg:
        summary = migrate_from_vault(reg, vault, dry_run=True, now="2026-06-25")
        assert summary["recordings"] == 2
        count = reg._conn.execute("SELECT COUNT(*) FROM recordings").fetchone()[0]
        assert count == 0
