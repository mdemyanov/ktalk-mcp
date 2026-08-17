"""AT-design: FR-13 — оркестрация предпросмотра/создания (`ktalk_mcp.meeting_scheduling`).

Покрывает: предпросмотр не делает сетевых записей (ключевая AC волны — перехват
исходящих запросов, ноль записывающих вызовов), совпадение состава/значений полей
предпросмотра и реального тела создания, отсутствие авто-retry на сетевую ошибку
(ровно одна попытка записи), fail-closed api-key для `create_meeting` (NFR-7).

Красные по замыслу: `ktalk_mcp.meeting_scheduling` не существует.
"""

from __future__ import annotations

import inspect
import re

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
    from ktalk_mcp.client import KTalkClient
    from ktalk_mcp.meeting_scheduling import PreviewService, create_meeting

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


async def test_create_meeting_posts_to_api_calendar_path(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """ADR-007: путь с префиксом `/api` — согласован с `get_room`/`get_calendar`,
    прежняя запись без `/api` была ошибкой прочтения источника (mainpart), не
    намеренным решением."""
    from ktalk_mcp.client import KTalkClient
    from ktalk_mcp.meeting_scheduling import create_meeting

    httpx_mock.add_response(status_code=200, json={"id": "MEET-0001"})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        await create_meeting(client, {"subject": "X"})

    request = httpx_mock.get_request()
    assert request.url.path == "/api/calendar"


# --- AC-6: нет авто-retry на сетевую ошибку ---------------------------------------------


async def test_ac_fr13_6_network_failure_does_not_trigger_automatic_retry(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """AC FR-13/6: сетевая ошибка/таймаут при создании -> инструмент не повторяет
    сам POST автоматически — ровно один фактический вызов на запись. ADR-007 п.3
    добавляет один контрольный GET (диагностика), тоже проваливается -> исходная
    сетевая ошибка, не `ContourDriftError` (edge case контракта QA-author)."""
    from ktalk_mcp.client import KTalkClient
    from ktalk_mcp.meeting_scheduling import create_meeting

    httpx_mock.add_exception(
        httpx.ConnectError("connection refused"),
        url=re.compile(rf"^{re.escape(base_url)}/api/calendar(\?.*)?$"),
    )
    httpx_mock.add_exception(
        httpx.ConnectError("connection refused"),
        url=re.compile(rf"^{re.escape(base_url)}/api/recordings(\?.*)?$"),
    )

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        with pytest.raises(httpx.ConnectError):
            await create_meeting(client, {"subject": "X"})

    requests = httpx_mock.get_requests()
    assert len(requests) == 2
    assert requests[0].url.path == "/api/calendar"
    assert requests[1].url.path == "/api/recordings"


async def test_create_meeting_404_with_working_control_raises_contour_drift_error(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """Edge case контракта QA-author: POST /api/calendar -> 404, контроль
    list_recordings(top=1) -> 200 -> `ContourDriftError`, не `KTalkNotFoundError`
    (ADR-007 п.3)."""
    from ktalk_mcp.client import KTalkClient
    from ktalk_mcp.contour_diagnostics import ContourDriftError
    from ktalk_mcp.meeting_scheduling import create_meeting

    httpx_mock.add_response(
        status_code=404,
        text="not found",
        url=re.compile(rf"^{re.escape(base_url)}/api/calendar(\?.*)?$"),
    )
    httpx_mock.add_response(
        status_code=200,
        json={"recordings": []},
        url=re.compile(rf"^{re.escape(base_url)}/api/recordings(\?.*)?$"),
    )

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        with pytest.raises(ContourDriftError):
            await create_meeting(client, {"subject": "X"})


async def test_create_meeting_logs_4xx_body_without_changing_user_message(
    httpx_mock: HTTPXMock, base_url, session_token, caplog
):
    """Тело ответа на 4xx попадает в лог до классификации, само сообщение
    исключения (`KTalkNotFoundError`) не меняется — лог дополняет, не заменяет
    (ADR-007 п.3)."""
    import logging

    from ktalk_mcp.client import KTalkClient, KTalkNotFoundError
    from ktalk_mcp.meeting_scheduling import create_meeting

    httpx_mock.add_response(
        status_code=404,
        text="устройство роутинга: путь не смаршрутизирован",
        url=re.compile(rf"^{re.escape(base_url)}/api/calendar(\?.*)?$"),
    )
    httpx_mock.add_response(
        status_code=500,
        url=re.compile(rf"^{re.escape(base_url)}/api/recordings(\?.*)?$"),
    )

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        with caplog.at_level(logging.WARNING):
            with pytest.raises(KTalkNotFoundError) as exc_info:
                await create_meeting(client, {"subject": "X"})

    assert str(exc_info.value) == "Ресурс не найден."
    assert "устройство роутинга: путь не смаршрутизирован" in caplog.text


# --- ADR-008: заголовок Authorization на мутирующей операции session-режима ------------


async def test_adr008_create_meeting_sends_authorization_header_additively(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """ADR-008 §1: `mutating=True` -> заголовок `Authorization: Session <token>`
    отправляется ДОПОЛНИТЕЛЬНО к query-параметру `sessionToken`, не вместо него."""
    from ktalk_mcp.client import KTalkClient
    from ktalk_mcp.meeting_scheduling import create_meeting

    httpx_mock.add_response(status_code=200, json={"id": "MEET-0001"})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        await create_meeting(client, {"subject": "X"})

    request = httpx_mock.get_request()
    assert request.headers.get("Authorization") == f"Session {session_token}"
    assert request.url.params.get("sessionToken") == session_token


async def test_adr008_401_with_working_control_raises_write_auth_mismatch_not_contour_drift(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """ADR-008: POST /api/calendar -> 401, контроль list_recordings(top=1) -> 200 —
    `KTalkWriteAuthMismatchError`, не `ContourDriftError` (правка ADR-007 п.3)."""
    from ktalk_mcp.client import KTalkClient, KTalkWriteAuthMismatchError
    from ktalk_mcp.meeting_scheduling import create_meeting

    httpx_mock.add_response(
        status_code=401,
        text="токен невалиден для этого пути",
        url=re.compile(rf"^{re.escape(base_url)}/api/calendar(\?.*)?$"),
    )
    httpx_mock.add_response(
        status_code=200,
        json={"recordings": []},
        url=re.compile(rf"^{re.escape(base_url)}/api/recordings(\?.*)?$"),
    )

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        with pytest.raises(KTalkWriteAuthMismatchError) as exc_info:
            await create_meeting(client, {"subject": "X"})

    assert exc_info.value.response_body == "токен невалиден для этого пути"
    assert session_token not in str(exc_info.value)


async def test_dev007_control_call_does_not_inherit_cookie_from_failed_post(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """DEV-007: `client.list_recordings(top=1)` (контроль ADR-004) обязан быть
    независим от отказа, который он проверяет. `httpx.AsyncClient` без явной
    зачистки копит `Set-Cookie` между запросами одного инстанса — POST на
    `/api/calendar`, вернувший 401 вместе с cookie, поставил бы под сомнение
    независимость контроля, если бы эта cookie улетела в следующий GET на том же
    клиенте. Ровно этим объяснялась воспроизведённая расходимость: `auth-status`
    (свежий клиент, без cookie) видел `alive: True`, а контроль внутри уже
    отработавшего клиента иногда — нет."""
    from ktalk_mcp.client import KTalkClient, KTalkWriteAuthMismatchError
    from ktalk_mcp.meeting_scheduling import create_meeting

    httpx_mock.add_response(
        status_code=401,
        headers={"Set-Cookie": "sid=stale-web-session; Path=/"},
        text="",
        url=re.compile(rf"^{re.escape(base_url)}/api/calendar(\?.*)?$"),
    )
    httpx_mock.add_response(
        status_code=200,
        json={"recordings": []},
        url=re.compile(rf"^{re.escape(base_url)}/api/recordings(\?.*)?$"),
    )

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        with pytest.raises(KTalkWriteAuthMismatchError):
            await create_meeting(client, {"subject": "X"})

    requests = httpx_mock.get_requests()
    control_request = next(r for r in requests if r.url.path == "/api/recordings")
    assert "cookie" not in control_request.headers


# --- NFR-7: fail-closed api-key ----------------------------------------------------------


async def test_nfr7_create_meeting_apikey_mode_refuses_before_network_call(
    httpx_mock: HTTPXMock, base_url, personal_api_key
):
    """`create_meeting`/api-key не проверено вовсе ни одним сигналом -> отказ до
    сети, тот же принцип, что `get_room`/api-key."""
    from ktalk_mcp.client import KTalkClient, OperationNotAvailableError
    from ktalk_mcp.meeting_scheduling import create_meeting

    async with KTalkClient(base_url=base_url, personal_api_key=personal_api_key) as client:
        with pytest.raises(OperationNotAvailableError):
            await create_meeting(client, {"subject": "X"})

    assert httpx_mock.get_requests() == []
