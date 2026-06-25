from __future__ import annotations

import json
from pathlib import Path


def _seed(db: Path):
    from ktalk_mcp.registry import Registry

    with Registry(db) as reg:
        reg.upsert_recording(
            {"recording_id": "a", "name": "Standup", "date": "2026-06-24",
             "duration_min": 30},
            participants=[{"ktalk_id": "668", "name": "Демьянов Максим"}],
            now="2026-06-24",
        )
        reg.upsert_recording(
            {"recording_id": "b", "name": "1-1", "date": "2026-06-20"},
            now="2026-06-20",
        )
        reg.set_status("b", "done")


def test_list_json(tmp_path, capsys):
    from ktalk_mcp.cli import main

    db = tmp_path / "r.db"
    _seed(db)
    rc = main(["--db", str(db), "list", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    ids = [r["recording_id"] for r in out["recordings"]]
    assert ids == ["a", "b"]  # date DESC


def test_list_status_filter_json(tmp_path, capsys):
    from ktalk_mcp.cli import main

    db = tmp_path / "r.db"
    _seed(db)
    rc = main(["--db", str(db), "list", "--status", "new", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert [r["recording_id"] for r in out["recordings"]] == ["a"]


def test_show_json_includes_participants(tmp_path, capsys):
    from ktalk_mcp.cli import main

    db = tmp_path / "r.db"
    _seed(db)
    rc = main(["--db", str(db), "show", "a", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["recording_id"] == "a"
    assert out["participants"][0]["ktalk_id"] == "668"


def test_show_missing_returns_error(tmp_path, capsys):
    from ktalk_mcp.cli import main

    db = tmp_path / "r.db"
    _seed(db)
    rc = main(["--db", str(db), "show", "nope", "--json"])
    assert rc == 1
    assert capsys.readouterr().err  # non-empty stderr


def test_list_text_output(tmp_path, capsys):
    from ktalk_mcp.cli import main

    db = tmp_path / "r.db"
    _seed(db)
    rc = main(["--db", str(db), "list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Standup" in out
