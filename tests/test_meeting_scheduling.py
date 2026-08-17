"""AT-design: FR-13 — оркестрация предпросмотра/создания (`ktalk_mcp.meeting_scheduling`).

Покрывает: предпросмотр не делает сетевых записей (ключевая AC волны — перехват
исходящих запросов, ноль записывающих вызовов), совпадение состава/значений полей
предпросмотра и реального тела создания, отсутствие авто-retry на сетевую ошибку
(ровно одна попытка записи), fail-closed api-key для `create_meeting` (NFR-7).

Красные по замыслу: `ktalk_mcp.meeting_scheduling` не существует.
"""

from __future__ import annotations

import inspect

import httpx
import pytest
from pytest_httpx import HTTPXMock

# Дублирует FULL_KWARGS из test_meeting_body.py осознанно: `tests/` не пакет
# (нет `__init__.py`), кросс-модульный импорт между stub-файлами ненадёжен.
FULL_KWARGS = {
    "subject": "Синтетическая встреча",
    "start": "2026-08-15T10:00:00+03:00",
    "end": "2026-08-15T11:00:00+03:00",
    "timezone": "Europe/Moscow",
    "room_name": "test-room-alpha",
    "required_user_keys": ["synthetic-user-1", "synthetic-user-2"],
    "description": "Синтетическое описание",
    "enable_auto_recording": True,
    "enable_sip": True,
    "pin_code": "1234",
    "allow_anonymous": False,
}


@pytest.fixture
def base_url():
    return "https://test.ktalk.ru"


@pytest.fixture
def session_token():
    return "test-session-token"


@pytest.fixture
def personal_api_key():
    return "test-personal-api-key-0001"


def _store():
    from ktalk_mcp.confirmation import ConfirmationStore

    return ConfirmationStore()


# --- Предпросмотр: ключевая AC волны — ноль сетевых записывающих вызовов ---------------


def test_preview_service_has_no_network_client_parameter():
    """`PreviewService.preview` физически не получает `KTalkClient` — структурная
    невозможность сетевого эффекта, не только поведенческая (ADR-005-spec §Компоненты)."""
    from ktalk_mcp.meeting_scheduling import PreviewService

    params = set(inspect.signature(PreviewService.preview).parameters) - {"self"}
    assert "client" not in params


def test_ac_fr13_1_preview_performs_zero_network_calls(httpx_mock: HTTPXMock):
    """AC FR-13/1: режим предпросмотра не выполняет ни одного сетевого запроса
    (POST/PUT/PATCH/DELETE и вообще никакого) к API Толка."""
    from ktalk_mcp.meeting_scheduling import PreviewService

    service = PreviewService(_store())
    body, confirmation_id = service.preview(**FULL_KWARGS)

    assert isinstance(body, dict)
    assert isinstance(confirmation_id, str)
    assert httpx_mock.get_requests() == []


# --- AC-2: предпросмотр и реальное создание дают одно и то же тело ---------------------


async def test_ac_fr13_2_preview_body_matches_body_sent_at_create(
    httpx_mock: HTTPXMock, base_url, session_token
):
    from ktalk_mcp.meeting_scheduling import PreviewService, create_meeting

    from ktalk_mcp.client import KTalkClient

    service = PreviewService(_store())
    body, _confirmation_id = service.preview(**FULL_KWARGS)

    httpx_mock.add_response(status_code=200, json={"id": "MEET-CREATED-0001"})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        await create_meeting(client, body)

    request = httpx_mock.get_request()
    assert request.method == "POST"
    import json as _json

    sent_body = _json.loads(request.content)
    assert sent_body == body


async def test_create_meeting_posts_to_calendar_path_without_api_prefix(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """Путь БЕЗ префикса `/api` (mainpart, Ф-38) — отличается от `get_room`/
    `get_calendar` намеренно, не опечатка."""
    from ktalk_mcp.meeting_scheduling import create_meeting

    from ktalk_mcp.client import KTalkClient

    httpx_mock.add_response(status_code=200, json={"id": "MEET-0001"})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        await create_meeting(client, {"subject": "X"})

    request = httpx_mock.get_request()
    assert request.url.path == "/calendar"


# --- AC-6: нет авто-retry на сетевую ошибку ---------------------------------------------


async def test_ac_fr13_6_network_failure_does_not_trigger_automatic_retry(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """AC FR-13/6: сетевая ошибка/таймаут при создании -> инструмент не повторяет
    запрос автоматически — ровно один фактически выполненный сетевой вызов на запись."""
    from ktalk_mcp.meeting_scheduling import create_meeting

    from ktalk_mcp.client import KTalkClient

    httpx_mock.add_exception(httpx.ConnectError("connection refused"))

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        with pytest.raises(Exception):  # noqa: B017 - конкретный класс решает Dev
            await create_meeting(client, {"subject": "X"})

    assert len(httpx_mock.get_requests()) == 1


# --- NFR-7: fail-closed api-key ----------------------------------------------------------


async def test_nfr7_create_meeting_apikey_mode_refuses_before_network_call(
    httpx_mock: HTTPXMock, base_url, personal_api_key
):
    """`create_meeting`/api-key не проверено вовсе ни одним сигналом -> отказ до
    сети, тот же принцип, что `get_room`/api-key."""
    from ktalk_mcp.meeting_scheduling import create_meeting

    from ktalk_mcp.client import KTalkClient, OperationNotAvailableError

    async with KTalkClient(base_url=base_url, personal_api_key=personal_api_key) as client:
        with pytest.raises(OperationNotAvailableError):
            await create_meeting(client, {"subject": "X"})

    assert httpx_mock.get_requests() == []
