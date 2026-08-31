"""AT-design: `ktalk config show` — CLI-команда, печатающая резолвленный `HostConfig`
машинно (`--json`) и человекочитаемо (ktalk-plugin-spec.md, «Как ключи доходят до
промтов навыка/агента»).

Контракт: `_REGISTRY_FREE_COMMANDS` (не открывает SQLite); JSON: отсутствующий ключ
= отсутствует в JSON, НЕ `null` (различимо от «объявлено пустой строкой» —
интеграционная точка ktalk-plugin-spec.md); повреждённый конфиг -> ненулевой код
возврата, stderr называет файл и причину (промт обязан прочитать stderr и
остановить шаг, не игнорировать код возврата).

Красные по замыслу: подкоманда `config show` не зарегистрирована в `build_parser`
(`cli.py`) — появляется вместе с `host_config.py` (Dev, ktalk-plugin-spec.md).
"""

from __future__ import annotations

import json

import pytest


def test_config_show_json_reflects_ktalk_toml(tmp_path, monkeypatch, capsys):
    from ktalk_cli.cli import main

    (tmp_path / ".ktalk.toml").write_text(
        '[registry]\ndb_path = "custom.db"\n[directories]\npeople = "10_PEOPLE"\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    rc = main(["config", "show", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["registry"]["db_path"] == "custom.db"
    assert out["directories"]["people"] == "10_PEOPLE"


def test_config_show_no_config_file_prints_defaults_without_error(
    tmp_path, monkeypatch, capsys
):
    from ktalk_cli.cli import main

    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)  # ни .ktalk.toml, ни .git

    rc = main(["config", "show", "--json"])
    assert rc == 0
    capsys.readouterr()  # не поднимает исключение — уже достаточно для AC


def test_config_show_undeclared_routing_key_absent_from_json_not_null(
    tmp_path, monkeypatch, capsys
):
    from ktalk_cli.cli import main

    (tmp_path / ".ktalk.toml").write_text(
        '[routing]\nstandup = "20_MEETINGS/standups/{date}.md"\n', encoding="utf-8"
    )
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    rc = main(["config", "show", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "committee" not in out.get("routing", {}), (
        "TODO: отсутствующий ключ должен отсутствовать в JSON, не быть null"
    )


def test_config_show_malformed_config_nonzero_exit_and_stderr_names_file(
    tmp_path, monkeypatch, capsys
):
    from ktalk_cli.cli import main

    config_path = tmp_path / ".ktalk.toml"
    config_path.write_text("not valid toml [[[", encoding="utf-8")
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    rc = main(["config", "show", "--json"])
    assert rc != 0
    captured = capsys.readouterr()
    assert str(config_path) in captured.err


def test_config_show_is_registry_free_command_does_not_require_db(tmp_path, monkeypatch, capsys):
    """`config show` входит в `_REGISTRY_FREE_COMMANDS` — работает даже когда
    `--db` указывает на недоступный/несуществующий путь, реестр не открывается."""
    from ktalk_cli.cli import main

    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)
    unreachable_db = "/nonexistent/deeply/nested/path/registry.db"

    rc = main(["--db", unreachable_db, "config", "show", "--json"])
    assert rc == 0
    capsys.readouterr()


def test_config_show_human_readable_without_json_flag(tmp_path, monkeypatch, capsys):
    from ktalk_cli.cli import main

    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)

    rc = main(["config", "show"])
    assert rc == 0
    out = capsys.readouterr().out
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)  # человекочитаемый вывод — не JSON по умолчанию
