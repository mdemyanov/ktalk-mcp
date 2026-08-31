"""Code review (эпик epic-capability-pairing, DEV-003), находка Р5: `export` без явного
`--db`/`KTALK_REGISTRY_DB`/`.ktalk.toml` кладёт `registry.md` внутрь централизованного
хранилища (`cli.py::_cmd_export` использовал `Path(resolve_db_path(args.db)).parent`, а
когда путь резолвится к машинному дефолту, `.parent` — корень хранилища).

Нарушает `centralized-machine-storage` capability, сценарий «The markdown registry mirror
stays in the host project, not the store» (NFR-16 AC, ADR-013): зеркало обязано лечь в
проекте-хозяине, не в хранилище, независимо от того, откуда резолвился путь БД.

Ни `test_cli_host_config_wiring.py::test_maj03_...`, ни `test_fr21_no_vault_layout.py` этот
путь не покрывают — оба гоняют `export` только с явным `--db`/`.ktalk.toml`, где `.parent`
и так указывает в проект-хозяина совпадением конструкции, а не по проверенному инварианту.
"""

from __future__ import annotations

import json
import os


def test_r5_export_without_any_explicit_path_does_not_write_mirror_inside_central_store(
    tmp_path, monkeypatch, capsys
):
    """Чистое окружение (нет `--db`, нет `KTALK_REGISTRY_DB`, нет `.ktalk.toml`) — БД
    резолвится к машинному дефолту централизованного хранилища (ADR-013 §1). Зеркало
    `registry.md` не должно оказаться внутри этого хранилища (NFR-16 AC)."""
    project = tmp_path / "project"
    project.mkdir()
    home = tmp_path / "home"
    home.mkdir()

    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)
    monkeypatch.delenv("CLAUDE_PROJECT_DIR", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(project)

    from ktalk_mcp.cli import main
    from ktalk_mcp.store import resolve_store_root

    rc = main(["export", "--json"])
    assert rc == 0
    written = json.loads(capsys.readouterr().out)["written"]

    # test_store.py::test_maj02_... (dev-заметка `store.py`): `resolve_store_root()`
    # мутирует process umask на 0o077 и НЕ восстанавливает его сама — вызов здесь
    # только для того, чтобы узнать путь корня, и обязан вернуть umask как было,
    # иначе тест портит umask для любого теста, запущенного после этого в том же
    # процессе pytest (наблюдалось: test_maj02_file_written_after_registry_closes_
    # uses_ambient_umask_not_0o077 ловил унаследованный 0o077).
    old_umask = os.umask(0o022)
    os.umask(old_umask)
    store_root = resolve_store_root()
    os.umask(old_umask)

    assert not str(written).startswith(str(store_root) + "/"), (
        f"export положил зеркало внутрь централизованного хранилища: {written} "
        f"(корень хранилища: {store_root}) — нарушение ADR-013/NFR-16"
    )
