"""AT-design: FR-17 — чтение комнаты (`ktalk_mcp.rooms`, `ktalk_mcp.tools_rooms`).

Покрывает FR-17 AC-1 (маппер 18 полей — регрессионный guard на форму, официальная
проверка AC-1 сама по себе ручная, см. at-design.md), AC-3 (api-key-режим без
подтверждённого профиля отказывает до сети). AC-2 (несуществующее имя комнаты) —
формально заблокирована требованием (поведение сервера не проверено), но SA сузила
её до тестируемого решения (rooms-calendar-spec §4.2): любой не-2xx с рабочим
контрольным вызовом -> ContourDriftError, не «комната не найдена» — см. тест ниже.

Красные по замыслу: `ktalk_mcp.rooms`/`ktalk_mcp.tools_rooms` не существуют.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def base_url():
    return "https://test.ktalk.ru"


@pytest.fixture
def session_token():
    return "test-session-token"


@pytest.fixture
def personal_api_key():
    return "test-personal-api-key-0001"


ROOM_FIELD_NAMES = (
    "roomName",
    "sessionHalls",
    "stageConferenceId",
    "moderators",
    "anonymousModerators",
    "allowAnonymous",
    "anonymousAccessExpirationDate",
    "anonymousAccessModifiedDate",
    "audioPolicy",
    "videoPolicy",
    "screenSharePolicy",
    "isModerator",
    "conferenceId",
    "sipSettings",
    "onlineUsers",
    "simultaneousTranslation",
    "chatChannelSettings",
    "maskingSettings",
)


def test_room_fields_constant_has_18_documented_fields():
    from ktalk_mcp.rooms import ROOM_FIELDS

    assert len(ROOM_FIELDS) == 18
    assert set(ROOM_FIELDS) == set(ROOM_FIELD_NAMES)


def test_map_room_extracts_all_18_fields_from_live_probe_fixture():
    """AC FR-17/1 (форма): маппер отдаёт объект как минимум с 18 задокументированными
    живым зондом полями."""
    from ktalk_mcp.rooms import map_room

    raw = _fixture_json("room-detail-session.json")
    mapped = map_room(raw)

    for field in ROOM_FIELD_NAMES:
        assert field in mapped, f"поле {field} отсутствует в результате map_room"
    assert mapped["roomName"] == "test-room-alpha"
    assert mapped["moderators"] == ["synthetic-mod-1"]


def test_map_room_tolerates_missing_non_anchor_fields():
    """Поле вне якоря контракта, отсутствующее в ответе, не должно ронять маппер —
    отдаётся как None, а не KeyError."""
    from ktalk_mcp.rooms import map_room

    raw = {"roomName": "test-room-alpha"}
    mapped = map_room(raw)

    assert mapped["roomName"] == "test-room-alpha"
    assert mapped["sipSettings"] is None


def test_map_room_missing_anchor_field_raises_contour_drift():
    """Якорь контракта (`roomName`) отсутствует на коде 200 -> ContourDriftError,
    не KeyError/None молча (rooms-calendar-spec §4.1)."""
    from ktalk_mcp.contour_diagnostics import ContourDriftError
    from ktalk_mcp.rooms import map_room

    with pytest.raises(ContourDriftError):
        map_room({"sessionHalls": []})


async def test_ac_fr17_3_get_room_apikey_mode_refuses_before_network_call(
    httpx_mock: HTTPXMock, base_url, personal_api_key
):
    """AC FR-17/3: api-key-режим без подтверждённого профиля -> отказ до сетевого
    вызова, а не запрос вслепую (ADR-004 п.2: `AuthMode.API_KEY: None` для `get_room`)."""
    from ktalk_mcp.rooms import get_room

    from ktalk_mcp.client import KTalkClient, OperationNotAvailableError

    async with KTalkClient(base_url=base_url, personal_api_key=personal_api_key) as client:
        with pytest.raises(OperationNotAvailableError):
            await get_room(client, "test-room-alpha")

    assert httpx_mock.get_requests() == []


async def test_ac_fr17_1_get_room_session_mode_happy_path(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """Session-режим, комната существует -> объект с полным составом полей."""
    from ktalk_mcp.rooms import get_room

    from ktalk_mcp.client import KTalkClient

    httpx_mock.add_response(json=_fixture_json("room-detail-session.json"))

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        room = await get_room(client, "test-room-alpha")

    assert room["roomName"] == "test-room-alpha"
    request = httpx_mock.get_request()
    assert "/api/rooms/" in str(request.url)


async def test_get_room_any_non_2xx_with_working_control_raises_contour_drift_not_not_found(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """Сужение rooms-calendar-spec §4.2: у get_room нет каталога известных ошибок —
    ЛЮБОЙ отказ (в т.ч. гипотетический 404 для несуществующей комнаты), при рабочем
    контрольном вызове, даёт ContourDriftError, не тихую классификацию "комната не
    найдена" (которая замаскировала бы реальный дрейф контура тем же кодом)."""
    from ktalk_mcp.contour_diagnostics import ContourDriftError
    from ktalk_mcp.rooms import get_room

    from ktalk_mcp.client import KTalkClient

    httpx_mock.add_response(status_code=404)  # недокументированный путь: гипотетический 404
    httpx_mock.add_response(json={"recordings": []})  # control: list_recordings(top=1) -> 200

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        with pytest.raises(ContourDriftError):
            await get_room(client, "room-that-does-not-exist-synthetic")


async def test_ktalk_get_room_mcp_tool_registered_with_room_name_required():
    """`ktalk_get_room` — новый MCP-инструмент (NFR-6: аддитивен, не заменяет
    существующие)."""
    from ktalk_mcp.server import mcp

    tools = await mcp.list_tools()
    tools_by_name = {t.name: t for t in tools}

    assert "ktalk_get_room" in tools_by_name
    schema = tools_by_name["ktalk_get_room"].parameters
    assert set(schema.get("required", [])) == {"room_name"}
