"""AT-design: QA-005 — CLI-контракты, на которые опирается промт-поверхность
плагина ktalk для встреч (`content/40-architecture/at-design-ktalk-plugin-meetings.md`).

Периметр: только факты пакета `ktalk-mcp` (флаги, `--json`, коды возврата, канал
stdout/stderr, TTY-барьер, отсутствие автоповтора) — не текст промта плагина
(дерево `ktalk-plugin`, другой репозиторий, вне периметра этой задачи, см.
at-design «Граница периметра»).

Красные по замыслу: `list-calendar`/`get-room`/`cancel-meeting-preview`/
`cancel-meeting-confirm`/`search-contacts` CLI-уровня уже существуют и работают —
red здесь означает «CLI-контракт этой волны ещё не подтверждён тестом», не
«функциональность отсутствует». Каждый stub падает на `assert False`, не на
импорте/синтаксисе — все импортируемые модули (`ktalk_cli.cli`,
`ktalk_cli.cli_meeting`, `ktalk_cli.cli_meetings_read`, `ktalk_cli.cli_contacts`)
уже существуют в 0.7.0.
"""

from __future__ import annotations

import json
import os
import pty
import sys

import httpx
import pytest
from pytest_httpx import HTTPXMock

BAD_DB = "/nonexistent/path/does-not-exist/registry.db"


def _run(argv, monkeypatch=None, base_url="https://test.ktalk.ru", session_token="sess-1"):
    if monkeypatch is not None:
        monkeypatch.setenv("KTALK_BASE_URL", base_url)
        monkeypatch.setenv("KTALK_SESSION_TOKEN", session_token)
        monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    from ktalk_cli.cli import main

    return main(["--db", BAD_DB, *argv])


def _with_real_pty(monkeypatch, input_line: str):
    """Тот же приём, что `test_cli_meeting.py::_with_real_pty` — реальный
    псевдотерминал, не мок `isatty()` как чистой функции (ADR-005-spec)."""
    master_fd, slave_fd = pty.openpty()
    stdin_file = os.fdopen(os.dup(slave_fd), "r")
    stdout_file = os.fdopen(os.dup(slave_fd), "w")
    monkeypatch.setattr(sys, "stdin", stdin_file)
    monkeypatch.setattr(sys, "stdout", stdout_file)
    os.write(master_fd, f"{input_line}\n".encode())
    return master_fd, slave_fd


# === FR-32 — list-calendar =================================================================


def test_ac_32_1b_list_calendar_requires_start_and_end_no_silent_default():
    from ktalk_cli.cli import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["list-calendar"])
    with pytest.raises(SystemExit):
        parser.parse_args(["list-calendar", "--start", "2026-08-01"])
    # Позитивная ветка: оба обязательных флага переданы -> parse_args не падает.
    args = parser.parse_args(["list-calendar", "--start", "2026-08-01", "--end", "2026-08-02"])
    assert args.start == "2026-08-01"
    assert args.end == "2026-08-02"


def test_ac_32_2_list_calendar_json_preserves_incomplete_segments_verbatim(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    # 100 элементов на один сегмент == потолок _PAGE_SIZE -> сегмент помечается
    # неполным (calendar_reader._fetch_segment: `len(items) >= _PAGE_SIZE`).
    items = [
        {"id": f"item-{i}", "roomName": "room-a", "start": "2026-08-01T10:00:00Z"}
        for i in range(100)
    ]
    httpx_mock.add_response(json={"items": items})

    rc = _run(
        ["list-calendar", "--start", "2026-08-01", "--end", "2026-08-02", "--json"], monkeypatch
    )

    assert rc == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["incomplete_segments"] == [["2026-08-01", "2026-08-02"]]


def test_ac_32_3_empty_items_success_vs_error_are_distinguishable_by_exit_code_and_channel(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    httpx_mock.add_response(json={"items": []})
    rc_ok = _run(
        ["list-calendar", "--start", "2026-08-01", "--end", "2026-08-02", "--json"], monkeypatch
    )
    ok_captured = capsys.readouterr()

    assert rc_ok == 0
    data = json.loads(ok_captured.out)
    assert data["items"] == []
    assert ok_captured.err == ""

    httpx_mock.add_exception(httpx.ConnectError("boom"))
    # ADR-007: контрольный GET (diagnose_undocumented_failure -> list_recordings)
    # срабатывает после падения основного запроса — без мока он "не ожидаемый".
    httpx_mock.add_response(json={"items": []})
    rc_err = _run(
        ["list-calendar", "--start", "2026-08-01", "--end", "2026-08-02", "--json"], monkeypatch
    )
    err_captured = capsys.readouterr()

    assert rc_err == 1
    assert "Ошибка:" in err_captured.err
    assert err_captured.out == ""

    assert (rc_ok, rc_err) == (0, 1)


def test_list_calendar_malformed_start_date_fails_closed_not_traceback(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    rc = _run(
        ["list-calendar", "--start", "2026-13-45", "--end", "2026-08-20", "--json"], monkeypatch
    )

    assert rc == 1
    captured = capsys.readouterr()
    assert "Ошибка:" in captured.err
    assert "Traceback" not in captured.err
    assert "Traceback" not in captured.out


# === FR-34 — cancel-meeting-preview / -confirm =============================================


def test_ac_34_1b_cancel_meeting_preview_zero_network_echoes_id_and_reason(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    rc = _run(
        ["cancel-meeting-preview", "--id", "abc123==", "--reason", "встреча переносится"],
        monkeypatch,
    )

    assert rc == 0
    assert httpx_mock.get_requests() == []
    captured = capsys.readouterr()
    assert "abc123==" in captured.out
    assert "встреча переносится" in captured.out


def test_ac_34_1c_cancel_meeting_commands_accept_json_flag():
    """ADR-016 §1: `--json` теперь есть у обеих команд.

    DEV-009 не регистрировал его у `*-confirm` осознанно — «программно не
    вызывается, машиночитаемый вывод не нужен». Волна 6 отменила посылку: агент
    вызывает `*-confirm` сам и обязан разобрать исход машинно. Тест переименован
    из `..._reject_json_flag` вслед за сменой контракта."""
    from ktalk_cli.cli import build_parser

    parser = build_parser()
    assert parser.parse_args(["cancel-meeting-preview", "--id", "x", "--json"]).json is True
    assert parser.parse_args(["cancel-meeting-confirm", "--id", "x", "--json"]).json is True


def test_dev009_cancel_meeting_preview_json_zero_network_with_confirmation_id(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """DEV-009: `--json` не делает сетевых вызовов (инвариант превью не меняется).
    ADR-016 §2 вернул `confirmation_id` в вывод — он снова переживает границу
    процессов и обязателен для подтверждения в санкционном канале."""
    rc = _run(
        ["cancel-meeting-preview", "--id", "abc123==", "--reason", "переносится", "--json"],
        monkeypatch,
    )

    assert rc == 0
    assert httpx_mock.get_requests() == []
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["payload"] == {
        "operation": "cancel_meeting",
        "id": "abc123==",
        "reason": "переносится",
    }
    assert data["confirmation_id"]


def test_ac_34_2b_cancel_meeting_id_is_required_on_both_subcommands():
    from ktalk_cli.cli import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["cancel-meeting-preview"])
    with pytest.raises(SystemExit):
        parser.parse_args(["cancel-meeting-confirm"])
    # Позитивная ветка: --id передан -> parse_args не падает на этом поле.
    args_preview = parser.parse_args(["cancel-meeting-preview", "--id", "abc123=="])
    assert args_preview.id == "abc123=="
    args_confirm = parser.parse_args(["cancel-meeting-confirm", "--id", "abc123=="])
    assert args_confirm.id == "abc123=="


def test_nfr23_cancel_meeting_confirm_refuses_without_tty(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    assert sys.stdin.isatty() is False
    assert sys.stdout.isatty() is False

    rc = _run(["cancel-meeting-confirm", "--id", "abc123=="], monkeypatch)

    assert rc != 0
    assert httpx_mock.get_requests() == []
    captured = capsys.readouterr()
    assert "терминал" in (captured.out + captured.err).lower()


def test_nfr22_cancel_meeting_confirm_network_failure_no_retry_exactly_one_post(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    master_fd, slave_fd = _with_real_pty(monkeypatch, "да")
    httpx_mock.add_exception(httpx.ConnectError("connection refused"))
    httpx_mock.add_exception(httpx.ConnectError("connection refused"))

    try:
        rc = _run(["cancel-meeting-confirm", "--id", "abc123=="], monkeypatch)
    finally:
        os.close(master_fd)
        os.close(slave_fd)

    assert rc != 0
    requests = httpx_mock.get_requests()
    post_requests = [r for r in requests if r.method == "POST"]
    assert len(post_requests) == 1
    # sys.stdout подменён реальным pty (см. _with_real_pty) — capsys видит только
    # stderr, туда `_print_error` пишет сообщение (тот же приём, что
    # test_cli_create_meeting_confirm_401_with_working_control_prints_adr008_message).
    err = capsys.readouterr().err
    assert "исход неизвестен" in err
    assert "list-calendar" in err or "list_calendar" in err


# === FR-35 — search-contacts (известное расхождение) ========================================


def test_search_contacts_rejects_json_flag():
    """DEV-009: расхождение из at-design «Находки» п.1 закрыто — `search-contacts`
    теперь регистрирует `--json` (используется промт-слоем для машиночитаемого
    вывода списка кандидатов). Имя теста сохранено для трассировки из at-design
    (`at-design-ktalk-plugin-meetings.md`, FR-35), тело перевёрнуто на проверку
    нового контракта — см. дев-заметку
    `content/60-implementation/dev-009-cli-json-and-exit-codes.md`."""
    from ktalk_cli.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["search-contacts", "--query", "x", "--json"])
    assert args.json is True


def test_dev009_search_contacts_json_zero_matches_shape(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """`--json` на 0 кандидатов — валидный JSON, не пустая строка/markdown."""
    httpx_mock.add_response(json={"contacts": []})

    rc = _run(["search-contacts", "--query", "zzz-no-match", "--json"], monkeypatch)

    assert rc == 2
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data == {"query": "zzz-no-match", "candidates": []}
    assert captured.err == ""


def test_ac_35_3_zero_matches_vs_network_error_are_distinguishable_by_exit_code_and_channel(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """AC-35-3, DEV-009: было — 0 найдено и сетевой отказ делили один и тот же
    `rc == 1`, различить их можно было только каналом (at-design «Замаскированный
    отказ»). Теперь коды развели: `2` — 0 найдено (не отказ), `1` — отказ (сеть/
    авторизация), `0` — найден хотя бы один. Различение по каналу остаётся верным
    как дополнительная гарантия, не единственная."""
    httpx_mock.add_response(json={"contacts": []})
    rc_zero = _run(["search-contacts", "--query", "zzz-no-match"], monkeypatch)
    zero_captured = capsys.readouterr()

    assert rc_zero == 2
    assert "Ничего не найдено" in zero_captured.out
    assert zero_captured.err == ""

    httpx_mock.add_exception(httpx.ConnectError("boom"))
    rc_error = _run(["search-contacts", "--query", "zzz-no-match"], monkeypatch)
    error_captured = capsys.readouterr()

    assert rc_error == 1
    assert "Ошибка:" in error_captured.err
    assert error_captured.out == ""

    assert rc_zero != rc_error  # DEV-009: коды больше не совпадают


# === FR-36 — get-room ========================================================================


def test_get_room_has_no_availability_check_flag():
    from ktalk_cli.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["get-room", "some-room", "--json"])
    known_flags = vars(args).keys()
    assert not {"check", "available", "exists", "occupied"} & set(known_flags), (
        f"get-room не должен предлагать проверку занятости имени (ADR-006 п.5); "
        f"known_flags={sorted(known_flags)!r}"
    )


def test_get_room_json_flag_prints_valid_json_room_payload(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    httpx_mock.add_response(json={"roomName": "test-room-alpha"})

    rc = _run(["get-room", "test-room-alpha", "--json"], monkeypatch)

    assert rc == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "test-room-alpha" in json.dumps(data, ensure_ascii=False)


def test_get_room_error_goes_to_stderr_not_stdout(httpx_mock: HTTPXMock, monkeypatch, capsys):
    httpx_mock.add_exception(httpx.ConnectError("boom"))
    # ADR-007: контрольный GET (diagnose_undocumented_failure -> list_recordings).
    httpx_mock.add_response(json={"items": []})

    rc = _run(["get-room", "test-room-alpha"], monkeypatch)

    assert rc == 1
    captured = capsys.readouterr()
    assert "Ошибка:" in captured.err
    assert captured.out == ""


# === FR-37/FR-38 — деградация и эскалация (сквозные) =========================================


@pytest.mark.parametrize(
    "argv",
    [
        pytest.param(
            ["list-calendar", "--start", "2026-08-01", "--end", "2026-08-02", "--json"],
            id="list-calendar",
        ),
        pytest.param(["get-room", "some-room", "--json"], id="get-room"),
        pytest.param(["search-contacts", "--query", "иванов"], id="search-contacts"),
    ],
)
def test_ac_37_1_cli_error_text_passthrough_not_replaced_by_generic_message(
    argv, httpx_mock: HTTPXMock, monkeypatch, capsys
):
    unique_message = "сообщение сервера, уникальное для этого прогона"
    httpx_mock.add_exception(RuntimeError(unique_message))

    rc = _run(argv, monkeypatch)

    assert rc != 0
    captured = capsys.readouterr()
    text = captured.out + captured.err
    assert unique_message in text
    assert "что-то пошло не так" not in text.lower()


def test_ac_38_1_meetings_commands_and_escalation_targets_are_all_registry_free():
    from ktalk_cli.cli import _REGISTRY_FREE_COMMANDS

    meetings_commands = {
        "list-calendar",
        "get-room",
        "search-contacts",
        "cancel-meeting-preview",
        "cancel-meeting-confirm",
        "create-meeting-preview",
        "create-meeting-confirm",
    }
    escalation_targets = {"auth-status", "config"}
    assert meetings_commands <= _REGISTRY_FREE_COMMANDS
    assert escalation_targets <= _REGISTRY_FREE_COMMANDS
