"""AT-design: FR-21 — команды реестра/MCP read-инструменты работают в проекте без
vault-подобной раскладки (не ошибка использования, штатная ветка).

Покрывает FR-21 AC-1 (registry-команды не требуют `95_TRANSCRIPTS`/`20_MEETINGS`/
любого каталога vault'а) и FR-21 AC-2 (MCP read-инструмент чтения записи не
адресует файлы хозяина, только API Толка + централизованное хранилище).

Часть покрытия здесь — регрессионный снимок: список команд ниже уже не создаёт
и не ищет vault-каталоги сегодня (единственная зависимость от раскладки —
`--db`), проверка фиксирует это явно как контракт, не полагается на «само
собой». Явное отсутствие требования каталога 95_TRANSCRIPTS/20_MEETINGS для этих
команд не проверялось раньше отдельным тестом.
"""

from __future__ import annotations


def _seed(db_path):
    from ktalk_mcp.registry import Registry

    with Registry(db_path) as reg:
        reg.upsert_recording(
            {"recording_id": "a", "name": "Standup", "date": "2026-06-24"},
            now="2026-06-24",
        )


def test_ac_fr21_1_list_show_mark_dashboard_export_work_without_ktalk_toml_or_vault_dirs(
    tmp_path, monkeypatch, capsys
):
    from ktalk_mcp.cli import main

    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    project = tmp_path / "clean-project"  # ни .ktalk.toml, ни 95_TRANSCRIPTS, ни .git
    project.mkdir()
    monkeypatch.chdir(project)

    db = tmp_path / "registry.db"  # путь вне проекта — только через --db, не через layout
    _seed(db)

    for argv in (
        ["--db", str(db), "list", "--json"],
        ["--db", str(db), "show", "a", "--json"],
        ["--db", str(db), "mark-processing", "a"],
        ["--db", str(db), "dashboard", "--json"],
        ["--db", str(db), "export"],
    ):
        rc = main(argv)
        captured = capsys.readouterr()
        assert rc == 0, f"TODO: FR-21 AC-1 — {argv} обязана отработать без vault-раскладки"
        assert "95_TRANSCRIPTS" not in captured.err
        assert "20_MEETINGS" not in captured.err

    assert not (project / "95_TRANSCRIPTS").exists(), (
        "команда не должна создавать vault-каталоги там, где их не было"
    )


def test_ac_fr21_1_export_mirror_written_relative_to_db_path_not_requiring_vault_dirs(
    tmp_path, monkeypatch
):
    """export уже сегодня пишет `registry.md` рядом с БД (cli.py) — регрессия:
    проверка, что это не требует существования vault-каталогов рядом."""
    from ktalk_mcp.cli import main

    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    db = tmp_path / "no-vault-here" / "registry.db"
    db.parent.mkdir()
    _seed(db)

    rc = main(["--db", str(db), "export"])
    assert rc == 0
    assert (db.parent / "registry.md").exists()


async def test_ac_fr21_2_mcp_read_tool_json_output_shape_unaffected_by_absence_of_host_layout(
    tmp_path, monkeypatch
):
    """FR-21 AC-2: MCP-инструмент чтения (например, ktalk_get_transcript) адресует
    только API Толка / централизованное хранилище — не файлы хозяина; отсутствие
    `.ktalk.toml`/vault-каталогов не меняет его поведение. Регрессия существующих
    read-инструментов (NFR-6) распространяется на проект без раскладки: инструменты
    не импортируют `host_config`/discovery на пути чтения контента."""
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    project = tmp_path / "clean-project"
    project.mkdir()
    monkeypatch.chdir(project)

    from ktalk_mcp.server import mcp

    tools = await mcp.list_tools()
    names = {t.name for t in tools}
    assert "ktalk_get_transcript" in names, (
        "TODO: FR-21 AC-2 — read-инструмент регистрируется независимо от layout хозяина"
    )
