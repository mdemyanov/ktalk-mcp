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


def test_list_recordings_filter_and_order(tmp_path: Path):
    from ktalk_mcp.registry import Registry

    with Registry(tmp_path / "r.db") as reg:
        reg.upsert_recording(_rec("a", date="2026-06-20"), now="2026-06-20")
        reg.upsert_recording(_rec("b", date="2026-06-22"), now="2026-06-22")
        reg.set_status("b", "done")
        all_recs = reg.list_recordings()
        assert [r["recording_id"] for r in all_recs] == ["b", "a"]  # date DESC
        new_only = reg.list_recordings(status="new")
        assert [r["recording_id"] for r in new_only] == ["a"]


def test_set_vault_id(tmp_path: Path):
    import pytest

    from ktalk_mcp.registry import Registry

    with Registry(tmp_path / "r.db") as reg:
        reg.upsert_recording(
            _rec("a"),
            participants=[{"ktalk_id": "668", "name": "Демьянов Максим"}],
            now="2026-06-20",
        )
        reg.set_vault_id("a", "668", "mdemyanov")
        assert reg.get_participants("a")[0]["vault_id"] == "mdemyanov"
        with pytest.raises(KeyError):
            reg.set_vault_id("a", "999", "x")


def test_expire_new_boundary_exactly_7_days(tmp_path: Path):
    from ktalk_mcp.registry import Registry

    with Registry(tmp_path / "r.db") as reg:
        # now = 2026-06-25, days = 7 -> cutoff 2026-06-18
        reg.upsert_recording(_rec("keep", date="2026-06-18"), now="2026-06-18")  # age 7
        reg.upsert_recording(_rec("gone", date="2026-06-17"), now="2026-06-17")  # age 8
        reg.upsert_recording(_rec("fresh", date="2026-06-25"), now="2026-06-25")
        reg.upsert_recording(_rec("done", date="2026-06-10"), now="2026-06-10")
        reg.set_status("done", "done")  # not 'new' -> never expired

        expired = reg.expire_new(now="2026-06-25", days=7)
        assert expired == ["gone"]
        assert reg.get_recording("keep")["status"] == "new"
        assert reg.get_recording("gone")["status"] == "skipped"
        assert reg.get_recording("gone")["processed_at"] == "2026-06-25"
        assert reg.get_recording("done")["status"] == "done"


def test_concurrent_writers_both_persist(tmp_path: Path):
    import threading

    from ktalk_mcp.registry import Registry

    db = tmp_path / "r.db"
    # Seed two recordings via one connection, then close it.
    with Registry(db) as seed:
        seed.upsert_recording(_rec("a"), now="2026-06-20")
        seed.upsert_recording(_rec("b"), now="2026-06-20")

    errors: list[Exception] = []

    def writer(rid: str):
        try:
            reg = Registry(db)
            reg.mark_done(rid, transcript_path=f"t-{rid}.md", now="2026-06-22")
            reg.close()
        except Exception as exc:  # noqa: BLE001 - test captures any failure
            errors.append(exc)

    t1 = threading.Thread(target=writer, args=("a",))
    t2 = threading.Thread(target=writer, args=("b",))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert errors == []
    with Registry(db) as reg:
        assert reg.get_recording("a")["status"] == "done"
        assert reg.get_recording("b")["status"] == "done"
        assert reg.get_recording("a")["transcript_path"] == "t-a.md"
        assert reg.get_recording("b")["transcript_path"] == "t-b.md"


def test_recording_fields_from_api():
    from ktalk_mcp.registry import recording_fields_from_api

    rec = {
        "id": "OowNhGRNjLOG3MshMC6i",
        "title": "Алексей 🤝 Максим",
        "createdDate": "2026-06-25T09:30:00Z",
        "duration": 3660,
    }
    fields = recording_fields_from_api(rec)
    assert fields["recording_id"] == "OowNhGRNjLOG3MshMC6i"
    assert fields["name"] == "Алексей 🤝 Максим"
    assert fields["date"] == "2026-06-25"
    assert fields["duration_min"] == 61
    assert '"id": "OowNhGRNjLOG3MshMC6i"' in fields["raw_json"]


def test_participants_from_api():
    from ktalk_mcp.registry import participants_from_api

    rec = {
        "participants": [
            {"userInfo": {"key": "668", "surname": "Демьянов", "firstname": "Максим"}},
            {"userInfo": {"key": "412", "surname": "Муратов", "firstname": "Алексей"}},
            {"userInfo": {"key": "668", "surname": "Демьянов", "firstname": "Максим"}},
            {"isAnonymous": True, "anonymousName": "Гость"},  # no ktalk_id -> skipped
        ]
    }
    parts = participants_from_api(rec)
    ids = sorted(p["ktalk_id"] for p in parts)
    assert ids == ["412", "668"]
    by_id = {p["ktalk_id"]: p["name"] for p in parts}
    assert by_id["668"] == "Демьянов Максим"


def test_render_markdown_mirror(tmp_path: Path):
    from ktalk_mcp.registry import Registry, render_markdown_mirror

    with Registry(tmp_path / "r.db") as reg:
        reg.upsert_recording(
            _rec("new1", name="Standup", date="2026-06-24", duration_min=55),
            participants=[{"ktalk_id": "668", "name": "Демьянов Максим"}],
            now="2026-06-24",
        )
        reg.upsert_recording(_rec("done1", name="1-1", date="2026-06-20"), now="2026-06-20")
        reg.mark_done(
            "done1",
            transcript_path="95_TRANSCRIPTS/2026/x.md",
            protocol_path="10_PEOPLE/x.md",
            now="2026-06-21",
        )
        reg.upsert_recording(_rec("old", name="Ancient", date="2026-01-05"), now="2026-01-05")
        reg.mark_skipped("old", now="2026-01-12")

        text = render_markdown_mirror(reg, now="2026-06-25")
        assert text.startswith("<!-- GENERATED by ktalk export")
        assert "## Необработанные записи" in text
        assert "new1" in text
        assert "Демьянов Максим (ktalk:668)" in text
        assert "done1" in text  # done within current/prev month window
        assert "old" not in text  # January skipped, outside 2-month window

        full = render_markdown_mirror(reg, full=True, now="2026-06-25")
        assert "old" in full  # full dump includes everything
