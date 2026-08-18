"""QA-007 (волна 6): подтверждение записи в неинтерактивном канале — ADR-016 §1/§4.

Красные по замыслу до DEV-012: флага `--confirmation-id` и санкционного канала нет.
Транспорт подменён, `XDG_*` уведены в tmp автouse-фикстурой — ни одной боевой операции.
"""

from __future__ import annotations

import json

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
    "Europe/Moscow",
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

_CANCEL_ARGS = ["--id", "TUVFVElORy0wMDAx", "--reason", "синтетическая отмена"]


def _run(argv, monkeypatch=None, base_url="https://test.ktalk.ru"):
    if monkeypatch is not None:
        monkeypatch.setenv("KTALK_BASE_URL", base_url)
        monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-1")
        monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    from ktalk_mcp.cli import main

    return main(["--db", BAD_DB, *argv])


def _preview_id(command, args, monkeypatch, capsys):
    assert _run([command, *args, "--json"], monkeypatch) == 0
    return json.loads(capsys.readouterr().out)["confirmation_id"]


def _grant(operation, **kwargs):
    from ktalk_mcp import write_sanction

    write_sanction.grant(operation, **{"hours": 8, "operations": 3, **kwargs})


# --- ADR-016 §2: id снова переживает границу процессов ------------------------------------


@pytest.mark.parametrize(
    "command, args, payload_key",
    [
        ("create-meeting-preview", _MEETING_ARGS, "body"),
        ("cancel-meeting-preview", _CANCEL_ARGS, "payload"),
    ],
)
def test_preview_json_exposes_confirmation_id(
    monkeypatch, capsys, command, args, payload_key
):
    assert _run([command, *args, "--json"], monkeypatch) == 0

    data = json.loads(capsys.readouterr().out)
    assert payload_key in data
    assert isinstance(data.get("confirmation_id"), str) and data["confirmation_id"]


# --- FR-33: санкция -----------------------------------------------------------------------


def test_confirm_without_sanction_refuses_and_makes_no_request(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """С ВАЛИДНЫМ id и без санкции — 40: санкция проверяется раньше подтверждения,
    иначе перебор id различал бы состояния санкции по коду возврата."""
    cid = _preview_id("create-meeting-preview", _MEETING_ARGS, monkeypatch, capsys)

    rc = _run(["create-meeting-confirm", *_MEETING_ARGS, "--confirmation-id", cid], monkeypatch)

    assert rc == 40
    assert httpx_mock.get_requests() == []


def test_confirm_with_sanction_and_confirmation_id_creates_exactly_once(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    from ktalk_mcp import write_sanction

    _grant("create_meeting")
    cid = _preview_id("create-meeting-preview", _MEETING_ARGS, monkeypatch, capsys)
    httpx_mock.add_response(status_code=200, json={"id": "MEET-CREATED-0001"})

    rc = _run(["create-meeting-confirm", *_MEETING_ARGS, "--confirmation-id", cid], monkeypatch)

    assert rc == 0
    requests = httpx_mock.get_requests()
    assert len(requests) == 1 and requests[0].method == "POST"
    assert write_sanction.read_state("create_meeting").remaining == 2


def test_confirm_without_confirmation_id_refuses(httpx_mock: HTTPXMock, monkeypatch):
    _grant("create_meeting")

    rc = _run(["create-meeting-confirm", *_MEETING_ARGS], monkeypatch)

    assert rc == 44
    assert httpx_mock.get_requests() == []


def test_confirm_refuses_when_body_changed_after_preview(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """Подмена тела между предпросмотром и записью: пишется показанное или ничего."""
    _grant("create_meeting")
    cid = _preview_id("create-meeting-preview", _MEETING_ARGS, monkeypatch, capsys)
    tampered = [*_MEETING_ARGS]
    tampered[tampered.index("--subject") + 1] = "Другая встреча"

    rc = _run(["create-meeting-confirm", *tampered, "--confirmation-id", cid], monkeypatch)

    assert rc == 44
    assert httpx_mock.get_requests() == []


def test_confirm_with_expired_sanction_returns_41(httpx_mock: HTTPXMock, monkeypatch, capsys):
    from datetime import datetime, timedelta, timezone

    _grant("create_meeting", hours=1, now=datetime.now(timezone.utc) - timedelta(hours=2))
    cid = _preview_id("create-meeting-preview", _MEETING_ARGS, monkeypatch, capsys)

    rc = _run(["create-meeting-confirm", *_MEETING_ARGS, "--confirmation-id", cid], monkeypatch)

    assert rc == 41
    assert httpx_mock.get_requests() == []


def test_confirm_with_exhausted_sanction_returns_42(httpx_mock: HTTPXMock, monkeypatch, capsys):
    from ktalk_mcp import write_sanction

    _grant("create_meeting", operations=1)
    write_sanction.consume("create_meeting")
    cid = _preview_id("create-meeting-preview", _MEETING_ARGS, monkeypatch, capsys)

    rc = _run(["create-meeting-confirm", *_MEETING_ARGS, "--confirmation-id", cid], monkeypatch)

    assert rc == 42
    assert httpx_mock.get_requests() == []


def test_revoke_takes_effect_on_next_attempt(httpx_mock: HTTPXMock, monkeypatch, capsys):
    from ktalk_mcp import write_sanction

    _grant("create_meeting")
    cid = _preview_id("create-meeting-preview", _MEETING_ARGS, monkeypatch, capsys)
    write_sanction.revoke("create_meeting")

    rc = _run(["create-meeting-confirm", *_MEETING_ARGS, "--confirmation-id", cid], monkeypatch)

    assert rc == 40
    assert httpx_mock.get_requests() == []


# --- FR-34: отмена, отдельный ключ ---------------------------------------------------------


def test_cancel_confirm_with_sanction_cancels_exactly_once(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    _grant("cancel_meeting")
    cid = _preview_id("cancel-meeting-preview", _CANCEL_ARGS, monkeypatch, capsys)
    httpx_mock.add_response(status_code=200, text="")

    rc = _run(["cancel-meeting-confirm", *_CANCEL_ARGS, "--confirmation-id", cid], monkeypatch)

    assert rc == 0
    assert len(httpx_mock.get_requests()) == 1


def test_create_sanction_does_not_authorize_cancel(httpx_mock: HTTPXMock, monkeypatch, capsys):
    _grant("create_meeting")
    cid = _preview_id("cancel-meeting-preview", _CANCEL_ARGS, monkeypatch, capsys)

    rc = _run(["cancel-meeting-confirm", *_CANCEL_ARGS, "--confirmation-id", cid], monkeypatch)

    assert rc == 40
    assert httpx_mock.get_requests() == []


# --- NFR-22: без автоповтора ---------------------------------------------------------------


def test_repeat_with_consumed_confirmation_id_refuses_exactly_one_post(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    _grant("create_meeting")
    cid = _preview_id("create-meeting-preview", _MEETING_ARGS, monkeypatch, capsys)
    httpx_mock.add_response(status_code=200, json={"id": "MEET-CREATED-0001"})

    argv = ["create-meeting-confirm", *_MEETING_ARGS, "--confirmation-id", cid]
    assert _run(argv, monkeypatch) == 0
    assert _run(argv, monkeypatch) == 44

    assert len(httpx_mock.get_requests()) == 1


def test_budget_is_consumed_on_unknown_outcome(httpx_mock: HTTPXMock, monkeypatch, capsys):
    """Списание до сетевой попытки: «попробовать ещё раз» не бесплатно даже для агента,
    решившего сделать это вопреки промту."""
    from ktalk_mcp import write_sanction

    _grant("create_meeting")
    cid = _preview_id("create-meeting-preview", _MEETING_ARGS, monkeypatch, capsys)
    httpx_mock.add_exception(httpx.ConnectError("сеть недоступна"))

    rc = _run(["create-meeting-confirm", *_MEETING_ARGS, "--confirmation-id", cid], monkeypatch)

    assert rc == 1
    assert write_sanction.read_state("create_meeting").remaining == 2


# --- ADR-016 §5: канал tty жив -------------------------------------------------------------


def test_tty_channel_works_without_sanction_and_logs_channel_tty(
    httpx_mock: HTTPXMock, monkeypatch
):
    import os
    import pty
    import sys

    from ktalk_mcp import write_journal, write_sanction

    master_fd, slave_fd = pty.openpty()
    monkeypatch.setattr(sys, "stdin", os.fdopen(os.dup(slave_fd), "r"))
    monkeypatch.setattr(sys, "stdout", os.fdopen(os.dup(slave_fd), "w"))
    os.write(master_fd, b"\xd0\xb4\xd0\xb0\n")
    httpx_mock.add_response(status_code=200, json={"id": "MEET-CREATED-0002"})

    try:
        rc = _run(["create-meeting-confirm", *_MEETING_ARGS], monkeypatch)
    finally:
        os.close(master_fd)
        os.close(slave_fd)

    assert rc == 0
    assert write_sanction.read_state("create_meeting").status == "absent"
    events = [
        json.loads(line)
        for line in write_journal.journal_path().read_text(encoding="utf-8").splitlines()
    ]
    assert {event["channel"] for event in events} == {"tty"}
