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


ARCHIVE_8COL = """\
# Архив

| recording_id | Название | Дата | Участники | Статус | Дата обработки | Путь транскрипта | Путь протокола |
|---|---|---|---|---|---|---|---|
| R0Wng9L7wAY58El8n5rf | Регулярные встречи | 2026-05-08 | Шадрин Всеволод (ktalk:706), Демьянов Максим (ktalk:668) | done | 2026-05-27 | 95_TRANSCRIPTS/2026/a.md | 30_PROJECTS/x.md |
"""

ARCHIVE_PIPE_IN_NAME = """\
# Архив

| recording_id | Название | Дата | Участники | Статус | Дата обработки | Путь транскрипта | Путь протокола |
|---|---|---|---|---|---|---|---|
| v3kbOfHTJTnFTQOv8RjZ | Документация на примере экосистемы | Gramax | 2026-05-12 | Демьянов Максим (ktalk:668) | done | 2026-05-27 | 95_TRANSCRIPTS/2026/b.md | 30_PROJECTS/y.md |
"""

ARCHIVE_ESCAPED_PIPE_7COL = """\
# Архив

| recording_id | Название | Дата | Статус | Дата обработки | Путь транскрипта | Путь протокола |
|---|---|---|---|---|---|---|
| ZmTErEzMULgA9b6186nX | Обновление 4.21.5. ECS \\| ITSM. Вопросы | 2026-04-23 | done | 2026-05-27 | 95_TRANSCRIPTS/2026/c.md | 20_MEETINGS/z.md |
"""

ARCHIVE_DUP_ID = """\
# Архив

| recording_id | Название | Дата | Участники | Статус | Дата обработки | Путь транскрипта | Путь протокола |
|---|---|---|---|---|---|---|---|
| xHpXhc29P7VlSOjw9PX0 | xHpXhc29P7VlSOjw9PX0 | Катя и Максим | 2026-05-15 | Демьянов Максим (ktalk:668) | done | 2026-05-27 | 95_TRANSCRIPTS/2026/d.md | 30_PROJECTS/w.md |
"""


def test_parse_archive_8col_with_participants():
    from ktalk_mcp.registry import parse_archive_table

    rows = parse_archive_table(ARCHIVE_8COL)
    assert len(rows) == 1
    row = rows[0]
    assert row["recording_id"] == "R0Wng9L7wAY58El8n5rf"
    assert row["name"] == "Регулярные встречи"
    assert row["date"] == "2026-05-08"
    assert row["status"] == "done"
    assert row["processed_at"] == "2026-05-27"
    assert row["transcript_path"] == "95_TRANSCRIPTS/2026/a.md"
    assert row["protocol_path"] == "30_PROJECTS/x.md"
    assert {p["ktalk_id"] for p in row["participants"]} == {"706", "668"}


def test_parse_archive_unescaped_pipe_in_name():
    from ktalk_mcp.registry import parse_archive_table

    row = parse_archive_table(ARCHIVE_PIPE_IN_NAME)[0]
    assert row["recording_id"] == "v3kbOfHTJTnFTQOv8RjZ"
    assert row["name"] == "Документация на примере экосистемы | Gramax"
    assert row["date"] == "2026-05-12"
    assert row["status"] == "done"
    assert row["protocol_path"] == "30_PROJECTS/y.md"


def test_parse_archive_escaped_pipe_7col():
    from ktalk_mcp.registry import parse_archive_table

    row = parse_archive_table(ARCHIVE_ESCAPED_PIPE_7COL)[0]
    assert row["recording_id"] == "ZmTErEzMULgA9b6186nX"
    assert row["name"] == "Обновление 4.21.5. ECS | ITSM. Вопросы"
    assert row["date"] == "2026-04-23"
    assert row["status"] == "done"
    assert row["transcript_path"] == "95_TRANSCRIPTS/2026/c.md"


def test_parse_archive_duplicated_id():
    from ktalk_mcp.registry import parse_archive_table

    row = parse_archive_table(ARCHIVE_DUP_ID)[0]
    assert row["recording_id"] == "xHpXhc29P7VlSOjw9PX0"
    assert row["date"] == "2026-05-15"
    assert row["status"] == "done"
    assert "Катя и Максим" in row["name"]
    assert {p["ktalk_id"] for p in row["participants"]} == {"668"}


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
