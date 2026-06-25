from __future__ import annotations

from pathlib import Path


def test_schema_and_pragmas(tmp_path: Path):
    from ktalk_mcp.registry import Registry

    db = tmp_path / "r.db"
    with Registry(db) as reg:
        mode = reg._conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
        tables = {
            row[0]
            for row in reg._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"recordings", "participants", "meta"} <= tables
        assert reg.get_meta("schema_version") == "1"


def test_meta_roundtrip(tmp_path: Path):
    from ktalk_mcp.registry import Registry

    with Registry(tmp_path / "r.db") as reg:
        assert reg.get_meta("missing") is None
        reg.set_meta("last_synced", "2026-06-25")
        assert reg.get_meta("last_synced") == "2026-06-25"
        reg.set_meta("last_synced", "2026-06-26")  # upsert overwrites
        assert reg.get_meta("last_synced") == "2026-06-26"


def _rec(rid: str, **over):
    base = {
        "recording_id": rid,
        "name": "Standup",
        "date": "2026-06-20",
        "duration_min": 30,
        "raw_json": "{}",
    }
    base.update(over)
    return base


def test_upsert_inserts_with_default_new_status(tmp_path: Path):
    from ktalk_mcp.registry import Registry

    with Registry(tmp_path / "r.db") as reg:
        assert reg.upsert_recording(_rec("a"), now="2026-06-20") == "inserted"
        row = reg.get_recording("a")
        assert row["status"] == "new"
        assert row["name"] == "Standup"
        assert row["created_at"] == "2026-06-20"
        assert reg.get_recording("missing") is None


def test_upsert_is_idempotent_and_preserves_status(tmp_path: Path):
    from ktalk_mcp.registry import Registry

    with Registry(tmp_path / "r.db") as reg:
        reg.upsert_recording(_rec("a"), now="2026-06-20")
        reg.set_status("a", "done")  # simulate processing
        # Re-sync the same id with a changed title — must NOT revert status.
        result = reg.upsert_recording(_rec("a", name="Standup (renamed)"), now="2026-06-21")
        assert result == "updated"
        row = reg.get_recording("a")
        assert row["status"] == "done"
        assert row["name"] == "Standup (renamed)"
        assert row["updated_at"] == "2026-06-21"
        # No duplicate rows.
        count = reg._conn.execute("SELECT COUNT(*) FROM recordings").fetchone()[0]
        assert count == 1


def test_upsert_replaces_participants(tmp_path: Path):
    from ktalk_mcp.registry import Registry

    with Registry(tmp_path / "r.db") as reg:
        reg.upsert_recording(
            _rec("a"),
            participants=[
                {"ktalk_id": "668", "name": "Демьянов Максим"},
                {"ktalk_id": "412", "name": "Муратов Алексей"},
            ],
            now="2026-06-20",
        )
        parts = reg.get_participants("a")
        assert [p["ktalk_id"] for p in parts] == ["412", "668"]
        assert parts[0]["vault_id"] is None


def test_mark_done_sets_paths_and_processed_at(tmp_path: Path):
    from ktalk_mcp.registry import Registry

    with Registry(tmp_path / "r.db") as reg:
        reg.upsert_recording(_rec("a"), now="2026-06-20")
        reg.mark_processing("a", now="2026-06-21")
        assert reg.get_recording("a")["status"] == "processing"
        reg.mark_done(
            "a",
            transcript_path="95_TRANSCRIPTS/2026/x.md",
            protocol_path="10_PEOPLE/x.md",
            meeting_type="1-1",
            now="2026-06-22",
        )
        row = reg.get_recording("a")
        assert row["status"] == "done"
        assert row["transcript_path"] == "95_TRANSCRIPTS/2026/x.md"
        assert row["protocol_path"] == "10_PEOPLE/x.md"
        assert row["meeting_type"] == "1-1"
        assert row["processed_at"] == "2026-06-22"


def test_set_status_rejects_unknown_status(tmp_path: Path):
    import pytest

    from ktalk_mcp.registry import Registry

    with Registry(tmp_path / "r.db") as reg:
        reg.upsert_recording(_rec("a"), now="2026-06-20")
        with pytest.raises(ValueError):
            reg.set_status("a", "bogus")


def test_set_status_missing_recording_raises(tmp_path: Path):
    import pytest

    from ktalk_mcp.registry import Registry

    with Registry(tmp_path / "r.db") as reg:
        with pytest.raises(KeyError):
            reg.set_status("nope", "done")
