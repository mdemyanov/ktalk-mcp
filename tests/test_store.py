"""AT-design: FR-22 (машинный дефолт хранилища), NFR-14 (не под облачной синхронизацией
молча), NFR-15 (права доступа 0700/0600).

Покрывает контракт с QA-author ADR-013-central-transcript-store-spec.md:
`resolve_store_root` (корень вне cwd, единый файл для двух «проектов», права при
создании), `detect_sync_dir` (маркеры iCloud/Dropbox/OneDrive/Google Drive, граница
сегментации — `MyDropboxBackup/` не должен ложно сработать на `Dropbox`), поведение
при срабатывании — предупреждение, не блокировка.

Ограничение окружения (CLAUDE.md, задача QA-001): тесты не трогают реальный $HOME —
`$HOME`/`$XDG_DATA_HOME` подменяются `monkeypatch` на `tmp_path`.

Красные по замыслу: `ktalk_mcp.store` не существует — `resolve_store_root`,
`detect_sync_dir` появляются с реализацией Dev (ADR-013-spec, «Реализовать»).
"""

from __future__ import annotations

import stat

# --- FR-22 AC-1: машинный дефолт — вне текущего проекта, не подкаталог cwd --------


def test_ac_fr22_1_store_root_is_not_inside_cwd(tmp_path, monkeypatch):
    from ktalk_mcp.store import resolve_store_root

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(fake_home))
    project_cwd = tmp_path / "some-project"
    project_cwd.mkdir()
    monkeypatch.chdir(project_cwd)

    root = resolve_store_root()
    assert not root.is_relative_to(project_cwd)
    assert root.is_relative_to(fake_home)


def test_store_root_respects_xdg_data_home_when_set(tmp_path, monkeypatch):
    from ktalk_mcp.store import resolve_store_root

    xdg = tmp_path / "xdg-data"
    monkeypatch.setenv("XDG_DATA_HOME", str(xdg))
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = resolve_store_root()
    assert root.is_relative_to(xdg)


def test_store_root_xdg_data_home_empty_string_falls_back_like_unset(tmp_path, monkeypatch):
    """Boundary (ADR-013-spec edge case): `$XDG_DATA_HOME` пустой строкой — не то же
    самое, что путь `""`, поведение как «не задано» (`$HOME/.local/share`)."""
    from ktalk_mcp.store import resolve_store_root

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("XDG_DATA_HOME", "")
    monkeypatch.setenv("HOME", str(fake_home))
    root = resolve_store_root()
    assert root.is_relative_to(fake_home / ".local" / "share")


# --- FR-22 AC-2: два "проекта" без своего пути адресуют один и тот же файл ---------


def test_ac_fr22_2_two_calls_from_different_cwd_resolve_to_same_root(tmp_path, monkeypatch):
    from ktalk_mcp.store import resolve_store_root

    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))

    project_a = tmp_path / "project-a"
    project_b = tmp_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()

    monkeypatch.chdir(project_a)
    root_a = resolve_store_root()
    monkeypatch.chdir(project_b)
    root_b = resolve_store_root()

    assert root_a == root_b


# --- FR-22 AC-3 / NFR-15: права каталога/файла при первом создании ----------------


def test_ac_fr22_3_store_root_created_with_owner_only_permissions(tmp_path, monkeypatch):
    from ktalk_mcp.store import resolve_store_root

    fake_home = tmp_path / "home"
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(fake_home))

    root = resolve_store_root()
    assert root.exists()
    mode = stat.S_IMODE(root.stat().st_mode)
    assert mode == 0o700, f"TODO: NFR-15 — каталог хранилища должен быть 0700, получено {oct(mode)}"


def test_nfr15_registry_db_file_created_with_0600(tmp_path, monkeypatch):
    """NFR-15: файл БД реестра при первом создании — 0600, не 0644 (umask-контролируемо,
    без post-hoc chmod)."""
    from ktalk_mcp.store import resolve_store_root

    from ktalk_mcp.registry import Registry

    fake_home = tmp_path / "home"
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(fake_home))

    root = resolve_store_root()
    db_path = root / "registry.db"
    with Registry(db_path):
        pass
    mode = stat.S_IMODE(db_path.stat().st_mode)
    assert mode == 0o600, f"TODO: NFR-15 — файл реестра должен быть 0600, получено {oct(mode)}"


# --- NFR-14: детекция каталогов облачной синхронизации ----------------------------


def test_nfr14_detect_sync_dir_true_for_icloud_marker(tmp_path):
    from ktalk_mcp.store import detect_sync_dir

    path = tmp_path / "Library" / "Mobile Documents" / "com~apple~CloudDocs" / "ktalk"
    is_sync, reason = detect_sync_dir(path)
    assert is_sync is True
    assert "Mobile Documents" in reason


def test_nfr14_detect_sync_dir_true_for_dropbox_marker(tmp_path):
    from ktalk_mcp.store import detect_sync_dir

    path = tmp_path / "Users" / "me" / "Dropbox" / "ktalk"
    is_sync, _reason = detect_sync_dir(path)
    assert is_sync is True


def test_nfr14_detect_sync_dir_false_for_ordinary_path(tmp_path):
    from ktalk_mcp.store import detect_sync_dir

    path = tmp_path / ".local" / "share" / "ktalk"
    is_sync, _reason = detect_sync_dir(path)
    assert is_sync is False


def test_nfr14_detect_sync_dir_no_false_positive_on_marker_as_substring_not_segment(
    tmp_path,
):
    """Boundary (ADR-013-spec edge case): `MyDropboxBackup/` не должен ложно
    сработать на маркер `Dropbox` — сегментация по границе каталога, не substring."""
    from ktalk_mcp.store import detect_sync_dir

    path = tmp_path / "Users" / "me" / "MyDropboxBackup" / "ktalk"
    is_sync, _reason = detect_sync_dir(path)
    assert is_sync is False


def test_ac_fr22_1_nfr14_machine_default_is_never_flagged_as_sync_dir(tmp_path, monkeypatch):
    """NFR-14 AC-1: резолвленный машинный дефолт проверяется относительно каталогов
    синхронизации — по построению вне них."""
    from ktalk_mcp.store import detect_sync_dir, resolve_store_root

    fake_home = tmp_path / "home"
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setenv("HOME", str(fake_home))
    root = resolve_store_root()
    is_sync, _reason = detect_sync_dir(root)
    assert is_sync is False


def test_nfr14_2_explicit_path_inside_sync_dir_produces_warning_not_block(
    tmp_path, capsys, monkeypatch
):
    """NFR-14 AC-2: пользователь явно указывает путь внутри распознаваемого каталога
    синхронизации — предупреждение в stderr, работа продолжается (не блокировка).
    Функция, применяющая путь и печатающая предупреждение — на усмотрение Dev
    (ADR-013-spec §«Поток данных» п.4); здесь используется `warn_if_sync_dir` как
    рабочее имя, точка входа уточняется Dev при реализации."""
    from ktalk_mcp.store import warn_if_sync_dir

    user_path = tmp_path / "Dropbox" / "ktalk" / "registry.db"
    warn_if_sync_dir(user_path)
    captured = capsys.readouterr()
    assert "Dropbox" in captured.err or "Dropbox" in captured.out
