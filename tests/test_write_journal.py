"""QA-007 (волна 6): журнал пишущих операций — ADR-016 §4/§5, NFR-23 п.6.

Красные по замыслу до DEV-012: модуля `ktalk_cli.write_journal` не существует.
"""

from __future__ import annotations

import json
import re

import httpx
import pytest
from pytest_httpx import HTTPXMock

BAD_DB = "/nonexistent/path/does-not-exist/registry.db"

_MEETING_ARGS = [
    "--subject",
    "Синтетическая встреча",
    "--start",
    "2026-08-20T10:00:00+03:00",
    "--end",
    "2026-08-20T11:00:00+03:00",
    "--timezone",
    "GMT+3",
    "--room-name",
    "synthetic-room",
    "--required-attendee-key",
    "1001",
    "--enable-auto-recording",
    "false",
    "--no-pin-code",
    "--allow-anonymous",
    "false",
]


def _run(argv, monkeypatch=None):
    if monkeypatch is not None:
        monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
        monkeypatch.setenv("KTALK_SESSION_TOKEN", "super-secret-session-value")
        monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    from ktalk_cli.cli import main

    return main(["--db", BAD_DB, *argv])


def _confirm_once(monkeypatch, capsys):
    from ktalk_cli import write_sanction

    write_sanction.grant("create_meeting", hours=8, operations=3)
    assert _run(["create-meeting-preview", *_MEETING_ARGS, "--json"], monkeypatch) == 0
    cid = json.loads(capsys.readouterr().out)["confirmation_id"]
    return _run(["create-meeting-confirm", *_MEETING_ARGS, "--confirmation-id", cid], monkeypatch)


def _events():
    from ktalk_cli import write_journal

    return [
        json.loads(line)
        for line in write_journal.journal_path().read_text(encoding="utf-8").splitlines()
    ]


def test_journal_records_attempt_and_outcome_for_successful_write(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    httpx_mock.add_response(status_code=200, json={"id": "MEET-CREATED-0001"})

    assert _confirm_once(monkeypatch, capsys) == 0

    events = _events()
    assert [event["event"] for event in events] == ["attempt", "outcome"]
    attempt, outcome = events
    assert attempt["operation"] == "create_meeting"
    assert attempt["channel"] == "sanctioned"
    assert attempt["body"]["subject"] == "Синтетическая встреча"
    assert attempt["body_sha256"] and attempt["confirmation_id"]
    assert attempt["sanction_remaining"] == 2
    assert outcome["result"] == "ok"
    assert outcome["status_code"] == 200


@pytest.mark.parametrize(
    "responder, expected_result, expected_code",
    [
        pytest.param({"status_code": 403}, "failed", 403, id="отказ сервера"),
        pytest.param(None, "unknown", None, id="сеть недоступна"),
    ],
)
def test_journal_records_failed_and_unknown_outcomes(
    httpx_mock: HTTPXMock, monkeypatch, capsys, responder, expected_result, expected_code
):
    calendar = re.compile(r".*/api/calendar(\?.*)?$")
    if responder is None:
        httpx_mock.add_exception(httpx.ConnectError("сеть недоступна"), url=calendar)
    else:
        httpx_mock.add_response(**responder, url=calendar)
    httpx_mock.add_response(
        status_code=200, json={"recordings": []}, url=re.compile(r".*/api/recordings.*")
    )

    assert _confirm_once(monkeypatch, capsys) == 1

    outcome = _events()[-1]
    assert outcome["event"] == "outcome"
    assert outcome["result"] == expected_result
    assert outcome["status_code"] == expected_code


def test_journal_does_not_contain_secret_values(httpx_mock: HTTPXMock, monkeypatch, capsys):
    httpx_mock.add_response(status_code=200, json={"id": "MEET-CREATED-0001"})

    assert _confirm_once(monkeypatch, capsys) == 0

    from ktalk_cli import write_journal

    assert "super-secret-session-value" not in write_journal.journal_path().read_text(
        encoding="utf-8"
    )


def test_journal_file_permissions_are_0600(httpx_mock: HTTPXMock, monkeypatch, capsys):
    httpx_mock.add_response(status_code=200, json={"id": "MEET-CREATED-0001"})

    assert _confirm_once(monkeypatch, capsys) == 0

    from ktalk_cli import write_journal

    assert write_journal.journal_path().stat().st_mode & 0o777 == 0o600


def test_unwritable_journal_blocks_the_network_call(httpx_mock: HTTPXMock, monkeypatch, capsys):
    """Прослеживаемость не опциональна: не записан `attempt` — сетевого вызова нет."""
    from ktalk_cli import write_journal

    path = write_journal.journal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.mkdir()  # каталог на месте файла — дозапись невозможна

    assert _confirm_once(monkeypatch, capsys) == 1
    assert httpx_mock.get_requests() == []
    assert "журнал" in capsys.readouterr().err.lower()
