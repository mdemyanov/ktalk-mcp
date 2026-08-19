"""AT-design: FR-13 CLI — `create-meeting-preview`/`create-meeting-confirm`
(`ktalk_mcp.cli_meeting`, расширение `ktalk_mcp.cli`).

Покрывает: булевы флаги НЕ `store_true` (отсутствие `--allow-anonymous` != `False`),
явная пустая коллекция участников (`--no-required-attendees` != отсутствие флага,
ADR-009 §5), явное «без PIN» (`--no-pin-code`, ADR-009 §2), условная обязательность
`--anonymous-access-expiration` (ADR-009 §3), `_tri_bool` (`TRUE`/`False`
принимаются, `yes`/`1` отклоняются), `isatty()`-барьер
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

import json
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
    "GMT+3",
    "--room-name",
    "test-room-alpha",
    "--required-attendee-key",
    "1001",
    "--required-attendee-key",
    "1002",
    "--enable-auto-recording",
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
    from ktalk_mcp.cli_meeting_args import tri_bool as _tri_bool

    assert _tri_bool("true") is True
    assert _tri_bool("TRUE") is True
    assert _tri_bool("false") is False
    assert _tri_bool("False") is False


def test_tri_bool_rejects_non_true_false_tokens():
    import argparse

    from ktalk_mcp.cli_meeting_args import tri_bool as _tri_bool

    with pytest.raises(argparse.ArgumentTypeError):
        _tri_bool("yes")
    with pytest.raises(argparse.ArgumentTypeError):
        _tri_bool("1")


# --- ADR-008: _print_error печатает response_body, маскирование не обходится -------------


def test_print_error_without_response_body_prints_only_message(capsys):
    from ktalk_mcp.cli_meeting_args import print_error as _print_error

    _print_error("Ошибка X")

    captured = capsys.readouterr()
    assert "Ошибка X" in captured.err
    assert "Тело ответа сервера" not in captured.err


def test_print_error_with_response_body_appends_it_to_message(capsys):
    from ktalk_mcp.cli_meeting_args import print_error as _print_error

    _print_error("Ошибка X", "тело ответа сервера тут")

    captured = capsys.readouterr()
    assert "Ошибка X" in captured.err
    assert "тело ответа сервера тут" in captured.err


def test_print_error_masks_secret_inside_response_body(monkeypatch, capsys):
    """NFR-10/SEC-001: `redact_secrets` маскирует секрет из активной переменной
    окружения, даже если он оказался внутри `response_body`, не только в основном
    тексте сообщения."""
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "super-secret-session-value")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    from ktalk_mcp.cli_meeting_args import print_error as _print_error

    _print_error("Ошибка сети", "лог сервера содержит super-secret-session-value внутри")

    captured = capsys.readouterr()
    assert "super-secret-session-value" not in captured.err


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


def test_dev009_cli_create_meeting_preview_json_zero_network_with_confirmation_id(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """DEV-009: `--json` не делает сетевых вызовов (инвариант превью не меняется).

    ADR-016 §2 отменил вторую половину прежнего контракта: `confirmation_id` снова
    выводится — хранилище персистентно, и именно id связывает предъявленное тело с
    записью. Тест переименован из `..._no_confirmation_id` вслед за сменой контракта."""
    rc = _run([*_PREVIEW_ARGV_FULL, "--json"], monkeypatch)

    assert rc == 0
    assert httpx_mock.get_requests() == []
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert set(data.keys()) == {"body", "confirmation_id"}
    assert data["body"]["subject"] == "Синтетическая встреча"
    assert data["confirmation_id"]


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


def test_cli_create_meeting_preview_missing_pin_code_signal_is_not_silently_none(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """ADR-009 §2: ни `--pin-code`, ни `--no-pin-code` -> `pinCode` не решён — CLI
    отказывает, называя `pinCode`, а не молча создаёт тело с `pinCode: null`."""
    argv = list(_PREVIEW_ARGV_FULL)
    idx = argv.index("--pin-code")
    del argv[idx : idx + 2]

    rc = _run(argv, monkeypatch)

    assert rc != 0
    assert httpx_mock.get_requests() == []
    captured = capsys.readouterr()
    assert "pinCode" in captured.out + captured.err


def test_cli_create_meeting_preview_no_pin_code_flag_gives_explicit_null(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """ADR-009 §2: `--no-pin-code` без `--pin-code` -> явное «без PIN» — предпросмотр
    проходит (не отклоняется как «не решено»)."""
    argv = list(_PREVIEW_ARGV_FULL)
    idx = argv.index("--pin-code")
    del argv[idx : idx + 2]
    argv.append("--no-pin-code")

    rc = _run(argv, monkeypatch)

    assert rc == 0
    assert httpx_mock.get_requests() == []


def test_cli_create_meeting_preview_no_required_attendees_flag_gives_explicit_empty_list(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """`--no-required-attendees` без `--required-attendee-key` -> явное «ноль
    участников», предпросмотр проходит (не отклоняется как «не решено»)."""
    argv = list(_PREVIEW_ARGV_FULL)
    while "--required-attendee-key" in argv:
        idx = argv.index("--required-attendee-key")
        del argv[idx : idx + 2]
    argv.append("--no-required-attendees")

    rc = _run(argv, monkeypatch)

    assert rc == 0
    assert httpx_mock.get_requests() == []


def test_cli_create_meeting_preview_neither_required_attendee_key_nor_no_flag_rejects(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """Ни `--required-attendee-key`, ни `--no-required-attendees` не переданы ->
    `None` -> `MissingFieldError("requiredAttendees")` (ADR-009 §1)."""
    argv = list(_PREVIEW_ARGV_FULL)
    while "--required-attendee-key" in argv:
        idx = argv.index("--required-attendee-key")
        del argv[idx : idx + 2]

    rc = _run(argv, monkeypatch)

    assert rc != 0
    assert httpx_mock.get_requests() == []
    captured = capsys.readouterr()
    assert "requiredAttendees" in captured.out + captured.err


def test_cli_create_meeting_preview_allow_anonymous_true_without_expiration_rejects(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """ADR-009 §3: `--allow-anonymous true` без `--anonymous-access-expiration` ->
    отказ, называющий `anonymousAccessExpirationDate` (нет вычисляемого дефолта)."""
    argv = list(_PREVIEW_ARGV_FULL)
    idx = argv.index("--allow-anonymous")
    argv[idx + 1] = "true"

    rc = _run(argv, monkeypatch)

    assert rc != 0
    assert httpx_mock.get_requests() == []
    captured = capsys.readouterr()
    assert "anonymousAccessExpirationDate" in captured.out + captured.err


def test_cli_create_meeting_preview_allow_anonymous_true_with_expiration_succeeds(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    argv = list(_PREVIEW_ARGV_FULL)
    idx = argv.index("--allow-anonymous")
    argv[idx + 1] = "true"
    argv += ["--anonymous-access-expiration", "2026-08-18T20:59:59.999Z"]

    rc = _run(argv, monkeypatch)

    assert rc == 0
    assert httpx_mock.get_requests() == []


# --- isatty()-барьер -----------------------------------------------------------------------


def test_cli_create_meeting_confirm_refuses_when_not_a_tty(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """Под pytest stdin/stdout по умолчанию перехвачены — уже не терминал, негативный
    случай получаем без дополнительного мокирования (эквивалент пайпа/CI-раннера).

    ADR-016 сменил причину отказа: до волны 6 отказывал сам TTY-барьер, теперь —
    отсутствие санкции (код 40). Проверяемое свойство то же и осталось верным:
    без терминала и без санкции команда не делает ни одного сетевого вызова."""
    assert sys.stdin.isatty() is False
    assert sys.stdout.isatty() is False

    rc = _run(["create-meeting-confirm", *_PREVIEW_ARGV_FULL[1:]], monkeypatch)

    assert rc == 40
    assert httpx_mock.get_requests() == []
    captured = capsys.readouterr()
    assert "санкци" in (captured.out + captured.err).lower()


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


# --- DEV-008: матрица статус x контроль x тело — что реально видит человек ---------------
#
# Предыдущий цикл (DEV-007) не покрывал статусные отказы сквозняком вовсе — только
# ConnectError. Здесь: 401/403 x контроль прошёл/упал x тело пустое/непустое.

_DEV008_MATRIX = [
    pytest.param(401, "тело ответа от /api/calendar", True, id="401-control_ok-body_nonempty"),
    pytest.param(401, "", True, id="401-control_ok-body_empty"),
    pytest.param(401, "тело ответа от /api/calendar", False, id="401-control_fail-body_nonempty"),
    pytest.param(401, "", False, id="401-control_fail-body_empty"),
    pytest.param(403, "тело ответа от /api/calendar", True, id="403-control_ok-body_nonempty"),
    pytest.param(403, "", True, id="403-control_ok-body_empty"),
    pytest.param(403, "тело ответа от /api/calendar", False, id="403-control_fail-body_nonempty"),
    pytest.param(403, "", False, id="403-control_fail-body_empty"),
]


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
@pytest.mark.parametrize("status_code, response_text, control_ok", _DEV008_MATRIX)
def test_dev008_status_control_body_matrix_prints_diagnostically_useful_text(
    httpx_mock: HTTPXMock, monkeypatch, capsys, status_code, response_text, control_ok
):
    import re

    base_url = "https://test.ktalk.ru"
    httpx_mock.add_response(
        status_code=status_code,
        text=response_text,
        url=re.compile(rf"^{re.escape(base_url)}/api/calendar(\?.*)?$"),
    )
    if control_ok:
        httpx_mock.add_response(
            status_code=200,
            json={"recordings": []},
            url=re.compile(rf"^{re.escape(base_url)}/api/recordings(\?.*)?$"),
        )
    else:
        httpx_mock.add_response(
            status_code=status_code,
            url=re.compile(rf"^{re.escape(base_url)}/api/recordings(\?.*)?$"),
        )

    master_fd, slave_fd = _with_real_pty(monkeypatch, "да")
    try:
        rc = _run(
            ["create-meeting-confirm", *_PREVIEW_ARGV_FULL[1:]], monkeypatch, base_url=base_url
        )
    finally:
        os.close(master_fd)
        os.close(slave_fd)

    assert rc != 0
    err = capsys.readouterr().err

    # ФАКТ 1: HTTP-код исходного отказа виден всегда, в обеих ветках.
    assert f"HTTP {status_code}" in err

    # ФАКТ 2: пустое тело — видимый факт контура, не неразличимо с "тело потерялось".
    if response_text:
        assert response_text in err
        assert "(пусто)" not in err
    else:
        assert "Тело ответа сервера: (пусто)" in err

    if control_ok:
        # ADR-008: контроль в порядке -> отдельное сообщение, не "Токен истёк"/"Доступ запрещён".
        assert "Токен сессии истёк" not in err
        assert "Доступ запрещён" not in err
        assert "ADR-008" in err
        assert "Контрольный вызов" not in err  # контроль не падал — нечего показывать
    else:
        # ФАКТ 3: контроль тоже упал -> это видно явно (класс/HTTP-код/текст), не тишина.
        assert "Контрольный вызов" in err
        assert "list_recordings" in err
        assert "тоже упал" in err
        assert "KTalkAuthError" in err
        if status_code == 401:
            assert "Токен сессии истёк" in err
        else:
            assert "Доступ запрещён" in err


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_cli_create_meeting_confirm_network_failure_no_retry_exactly_one_attempt(
    httpx_mock: HTTPXMock, monkeypatch
):
    """AC FR-13/6 на CLI-уровне: сетевая ошибка при `POST /api/calendar` -> ровно
    одна попытка самой записи, сообщение о неопределённом исходе, не автоматический
    повтор. ADR-007 п.3 добавляет один контрольный GET (диагностика ADR-004), тоже
    проваливается -> исходное сообщение о сетевой ошибке не меняется."""
    import httpx as httpx_module

    master_fd, slave_fd = _with_real_pty(monkeypatch, "да")
    httpx_mock.add_exception(httpx_module.ConnectError("connection refused"))
    httpx_mock.add_exception(httpx_module.ConnectError("connection refused"))

    try:
        rc = _run(["create-meeting-confirm", *_PREVIEW_ARGV_FULL[1:]], monkeypatch)
    finally:
        os.close(master_fd)
        os.close(slave_fd)

    assert rc != 0
    requests = httpx_mock.get_requests()
    assert len(requests) == 2
    assert requests[0].method == "POST"
    assert requests[1].method == "GET"


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_cli_create_meeting_confirm_401_with_working_control_prints_adr008_message(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """DEV-007: сквозной путь CLI (`cmd_create_meeting_confirm` -> `_print_error`)
    ранее не был покрыт для HTTP-статусного отказа (только для `ConnectError` —
    см. тест выше) — именно этот пробел пропустил дефект в бою. POST -> 401,
    контроль (`list_recordings`) -> 200: пользователь должен увидеть сообщение
    ADR-008 (`KTalkWriteAuthMismatchError`), не старый текст «Токен сессии истёк»,
    и тело ответа сервера."""
    import re

    base_url = "https://test.ktalk.ru"
    httpx_mock.add_response(
        status_code=401,
        text="тело ответа от /api/calendar",
        url=re.compile(rf"^{re.escape(base_url)}/api/calendar(\?.*)?$"),
    )
    httpx_mock.add_response(
        status_code=200,
        json={"recordings": []},
        url=re.compile(rf"^{re.escape(base_url)}/api/recordings(\?.*)?$"),
    )

    master_fd, slave_fd = _with_real_pty(monkeypatch, "да")
    try:
        rc = _run(
            ["create-meeting-confirm", *_PREVIEW_ARGV_FULL[1:]], monkeypatch, base_url=base_url
        )
    finally:
        os.close(master_fd)
        os.close(slave_fd)

    assert rc != 0
    captured = capsys.readouterr()
    assert "KTalkWriteAuthMismatchError" not in captured.err  # сообщение, не имя класса
    assert "ADR-008" in captured.err
    assert "Токен сессии истёк" not in captured.err
    assert "тело ответа от /api/calendar" in captured.err
