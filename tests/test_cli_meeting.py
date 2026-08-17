"""AT-design: FR-13 CLI — `create-meeting-preview`/`create-meeting-confirm`
(`ktalk_mcp.cli_meeting`, расширение `ktalk_mcp.cli`).

Покрывает: булевы флаги НЕ `store_true` (отсутствие `--enable-sip` != `False`),
явная пустая коллекция участников (`--no-required-users` != отсутствие флага),
`_tri_bool` (`TRUE`/`False` принимаются, `yes`/`1` отклоняются), `isatty()`-барьер
(под pytest stdin/stdout уже не терминал — негативный случай получаем бесплатно;
позитивный — реальный `pty`), отсутствие авто-retry на сетевую ошибку на CLI-уровне,
работа обеих подкоманд при недоступном пути реестра (FR-19-совместимость, детальный
тест FR-19 — `test_fr19_auth_status.py`).

Красные по замыслу: подкоманды `create-meeting-preview`/`create-meeting-confirm` и
`ktalk_mcp.cli_meeting` не существуют.

Допущение для Dev (см. at-design-rooms-calendar.md «Допущения»): позитивный
TTY-сценарий кодирует рабочую гипотезу — подтверждающий ввод "да" (регистронезависимо).
Если Dev выберет другой токен подтверждения — правка одной строки в тесте, не самого
сценария.
"""

from __future__ import annotations

import os
import pty
import sys

import pytest
from pytest_httpx import HTTPXMock

BAD_DB = "/nonexistent/path/does-not-exist/registry.db"

_PREVIEW_ARGV_FULL = [
    "create-meeting-preview",
    "--subject",
    "Синтетическая встреча",
    "--start",
    "2026-08-15T10:00:00+03:00",
    "--end",
    "2026-08-15T11:00:00+03:00",
    "--timezone",
    "Europe/Moscow",
    "--room-name",
    "test-room-alpha",
    "--required-user-key",
    "synthetic-user-1",
    "--required-user-key",
    "synthetic-user-2",
    "--enable-auto-recording",
    "true",
    "--enable-sip",
    "true",
    "--pin-code",
    "1234",
    "--allow-anonymous",
    "false",
]


def _run(argv, monkeypatch=None, base_url="https://test.ktalk.ru", session_token="sess-1"):
    if monkeypatch is not None:
        monkeypatch.setenv("KTALK_BASE_URL", base_url)
        monkeypatch.setenv("KTALK_SESSION_TOKEN", session_token)
        monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    from ktalk_mcp.cli import main

    return main(["--db", BAD_DB, *argv])


# --- _tri_bool ---------------------------------------------------------------------------


def test_tri_bool_accepts_true_false_case_insensitively():
    from ktalk_mcp.cli_meeting import _tri_bool

    assert _tri_bool("true") is True
    assert _tri_bool("TRUE") is True
    assert _tri_bool("false") is False
    assert _tri_bool("False") is False


def test_tri_bool_rejects_non_true_false_tokens():
    import argparse

    from ktalk_mcp.cli_meeting import _tri_bool

    with pytest.raises(argparse.ArgumentTypeError):
        _tri_bool("yes")
    with pytest.raises(argparse.ArgumentTypeError):
        _tri_bool("1")


# --- Регистрация подкоманд ----------------------------------------------------------------


def test_build_parser_registers_both_create_meeting_subcommands():
    from ktalk_mcp.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["create-meeting-preview"])
    assert args.command == "create-meeting-preview"
    args = parser.parse_args(["create-meeting-confirm"])
    assert args.command == "create-meeting-confirm"


# --- Предпросмотр: ноль сетевых вызовов, полные флаги -------------------------------------


def test_cli_create_meeting_preview_full_flags_zero_network_calls(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    rc = _run(_PREVIEW_ARGV_FULL, monkeypatch)

    assert rc == 0
    assert httpx_mock.get_requests() == []
    captured = capsys.readouterr()
    assert captured.out  # что-то человекочитаемое напечатано


def test_cli_create_meeting_preview_missing_room_name_names_the_field(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    argv = list(_PREVIEW_ARGV_FULL)
    idx = argv.index("--room-name")
    del argv[idx : idx + 2]

    rc = _run(argv, monkeypatch)

    assert rc != 0
    assert httpx_mock.get_requests() == []
    captured = capsys.readouterr()
    assert "roomName" in captured.out + captured.err


def test_cli_create_meeting_preview_missing_enable_sip_flag_is_not_silently_false(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """NFR-9: отсутствие `--enable-sip` не эквивалентно `False` — CLI отказывает,
    называя `enableSip`, а не молча создаёт тело с `enableSip: false`."""
    argv = list(_PREVIEW_ARGV_FULL)
    idx = argv.index("--enable-sip")
    del argv[idx : idx + 2]

    rc = _run(argv, monkeypatch)

    assert rc != 0
    assert httpx_mock.get_requests() == []
    captured = capsys.readouterr()
    assert "enableSip" in captured.out + captured.err


def test_cli_create_meeting_preview_no_required_users_flag_gives_explicit_empty_list(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """`--no-required-users` без `--required-user-key` -> явное «ноль участников»,
    предпросмотр проходит (не отклоняется как «не решено»)."""
    argv = list(_PREVIEW_ARGV_FULL)
    while "--required-user-key" in argv:
        idx = argv.index("--required-user-key")
        del argv[idx : idx + 2]
    argv.append("--no-required-users")

    rc = _run(argv, monkeypatch)

    assert rc == 0
    assert httpx_mock.get_requests() == []


def test_cli_create_meeting_preview_neither_required_user_key_nor_no_required_users_rejects(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """Ни `--required-user-key`, ни `--no-required-users` не переданы -> `None` ->
    `MissingFieldError("requiredUserKeys")` (rooms-calendar-spec «Контракт с QA-author»)."""
    argv = list(_PREVIEW_ARGV_FULL)
    while "--required-user-key" in argv:
        idx = argv.index("--required-user-key")
        del argv[idx : idx + 2]

    rc = _run(argv, monkeypatch)

    assert rc != 0
    assert httpx_mock.get_requests() == []
    captured = capsys.readouterr()
    assert "requiredUserKeys" in captured.out + captured.err


# --- isatty()-барьер -----------------------------------------------------------------------


def test_cli_create_meeting_confirm_refuses_when_not_a_tty(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """Под pytest stdin/stdout по умолчанию перехвачены — уже не терминал, негативный
    случай получаем без дополнительного мокирования (эквивалент пайпа/CI-раннера)."""
    assert sys.stdin.isatty() is False
    assert sys.stdout.isatty() is False

    rc = _run(["create-meeting-confirm", *_PREVIEW_ARGV_FULL[1:]], monkeypatch)

    assert rc != 0
    assert httpx_mock.get_requests() == []
    captured = capsys.readouterr()
    assert "терминал" in (captured.out + captured.err).lower()


def _with_real_pty(monkeypatch, input_line: str):
    """Подменяет sys.stdin/sys.stdout на реальный псевдотерминал и предзаписывает
    строку ввода в него — позитивный isatty()-сценарий (ADR-005-spec: "не мокируется
    как чистая функция")."""
    master_fd, slave_fd = pty.openpty()
    stdin_file = os.fdopen(os.dup(slave_fd), "r")
    stdout_file = os.fdopen(os.dup(slave_fd), "w")
    monkeypatch.setattr(sys, "stdin", stdin_file)
    monkeypatch.setattr(sys, "stdout", stdout_file)
    os.write(master_fd, f"{input_line}\n".encode())
    return master_fd, slave_fd


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_cli_create_meeting_confirm_over_real_tty_creates_exactly_once(
    httpx_mock: HTTPXMock, monkeypatch
):
    """Позитивный путь: реальный `pty` проходит `isatty()`, подтверждающий ввод "да"
    -> ровно один сетевой POST на создание."""
    master_fd, slave_fd = _with_real_pty(monkeypatch, "да")
    httpx_mock.add_response(status_code=200, json={"id": "MEET-CREATED-0001"})

    try:
        rc = _run(["create-meeting-confirm", *_PREVIEW_ARGV_FULL[1:]], monkeypatch)
    finally:
        os.close(master_fd)
        os.close(slave_fd)

    assert rc == 0
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    assert requests[0].method == "POST"


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_cli_create_meeting_confirm_network_failure_no_retry_exactly_one_attempt(
    httpx_mock: HTTPXMock, monkeypatch
):
    """AC FR-13/6 на CLI-уровне: сетевая ошибка при `POST /calendar` -> ровно одна
    попытка, сообщение о неопределённом исходе, не автоматический повтор."""
    import httpx as httpx_module

    master_fd, slave_fd = _with_real_pty(monkeypatch, "да")
    httpx_mock.add_exception(httpx_module.ConnectError("connection refused"))

    try:
        rc = _run(["create-meeting-confirm", *_PREVIEW_ARGV_FULL[1:]], monkeypatch)
    finally:
        os.close(master_fd)
        os.close(slave_fd)

    assert rc != 0
    assert len(httpx_mock.get_requests()) == 1
