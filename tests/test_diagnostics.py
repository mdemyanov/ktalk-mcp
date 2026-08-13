"""AT-design: диагностика 401/403 (FR-5) и auth_status (FR-11).

Покрывает: FR-5 (AC-1, AC-2, AC-3) + карта scope->сообщение из ADR-003-spec (403 в
api-key называет scope, 403 в session — общее «доступ запрещён»); FR-11 (AC-1, AC-2,
AC-3) + все 4 сценария деградации auth_status из ADR-003-spec, плюс edge case «ошибка
сети не маскируется под мёртвый ключ».

Красные по замыслу: `KTalkScopeError`, mode-осведомлённый `_check_response`/`_classify`,
`client.get_auth_status()` — ничего из этого не реализовано в src/ktalk_mcp/client.py.

Примечание об импортах (для Dev): точные имена AuthStatus.alive/scopes/expired_at/note
взяты из ADR-003-auth-modes-spec.md (таблица деградации + фраза «AuthStatus.note всегда
объясняет...») — если Dev выберет другие имена полей, это точечная правка импорта/атрибута
в этом файле, сам сценарий и код ошибки остаются источником истины для AC.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture_json(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture
def base_url():
    return "https://test.ktalk.ru"


# --- FR-5: диагностика протухшего ключа/токена ------------------------------------------


async def test_ac_fr5_1_401_apikey_mentions_personal_api_key_var(httpx_mock: HTTPXMock, base_url):
    """AC FR-5/1: 401 в api-key-режиме с телом {errorId,errorType,errorCode,errorMessage}
    -> русскоязычное сообщение с указанием обновить KTALK_PERSONAL_API_KEY."""
    httpx_mock.add_response(status_code=401, json=_fixture_json("error-body-validation.json"))

    from ktalk_mcp.client import KTalkAuthError, KTalkClient

    async with KTalkClient(base_url=base_url, personal_api_key="pk-1") as client:
        with pytest.raises(KTalkAuthError, match="KTALK_PERSONAL_API_KEY"):
            await client.list_recordings()


async def test_ac_fr5_1b_403_apikey_names_missing_scope(httpx_mock: HTTPXMock, base_url):
    """Group B: 403 в api-key-режиме называет конкретный недостающий scope операции
    (тело в большинстве случаев пустое, зонд Ф-12 — диагностика не зависит от тела)."""
    httpx_mock.add_response(status_code=403, content=b"")

    from ktalk_mcp.client import KTalkClient, KTalkScopeError

    async with KTalkClient(base_url=base_url, personal_api_key="pk-1") as client:
        with pytest.raises(KTalkScopeError, match="application.recording.read"):
            await client.list_recordings()


async def test_ac_fr5_2_401_session_mentions_session_token_var(
    httpx_mock: HTTPXMock, base_url
):
    """AC FR-5/2: 401 в session-режиме -> сообщение указывает на KTALK_SESSION_TOKEN."""
    httpx_mock.add_response(status_code=401)

    from ktalk_mcp.client import KTalkAuthError, KTalkClient

    async with KTalkClient(base_url=base_url, session_token="sess-1") as client:
        with pytest.raises(KTalkAuthError, match="KTALK_SESSION_TOKEN"):
            await client.list_recordings()


async def test_ac_fr5_2b_403_session_generic_access_denied_no_scope_concept(
    httpx_mock: HTTPXMock, base_url
):
    """Group B: 403 в session-режиме — общее «доступ запрещён», не спутано со scope-
    диагнозом api-key (у сессии нет понятия scope)."""
    httpx_mock.add_response(status_code=403)

    from ktalk_mcp.client import KTalkAuthError, KTalkClient, KTalkScopeError

    async with KTalkClient(base_url=base_url, session_token="sess-1") as client:
        with pytest.raises(KTalkAuthError) as exc_info:
            await client.list_recordings()

    assert not isinstance(exc_info.value, KTalkScopeError)
    assert "scope" not in str(exc_info.value).lower()


async def test_ac_fr5_3_unparseable_error_body_still_readable_message(
    httpx_mock: HTTPXMock, base_url
):
    """AC FR-5/3: тело ошибки не парсится как JSON -> читаемое сообщение без сырого
    трейсбэка."""
    httpx_mock.add_response(status_code=401, content=b"<html>not json</html>")

    from ktalk_mcp.client import KTalkAuthError, KTalkClient

    async with KTalkClient(base_url=base_url, personal_api_key="pk-1") as client:
        with pytest.raises(KTalkAuthError) as exc_info:
            await client.list_recordings()

    text = str(exc_info.value)
    assert "Traceback" not in text
    assert "<html>" not in text


async def test_diagnostics_403_empty_body_does_not_break_classification(
    httpx_mock: HTTPXMock, base_url
):
    """Group B: тело 403 пустое (Content-Length: 0, зонд Ф-12) — диагностика по коду
    ответа + known required_scope операции, не по телу."""
    httpx_mock.add_response(status_code=403, content=b"")

    from ktalk_mcp.client import KTalkClient, KTalkScopeError

    async with KTalkClient(base_url=base_url, personal_api_key="pk-1") as client:
        with pytest.raises(KTalkScopeError):
            await client.get_transcript("REC-1")


# --- FR-11: диагностика токена/ключа (auth_status) --------------------------------------


async def test_ac_fr11_1_auth_status_apikey_full_scopes(httpx_mock: HTTPXMock, base_url):
    """AC FR-11/1: api-key-режим, access-info 200 -> живой запрос возвращает scopes[]
    и expiredAt, не локальное предположение."""
    httpx_mock.add_response(json=_fixture_json("access-info-full.json"))

    from ktalk_mcp.client import KTalkClient

    async with KTalkClient(base_url=base_url, personal_api_key="pk-1") as client:
        status = await client.get_auth_status()

    assert status.alive is True
    assert status.scopes is not None
    assert status.expired_at is not None
    request = httpx_mock.get_request()
    assert "access-info" in str(request.url)


async def test_auth_status_apikey_403_degrades_alive_true_scopes_none(
    httpx_mock: HTTPXMock, base_url
):
    """Сценарий деградации ADR-003-spec: access-info -> 403 значит «ключ жив, не хватает
    applications.read» — alive=True, scopes=None, а не «ключ мёртв»."""
    httpx_mock.add_response(status_code=403, content=b"")

    from ktalk_mcp.client import KTalkClient

    async with KTalkClient(base_url=base_url, personal_api_key="pk-1") as client:
        status = await client.get_auth_status()

    assert status.alive is True
    assert status.scopes is None
    assert status.note  # объясняет, почему scopes недоступны


async def test_auth_status_apikey_401_key_dead(httpx_mock: HTTPXMock, base_url):
    """Сценарий деградации ADR-003-spec: access-info -> 401 значит ключ мёртв."""
    httpx_mock.add_response(status_code=401)

    from ktalk_mcp.client import KTalkClient

    async with KTalkClient(base_url=base_url, personal_api_key="pk-1") as client:
        status = await client.get_auth_status()

    assert status.alive is False


async def test_ac_fr11_2_auth_status_apikey_expired_key_still_returns_result(
    httpx_mock: HTTPXMock, base_url
):
    """AC FR-11/2: ключ истёк -> access-info всё равно отдаёт результат (не исключение),
    спека утверждает эту особенность текстом (Ф-9/RES-001, находка 8)."""
    httpx_mock.add_response(json=_fixture_json("access-info-expired.json"))

    from ktalk_mcp.client import KTalkClient

    async with KTalkClient(base_url=base_url, personal_api_key="pk-1") as client:
        status = await client.get_auth_status()  # не должно поднимать исключение

    assert status.alive is True
    assert status.expired_at is not None


async def test_ac_fr11_3_auth_status_session_mode_real_probe_not_fake(
    httpx_mock: HTTPXMock, base_url
):
    """AC FR-11/3: session-режим -> честный ответ о том, что диагностика ограничена
    (нет понятия scope/expiredAt), но проверка — реальный сетевой запрос
    (list_recordings(top=1)), а не имитация без обращения к сети."""
    httpx_mock.add_response(json={"recordings": []})

    from ktalk_mcp.client import KTalkClient

    async with KTalkClient(base_url=base_url, session_token="sess-1") as client:
        status = await client.get_auth_status()

    assert status.alive is True
    assert status.scopes is None
    assert status.note  # явно объясняет отсутствие scope/expiredAt для сессии
    request = httpx_mock.get_request()
    assert request is not None
    assert "/api/recordings" in str(request.url)


async def test_auth_status_network_error_is_not_reported_as_dead_key(
    httpx_mock: HTTPXMock, base_url
):
    """Edge case ADR-003-spec: ошибка сети/таймаут при auth_status — отдельный класс
    отказа, не должна маскироваться под alive=False («ключ мёртв»)."""
    httpx_mock.add_exception(httpx.ConnectTimeout("simulated network timeout"))

    from ktalk_mcp.client import KTalkClient

    async with KTalkClient(base_url=base_url, personal_api_key="pk-1") as client:
        with pytest.raises(Exception):  # noqa: B017 — тип решает Dev, важно что это НЕ AuthStatus(alive=False)
            await client.get_auth_status()
