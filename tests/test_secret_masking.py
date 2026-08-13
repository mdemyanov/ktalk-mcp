"""AT-design: секрет не логируется и не попадает в вывод (NFR-5).

Покрывает NFR-5 единственное AC через представительный набор ошибочных сценариев, как
требует его формулировка ("проверка отсутствия строки ключа в захваченном выводе по
представительному набору сценариев"): исключение клиента, generic-исключение сети,
CLI stderr (текстовый режим), CLI --json.

Красные по замыслу: сегодня `KTALK_PERSONAL_API_KEY` не существует вовсе (FR-1 не
реализован), поэтому сценарии ниже падают на отсутствии функциональности раньше, чем
успели бы проверить факт маскирования — это ожидаемо для стадии red.
"""

from __future__ import annotations

import httpx
import pytest
from pytest_httpx import HTTPXMock

SECRET = "pk-supersecret-abcdef123456"


@pytest.fixture
def base_url():
    return "https://test.ktalk.ru"


async def test_secret_not_in_auth_error_message(httpx_mock: HTTPXMock, base_url):
    """Значение ключа не появляется в тексте KTalkAuthError."""
    from ktalk_mcp.client import KTalkAuthError, KTalkClient

    httpx_mock.add_response(status_code=401)

    async with KTalkClient(base_url=base_url, personal_api_key=SECRET) as client:
        with pytest.raises(KTalkAuthError) as exc_info:
            await client.list_recordings()

    assert SECRET not in str(exc_info.value)


async def test_secret_not_in_generic_exception_str_or_repr(httpx_mock: HTTPXMock, base_url):
    """ADR-003: KTalkError строит текст из статичных строк, никогда из
    str(request.url)/request.headers — секрет не должен всплыть даже в repr исключения
    при непредвиденной сетевой ошибке."""
    from ktalk_mcp.client import KTalkClient

    httpx_mock.add_exception(httpx.ConnectError("connection refused"))

    async with KTalkClient(base_url=base_url, personal_api_key=SECRET) as client:
        with pytest.raises(Exception) as exc_info:
            await client.list_recordings()

    assert SECRET not in str(exc_info.value)
    assert SECRET not in repr(exc_info.value)


def test_secret_not_in_cli_text_output(
    tmp_path, monkeypatch, httpx_mock: HTTPXMock, capsys
):
    """Значение ключа не попадает в stdout/stderr CLI при ошибке (текстовый режим)."""
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_PERSONAL_API_KEY", SECRET)
    monkeypatch.delenv("KTALK_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)
    httpx_mock.add_response(status_code=401)

    from ktalk_mcp.cli import main

    db = tmp_path / "r.db"
    main(["--db", str(db), "sync", "--days", "7"])

    captured = capsys.readouterr()
    assert SECRET not in captured.out
    assert SECRET not in captured.err


def test_secret_not_in_cli_json_output(
    tmp_path, monkeypatch, httpx_mock: HTTPXMock, capsys
):
    """Значение ключа не попадает в stdout/stderr CLI при ошибке, включая --json-вывод."""
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_PERSONAL_API_KEY", SECRET)
    monkeypatch.delenv("KTALK_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)
    httpx_mock.add_response(status_code=401)

    from ktalk_mcp.cli import main

    db = tmp_path / "r.db"
    main(["--db", str(db), "sync", "--days", "7", "--json"])

    captured = capsys.readouterr()
    assert SECRET not in captured.out
    assert SECRET not in captured.err


def test_secret_not_in_auth_status_cli_output(
    tmp_path, monkeypatch, httpx_mock: HTTPXMock, capsys
):
    """`ktalk auth-status --json` (NEW команда) не утекает ключом даже на сетевой ошибке."""
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_PERSONAL_API_KEY", SECRET)
    monkeypatch.delenv("KTALK_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)
    httpx_mock.add_response(status_code=401)

    from ktalk_mcp.cli import main

    db = tmp_path / "r.db"
    main(["--db", str(db), "auth-status", "--json"])

    captured = capsys.readouterr()
    assert SECRET not in captured.out
    assert SECRET not in captured.err


def test_secret_not_in_settings_repr_or_str(monkeypatch):
    """Security review SEC-001: pydantic по умолчанию печатает значения ВСЕХ полей в
    `repr(settings)`/`str(settings)` — в отличие от `AuthContext`, который уже маскирует
    себя явно, `Settings` этого не делала. Секретные поля объявлены `Field(repr=False)`."""
    monkeypatch.setenv("KTALK_PERSONAL_API_KEY", SECRET)
    monkeypatch.delenv("KTALK_SESSION_TOKEN", raising=False)

    from ktalk_mcp.config import Settings

    settings = Settings()
    assert SECRET not in repr(settings)
    assert SECRET not in str(settings)


def test_secret_redacted_from_unexpected_exception_via_cli_main(
    tmp_path, monkeypatch, capsys
):
    """Барьер-редактор (ADR-003 «SecretRedactor», ранее спроектирован, но не был вызван
    ниоткуда): даже если секрет случайно попадёт в текст исключения, НЕ являющегося
    `KTalkError`/`KTalkConfigError` (т.е. минующего специальный обработчик `cmd_sync`/
    `cmd_auth_status` и всплывающего через общий `except Exception` в `cli.py::main`),
    значение ключа не должно долететь до stderr в открытом виде."""
    monkeypatch.setenv("KTALK_PERSONAL_API_KEY", SECRET)
    monkeypatch.delenv("KTALK_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)

    from ktalk_mcp import cli

    def _boom(reg, args):
        raise RuntimeError(f"unexpected failure, credential was {SECRET}")

    monkeypatch.setitem(cli._HANDLERS, "list", _boom)

    db = tmp_path / "r.db"
    rc = cli.main(["--db", str(db), "list"])

    captured = capsys.readouterr()
    assert rc == 1
    assert SECRET not in captured.out
    assert SECRET not in captured.err
    assert "REDACTED" in captured.err
