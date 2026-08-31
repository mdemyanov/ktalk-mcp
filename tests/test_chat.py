"""AT-design: чат встречи (FR-10).

Покрывает: FR-10 AC-2 (без явного канала клиент сначала резолвит доступные каналы, не
падает с сырым 400 "The channel field is required" — зонд Ф-6), AC-4 (403 на конкретном
канале -> читаемое сообщение о нехватке прав именно на этот канал). FR-10 AC-1/AC-3
(session-режим с известным каналом; api-key-режим) — ручная проверка на боевом домене,
см. at-design.md.

Красные по замыслу: `KTalkClient.get_chat_messages(...)` не существует.
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


async def test_ac_fr10_2_missing_channel_resolves_available_channels_first(
    httpx_mock: HTTPXMock, base_url
):
    """AC FR-10/2: канал не указан явно -> клиент сначала определяет доступные каналы
    (из деталей встречи), а не падает с сырым 400 "The channel field is required"."""
    from ktalk_cli.client import KTalkClient

    httpx_mock.add_response(
        json={"key": "CONF-1", "artifacts": {"chatChannelHasMessages": {"general": True}}}
    )
    httpx_mock.add_response(json=_fixture_json("chat-messages-session.json"))

    async with KTalkClient(base_url=base_url, session_token="sess-1") as client:
        result = await client.get_chat_messages(conference_key="CONF-1")

    assert result
    requests = httpx_mock.get_requests()
    assert any("channel=general" in str(r.url) for r in requests)


async def test_get_chat_messages_resolves_conference_key_from_recording_key(
    httpx_mock: HTTPXMock, base_url
):
    """Оркестрация из client-modules-spec: recording_key -> резолв conferenceKey (мост
    Запись -> Встреча, зонд Ф-5) -> резолв канала -> сообщения."""
    from ktalk_cli.client import KTalkClient

    httpx_mock.add_response(json={"id": "REC-1", "conferenceKey": "CONF-1"})
    httpx_mock.add_response(
        json={"key": "CONF-1", "artifacts": {"chatChannelHasMessages": {"general": True}}}
    )
    httpx_mock.add_response(json=_fixture_json("chat-messages-session.json"))

    async with KTalkClient(base_url=base_url, session_token="sess-1") as client:
        result = await client.get_chat_messages(recording_key="REC-1")

    assert result


async def test_ac_fr10_4_forbidden_channel_gives_readable_permission_message(
    httpx_mock: HTTPXMock, base_url
):
    """AC FR-10/4: 403 с текстом "нет прав на получение сообщений чат-канала X" (зонд
    Ф-6) -> понятное сообщение о нехватке прав на конкретный канал."""
    from ktalk_cli.client import KTalkClient

    httpx_mock.add_response(
        status_code=403, text="У вас нет прав на получение сообщений чат-канала vip"
    )

    async with KTalkClient(base_url=base_url, session_token="sess-1") as client:
        with pytest.raises(Exception) as exc_info:
            await client.get_chat_messages(conference_key="CONF-1", channel="vip")

    text = str(exc_info.value)
    assert "vip" in text
    assert "прав" in text.lower()
