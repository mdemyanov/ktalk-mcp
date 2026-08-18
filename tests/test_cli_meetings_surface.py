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
импорте/синтаксисе — все импортируемые модули (`ktalk_mcp.cli`,
`ktalk_mcp.cli_meeting`, `ktalk_mcp.cli_meetings_read`, `ktalk_mcp.cli_contacts`)
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
    from ktalk_mcp.cli import main

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
    from ktalk_mcp.cli import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["list-calendar"])
    with pytest.raises(SystemExit):
        parser.parse_args(["list-calendar", "--start", "2026-08-01"])
    assert False, (
        "TODO: AC-32-1b — оба вызова parse_args должны поднимать SystemExit "
        "(argparse required), не подставлять дефолтный период; дописать "
        "позитивную ветку (--start и --end оба переданы -> не SystemExit)"
    )


def test_ac_32_2_list_calendar_json_preserves_incomplete_segments_verbatim(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    assert False, (
        "TODO: AC-32-2 — замокать get_calendar_window (или сеть) так, чтобы "
        "результат содержал непустой incomplete_segments; вызвать "
        "list-calendar --start --end --json; распарсить stdout как JSON; "
        "assert данные['incomplete_segments'] равен исходному списку дословно "
        "(не пустой, не булев флаг)"
    )


def test_ac_32_3_empty_items_success_vs_error_are_distinguishable_by_exit_code_and_channel(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    assert False, (
        "TODO: AC-32-3 — два прогона: (1) мок пустого календаря -> rc==0, "
        "stdout валиден как JSON с items==[], stderr пуст; (2) мок сетевой "
        "ошибки -> rc==1, stderr содержит 'Ошибка:', stdout пуст. Доказать, "
        "что (rc, channel) различают исходы, не текст 'встреч нет'"
    )


def test_list_calendar_malformed_start_date_fails_closed_not_traceback(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    assert False, (
        "TODO: испорченный ввод — list-calendar --start 2026-13-45 --end "
        "2026-08-20 --json; ожидание: rc==1, 'Ошибка:' на stderr, ни один из "
        "потоков не содержит 'Traceback' (ValueError пойман _run, не утёк "
        "необработанным)"
    )


# === FR-34 — cancel-meeting-preview / -confirm =============================================


def test_ac_34_1b_cancel_meeting_preview_zero_network_echoes_id_and_reason(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    assert False, (
        "TODO: AC-34-1b — cancel-meeting-preview --id abc123== --reason "
        "'встреча переносится'; assert rc==0, httpx_mock.get_requests()==[], "
        "вывод содержит 'abc123==' и 'встреча переносится' дословно (эхо, "
        "не изобретённые значения)"
    )


def test_ac_34_1c_cancel_meeting_commands_reject_json_flag():
    """DEV-009: расхождение из at-design «Находки» п.1 закрыто для `-preview`,
    сохранено для `-confirm` осознанно — см. дев-заметку
    `content/60-implementation/dev-009-cli-json-and-exit-codes.md`.

    `cancel-meeting-preview` — без сети, безопасно дать `--json` (используется
    промт-слоем для handoff-сообщения). `cancel-meeting-confirm` — только
    интерактивный TTY (NFR-22/NFR-23), программно не вызывается, `--json` там не
    нужен и не регистрируется — argparse отказывает на неизвестном флаге."""
    from ktalk_mcp.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["cancel-meeting-preview", "--id", "x", "--json"])
    assert args.json is True

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["cancel-meeting-confirm", "--id", "x", "--json"])
    assert exc_info.value.code == 2  # argparse: неизвестный аргумент


def test_dev009_cancel_meeting_preview_json_zero_network_no_confirmation_id(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """DEV-009: `--json` не делает сетевых вызовов (инвариант превью не меняется)
    и не отдаёт `confirmation_id` (ADR-015: не переживает границу процессов, не
    основание для подтверждения из другого процесса)."""
    rc = _run(
        ["cancel-meeting-preview", "--id", "abc123==", "--reason", "переносится", "--json"],
        monkeypatch,
    )

    assert rc == 0
    assert httpx_mock.get_requests() == []
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data == {
        "payload": {"operation": "cancel_meeting", "id": "abc123==", "reason": "переносится"}
    }
    assert "confirmation_id" not in captured.out


def test_ac_34_2b_cancel_meeting_id_is_required_on_both_subcommands():
    from ktalk_mcp.cli import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["cancel-meeting-preview"])
    with pytest.raises(SystemExit):
        parser.parse_args(["cancel-meeting-confirm"])
    assert False, (
        "TODO: AC-34-2b — оба parse_args без --id должны падать SystemExit "
        "(argparse required=True на --id, cli_meeting.py::_add_cancel_args); "
        "дописать позитивную ветку (--id передан -> не SystemExit на этом поле)"
    )


def test_nfr23_cancel_meeting_confirm_refuses_without_tty(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    assert False, (
        "TODO: NFR-23-b — под pytest sys.stdin/stdout уже не TTY; вызвать "
        "cancel-meeting-confirm --id abc123==; assert rc!=0, "
        "httpx_mock.get_requests()==[], текст (stdout+stderr) содержит "
        "'терминал' (регистронезависимо) — тот же приём, что "
        "test_cli_meeting.py::test_cli_create_meeting_confirm_refuses_when_not_a_tty"
    )


def test_nfr22_cancel_meeting_confirm_network_failure_no_retry_exactly_one_post(
    httpx_mock: HTTPXMock, monkeypatch
):
    assert False, (
        "TODO: NFR-22 (cancel, CLI-уровень) — реальный pty (_with_real_pty, "
        "ввод 'да'), httpx_mock.add_exception(httpx.ConnectError(...)) на "
        "POST .../cancel; вызвать cancel-meeting-confirm --id abc123==; "
        "assert rc!=0, ровно один POST-запрос среди httpx_mock.get_requests() "
        "(не два и не ноль), текст называет 'исход неизвестен' и "
        "'list-calendar' / 'list_calendar' — тот же паттерн, что "
        "test_cli_create_meeting_confirm_network_failure_no_retry_exactly_one_attempt "
        "в test_cli_meeting.py, применённый к cancel"
    )


# === FR-35 — search-contacts (известное расхождение) ========================================


def test_search_contacts_rejects_json_flag():
    """DEV-009: расхождение из at-design «Находки» п.1 закрыто — `search-contacts`
    теперь регистрирует `--json` (используется промт-слоем для машиночитаемого
    вывода списка кандидатов). Имя теста сохранено для трассировки из at-design
    (`at-design-ktalk-plugin-meetings.md`, FR-35), тело перевёрнуто на проверку
    нового контракта — см. дев-заметку
    `content/60-implementation/dev-009-cli-json-and-exit-codes.md`."""
    from ktalk_mcp.cli import build_parser

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
    from ktalk_mcp.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["get-room", "some-room", "--json"])
    known_flags = vars(args).keys()
    assert False, (
        "TODO: AC-36-2 (структурная опора) — assert ни один из известных "
        "флагов get-room ('check', 'available', 'exists', 'occupied') не "
        "присутствует в vars(args) — get-room физически не предлагает "
        "проверку занятости имени (ADR-006 п.5); known_flags = "
        f"{sorted(known_flags)!r} — использовать этот список в финальном ассерте"
    )


def test_get_room_json_flag_prints_valid_json_room_payload(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    assert False, (
        "TODO: замокать get_room (или сеть /api/rooms/{name}) на успешный "
        "ответ; вызвать get-room test-room-alpha --json; распарсить stdout "
        "как JSON; assert rc==0, имя комнаты 'test-room-alpha' присутствует "
        "где-то в распарсенных данных"
    )


def test_get_room_error_goes_to_stderr_not_stdout(httpx_mock: HTTPXMock, monkeypatch, capsys):
    assert False, (
        "TODO: замокать get_room на исключение (сеть/авторизация); вызвать "
        "get-room test-room-alpha; assert rc==1, 'Ошибка:' в stderr, stdout пуст"
    )


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
    assert False, (
        "TODO: AC-37-1 — для каждой команды из argv замокать нижележащий "
        "вызов (клиент/get_room/search_contacts) так, чтобы он бросал "
        "RuntimeError('сообщение сервера, уникальное для этого прогона'); "
        "вызвать CLI; assert исходный текст присутствует ДОСЛОВНО в "
        "(stdout+stderr) (после redact_secrets — секретов в фикстуре нет, "
        "текст не тронут), не заменён на общее 'что-то пошло не так'"
    )


def test_ac_38_1_meetings_commands_and_escalation_targets_are_all_registry_free():

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
    assert False, (
        "TODO: AC-38-1 (структурная опора эскалации) — assert "
        "meetings_commands <= _REGISTRY_FREE_COMMANDS И escalation_targets <= "
        "_REGISTRY_FREE_COMMANDS — путь эскалации (auth-status/config show) "
        "достижим из того же процесса, что любая команда FR-32…FR-36/FR-33/"
        f"FR-34, без доступного реестра. meetings_commands={meetings_commands!r}, "
        f"escalation_targets={escalation_targets!r}"
    )
