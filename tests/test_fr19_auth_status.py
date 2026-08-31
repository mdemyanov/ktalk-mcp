"""AT-design: FR-19 — `ktalk auth-status` не зависит от доступности реестра.

Покрывает все три AC FR-19: диагностика выполняется даже при недоступном файле
реестра (AC-1), сообщение остаётся диагностикой авторизации, не подменяется ошибкой
БД (AC-2), остальные команды CLI по-прежнему требуют доступный реестр — регрессия
(AC-3). Плюс rooms-calendar-spec §7.1: `create-meeting-preview`/`create-meeting-confirm`
тоже выполняются (до сети/MissingFieldError/TTY) при недоступном реестре — тот же
приём, что уже покрывает `auth-status`.

Красные по замыслу: сегодня `main()` открывает `Registry(db_path)` безусловно для
любой команды (cli.py:229) — `auth-status` падает с «Ошибка: unable to open database
file» вместо диагностики.
"""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock

# Путь, гарантированно недоступный: несуществующий каталог, не просто несуществующий
# файл (SQLite сам создал бы файл в существующем каталоге).
UNAVAILABLE_DB = "/nonexistent/path/does-not-exist/registry.db"


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_ac_fr19_1_auth_status_runs_diagnostics_despite_unavailable_registry(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """AC FR-19/1: `ktalk auth-status` с заведомо недоступным путём реестра всё равно
    выполняет диагностику авторизации и печатает результат, не падает на открытии БД."""
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-1")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    httpx_mock.add_response(json={"recordings": []})  # проба list_recordings(top=1)

    from ktalk_cli.cli import main

    rc = main(["--db", UNAVAILABLE_DB, "auth-status", "--json"])

    captured = capsys.readouterr()
    assert "unable to open database file" not in captured.err
    assert "unable to open database file" not in captured.out
    assert rc == 0
    assert "alive" in captured.out


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_ac_fr19_2_auth_diagnostics_error_not_replaced_by_database_message(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """AC FR-19/2: ошибка в самой диагностике авторизации (сеть/401/403) остаётся
    сообщением о диагностике, не подменяется сообщением о базе данных."""
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-1")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    httpx_mock.add_response(status_code=401)

    from ktalk_cli.cli import main

    main(["--db", UNAVAILABLE_DB, "auth-status"])

    captured = capsys.readouterr()
    assert "database" not in (captured.out + captured.err).lower()
    assert "unable to open" not in (captured.out + captured.err).lower()


@pytest.mark.parametrize(
    "argv",
    [
        ["list"],
        ["dashboard"],
        ["show", "REC-1"],
        ["mark-processing", "REC-1"],
        ["export"],
        ["migrate", "/some/vault/path"],
        ["set-vault-id", "REC-1", "u1", "v1"],
        ["sync", "--days", "7"],
    ],
)
def test_ac_fr19_3_other_commands_still_require_available_registry(
    argv, monkeypatch, capsys
):
    """AC FR-19/3 (регрессия): остальные команды CLI по-прежнему требуют доступный
    файл реестра — исправление FR-19 не меняет их поведение."""
    monkeypatch.delenv("KTALK_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)

    from ktalk_cli.cli import main

    rc = main(["--db", UNAVAILABLE_DB, *argv])

    assert rc != 0
    captured = capsys.readouterr()
    assert "Ошибка" in captured.err


def test_fr19_create_meeting_preview_works_despite_unavailable_registry(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """rooms-calendar-spec §7.1: `create-meeting-preview` — тоже в
    `_REGISTRY_FREE_COMMANDS`, никогда не читает/не пишет реестр. Проверяем до
    MissingFieldError (не все поля переданы) — реестр всё равно не должен помешать."""
    from ktalk_cli.cli import main

    rc = main(["--db", UNAVAILABLE_DB, "create-meeting-preview", "--subject", "X"])

    captured = capsys.readouterr()
    assert "unable to open database file" not in (captured.out + captured.err)
    assert rc != 0  # MissingFieldError на других полях — но не из-за реестра
    assert httpx_mock.get_requests() == []
