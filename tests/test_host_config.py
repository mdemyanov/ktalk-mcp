"""AT-design: FR-20 — discovery конфигурации проекта-хозяина `.ktalk.toml`.

Покрывает контракт с QA-author ktalk-plugin-spec.md: FR-20 AC-1..3 (пути из
конфига применяются / отсутствие файла — тихий дефолт, не ошибка / повреждённый
файл — именованная ошибка, не тихий откат), discovery-алгоритм (§«Discovery»):
`${CLAUDE_PROJECT_DIR}` — строго по корню без обхода; иначе обход вверх от cwd
до `.git`/корня ФС; boundary cases из «Контракт с QA-author» (пустой валидный
файл, неизвестный top-level ключ, `${CLAUDE_PROJECT_DIR}` без файла).

Красные по замыслу: `ktalk_cli.host_config` не существует — `discover_host_config`,
`load_host_config`, `HostConfig`, `HostConfigError` появляются с реализацией Dev
(ktalk-plugin-spec.md, «Реализовать»).
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _write_toml(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


# --- FR-20 AC-1: конфиг присутствует -> пути берутся из него ------------------------


def test_ac_fr20_1_config_present_registry_db_path_is_read_from_file(tmp_path):
    from ktalk_cli.host_config import load_host_config

    config_path = _write_toml(
        tmp_path / ".ktalk.toml",
        '[registry]\ndb_path = "custom/registry.db"\n',
    )
    host_config = load_host_config(config_path)
    assert host_config.registry.get("db_path") == "custom/registry.db"


def test_ac_fr20_1_config_present_routing_and_directories_read_from_file(tmp_path):
    from ktalk_cli.host_config import load_host_config

    config_path = _write_toml(
        tmp_path / ".ktalk.toml",
        (
            "[directories]\n"
            'people = "10_PEOPLE"\n'
            "[routing]\n"
            'standup = "20_MEETINGS/standups/{date}.md"\n'
        ),
    )
    host_config = load_host_config(config_path)
    assert host_config.directories.get("people") == "10_PEOPLE"
    assert host_config.routing.get("standup") == "20_MEETINGS/standups/{date}.md"


# --- FR-20 AC-2: конфига нет вовсе -> тихий машинный дефолт, не ошибка --------------


def test_ac_fr20_2_no_config_file_discovery_returns_none_without_raising(
    tmp_path, monkeypatch
):
    from ktalk_cli.host_config import discover_host_config

    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.chdir(tmp_path)  # нет .ktalk.toml, нет .git — упрётся в корень ФС
    assert discover_host_config() is None


def test_ac_fr20_2_empty_valid_toml_equivalent_to_no_config_per_key(tmp_path):
    """Boundary (Контракт с QA-author): пустой валидный TOML — не ошибка, каждый
    ключ трактуется как отсутствующий, не как «объявлен пустым»."""
    from ktalk_cli.host_config import load_host_config

    config_path = _write_toml(tmp_path / ".ktalk.toml", "")
    host_config = load_host_config(config_path)
    assert host_config.registry.get("db_path") is None
    assert host_config.directories == {}
    assert host_config.routing == {}


# --- FR-20 AC-3: конфиг повреждён/невалиден -> именованная ошибка, не тихий откат --


def test_ac_fr20_3_malformed_toml_syntax_raises_host_config_error_naming_file(
    tmp_path,
):
    from ktalk_cli.host_config import HostConfigError, load_host_config

    config_path = _write_toml(tmp_path / ".ktalk.toml", "this is not [valid toml")
    with pytest.raises(HostConfigError) as exc_info:
        load_host_config(config_path)
    assert str(config_path) in str(exc_info.value)


def test_ac_fr20_3_unknown_top_level_key_raises_host_config_error(tmp_path):
    """Boundary: опечатка `[routng]` вместо `[routing]` — неизвестная секция,
    не тихое игнорирование."""
    from ktalk_cli.host_config import HostConfigError, load_host_config

    config_path = _write_toml(tmp_path / ".ktalk.toml", '[routng]\nstandup = "x"\n')
    with pytest.raises(HostConfigError):
        load_host_config(config_path)


def test_ac_fr20_3_non_bool_integrations_qmd_raises_host_config_error(tmp_path):
    from ktalk_cli.host_config import HostConfigError, load_host_config

    config_path = _write_toml(tmp_path / ".ktalk.toml", '[integrations]\nqmd = "yes"\n')
    with pytest.raises(HostConfigError):
        load_host_config(config_path)


def test_ac_fr20_3_non_string_routing_value_raises_host_config_error(tmp_path):
    config_path = _write_toml(tmp_path / ".ktalk.toml", "[routing]\nstandup = 123\n")
    from ktalk_cli.host_config import HostConfigError, load_host_config

    with pytest.raises(HostConfigError):
        load_host_config(config_path)


def test_ac_fr20_3_malformed_file_does_not_silently_fall_back_to_default(tmp_path):
    """Малформенный файл — процесс останавливается на этом шаге (не продолжает
    на дефолте молча) — discover_host_config не глотает HostConfigError."""
    from ktalk_cli.host_config import HostConfigError, discover_host_config

    _write_toml(tmp_path / ".ktalk.toml", "not valid toml [[[")
    with pytest.raises(HostConfigError):
        discover_host_config(project_dir=tmp_path)


# --- Discovery: ${CLAUDE_PROJECT_DIR} — строго по корню, без обхода вверх ----------


def test_discovery_claude_project_dir_set_reads_config_at_exact_root(
    tmp_path, monkeypatch
):
    from ktalk_cli.host_config import discover_host_config

    _write_toml(tmp_path / ".ktalk.toml", '[registry]\ndb_path = "x.db"\n')
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    host_config = discover_host_config()
    assert host_config is not None
    assert host_config.registry.get("db_path") == "x.db"


def test_discovery_claude_project_dir_set_but_file_absent_returns_none_no_walkup(
    tmp_path, monkeypatch
):
    """${CLAUDE_PROJECT_DIR} задан, но `.ktalk.toml` по этому пути отсутствует —
    FR-20 AC2 (нет ошибки, дефолт), обхода вверх при этом НЕТ, даже если родитель
    несёт валидный конфиг."""
    from ktalk_cli.host_config import discover_host_config

    parent = tmp_path
    child = parent / "project"
    child.mkdir()
    _write_toml(parent / ".ktalk.toml", '[registry]\ndb_path = "parent.db"\n')
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(child))
    assert discover_host_config() is None


# --- Discovery: голый CLI, обход вверх от cwd до .git/корня ФС --------------------


def test_discovery_bare_cli_walks_up_from_cwd_to_nearest_config(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    from ktalk_cli.host_config import discover_host_config

    root = tmp_path / "host"
    nested = root / "a" / "b"
    nested.mkdir(parents=True)
    (root / ".git").mkdir()
    _write_toml(root / ".ktalk.toml", '[registry]\ndb_path = "found-by-walkup.db"\n')
    monkeypatch.chdir(nested)
    host_config = discover_host_config()
    assert host_config is not None
    assert host_config.registry.get("db_path") == "found-by-walkup.db"


def test_discovery_bare_cli_stops_at_git_boundary_before_ancestor_config(
    tmp_path, monkeypatch
):
    """Обход останавливается на первом каталоге с `.git` — конфиг каталога-предка
    ЧУЖОГО репозитория не подхватывается, даже если .git-каталог сам конфига не
    несёт."""
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    from ktalk_cli.host_config import discover_host_config

    outer_ancestor = tmp_path
    _write_toml(outer_ancestor / ".ktalk.toml", '[registry]\ndb_path = "should-not-be-found.db"\n')
    repo_root = outer_ancestor / "repo"
    nested = repo_root / "src" / "pkg"
    nested.mkdir(parents=True)
    (repo_root / ".git").mkdir()  # .git есть, но конфига внутри repo_root нет
    monkeypatch.chdir(nested)
    assert discover_host_config() is None


def test_discovery_bare_cli_stops_at_filesystem_root_if_no_git_and_no_config(
    tmp_path, monkeypatch
):
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    from ktalk_cli.host_config import discover_host_config

    nested = tmp_path / "a" / "b" / "c"
    nested.mkdir(parents=True)
    monkeypatch.chdir(nested)
    # Ни .git, ни .ktalk.toml нигде по цепочке предков tmp_path — не зависает,
    # не поднимается выше реального корня ФС, возвращает None.
    assert discover_host_config() is None


def test_discovery_bare_cli_config_at_git_boundary_itself_is_used(tmp_path, monkeypatch):
    """Конфиг лежит ровно в каталоге с `.git` (граница проекта) — используется,
    обход не идёт дальше вверх ошибочно раньше срока."""
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    from ktalk_cli.host_config import discover_host_config

    repo_root = tmp_path / "repo"
    nested = repo_root / "sub"
    nested.mkdir(parents=True)
    (repo_root / ".git").mkdir()
    _write_toml(repo_root / ".ktalk.toml", '[registry]\ndb_path = "at-boundary.db"\n')
    monkeypatch.chdir(nested)
    host_config = discover_host_config()
    assert host_config is not None
    assert host_config.registry.get("db_path") == "at-boundary.db"


def test_discovery_no_merge_of_two_levels_nearest_wins_entirely(tmp_path, monkeypatch):
    """Discovery п.4: слияния конфигов разных уровней нет — найден ближайший,
    дальше не смотрит, даже если у него меньше ключей, чем у предка."""
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    from ktalk_cli.host_config import discover_host_config

    outer = tmp_path
    _write_toml(
        outer / ".ktalk.toml",
        '[directories]\npeople = "OUTER_PEOPLE"\n[registry]\ndb_path = "outer.db"\n',
    )
    inner = outer / "inner"
    inner.mkdir()
    _write_toml(inner / ".ktalk.toml", '[registry]\ndb_path = "inner.db"\n')
    monkeypatch.chdir(inner)
    host_config = discover_host_config()
    assert host_config.registry.get("db_path") == "inner.db"
    assert host_config.directories.get("people") is None  # не подмешан из outer
