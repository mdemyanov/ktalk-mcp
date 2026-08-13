"""AT-design: авторизация — селектор режима, заголовок/query, профиль эндпоинтов.

Покрывает AC из personal-api-key.md: FR-1 (AC-1, AC-2), FR-2 (AC-1, AC-2),
FR-3 (AC-2 — FR-3 AC-1 регрессия уже покрыта существующими test_client.py, не дублируется),
FR-6 (AC-1, AC-2, AC-3), NFR-2 (AC-1).

Красные по замыслу: `AuthMode`/`KTalkConfigError` в ktalk_mcp.config, `personal_api_key=`
у KTalkClient, `KTalkClient.from_settings`, `OPERATION_PROFILES`-диспетчер и
`OperationNotAvailableError` в ktalk_mcp.client — ничего из этого пока не реализовано.
"""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock


@pytest.fixture
def base_url():
    return "https://test.ktalk.ru"


@pytest.fixture
def session_token():
    return "test-session-token"


@pytest.fixture
def personal_api_key():
    return "test-personal-api-key-0001"


# --- FR-1: чтение ключа из окружения -------------------------------------------------


def test_ac_fr1_1_personal_api_key_available_when_set(monkeypatch):
    """AC FR-1/1: KTALK_PERSONAL_API_KEY задан -> доступен клиенту как персональный ключ."""
    monkeypatch.setenv("KTALK_PERSONAL_API_KEY", "pk-set-0001")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "")
    monkeypatch.delenv("KTALK_SESSION_TOKEN", raising=False)

    from ktalk_mcp.config import AuthMode, Settings

    settings = Settings()
    assert settings.ktalk_personal_api_key == "pk-set-0001"
    assert settings.auth_mode == AuthMode.API_KEY
    assert settings.auth_credential == "pk-set-0001"


def test_ac_fr1_2_personal_api_key_absent_no_error_at_load(monkeypatch):
    """AC FR-1/2: ключ отсутствует/пуст -> конфигурация грузится без ошибки, ключ = None."""
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-token-still-needed")

    from ktalk_mcp.config import Settings

    settings = Settings()  # не должно поднимать исключение
    assert settings.ktalk_personal_api_key is None


# --- FR-2: заголовок X-Auth-Token вместо sessionToken ---------------------------------


async def test_ac_fr2_1_apikey_request_has_header_no_query_param(
    httpx_mock: HTTPXMock, base_url, personal_api_key
):
    """AC FR-2/1: запрос несёт X-Auth-Token и НЕ несёт query-параметр sessionToken."""
    httpx_mock.add_response(json={"status": "complete", "tracks": []})

    from ktalk_mcp.client import KTalkClient

    async with KTalkClient(base_url=base_url, personal_api_key=personal_api_key) as client:
        await client.get_transcript("REC-1")

    request = httpx_mock.get_request()
    assert request.headers.get("X-Auth-Token") == personal_api_key
    assert "sessionToken" not in str(request.url)


async def test_ac_fr2_2_both_set_key_wins_session_never_sent(
    httpx_mock: HTTPXMock, base_url, personal_api_key
):
    """AC FR-2/2: оба env заданы -> используется только режим по ключу, sessionToken
    не появляется ни в query, ни где-либо в запросе (инвариант «взаимоисключение»)."""
    httpx_mock.add_response(json={"status": "complete", "tracks": []})

    from ktalk_mcp.client import KTalkClient

    async with KTalkClient(
        base_url=base_url, session_token="legacy-session-value", personal_api_key=personal_api_key
    ) as client:
        await client.get_transcript("REC-1")

    request = httpx_mock.get_request()
    assert request.headers.get("X-Auth-Token") == personal_api_key
    assert "sessionToken" not in str(request.url)
    assert "legacy-session-value" not in str(request.url)
    assert "legacy-session-value" not in str(request.headers)


async def test_from_settings_builds_apikey_transport(
    monkeypatch, httpx_mock: HTTPXMock, base_url, personal_api_key
):
    """KTalkClient.from_settings(settings) конфигурирует транспорт один раз по AuthContext
    (ADR-003 псевдокод _build_http_client) — заголовок присутствует на реальном запросе."""
    monkeypatch.setenv("KTALK_BASE_URL", base_url)
    monkeypatch.setenv("KTALK_PERSONAL_API_KEY", personal_api_key)
    monkeypatch.delenv("KTALK_SESSION_TOKEN", raising=False)

    from ktalk_mcp.client import KTalkClient
    from ktalk_mcp.config import Settings

    settings = Settings()
    httpx_mock.add_response(json={"status": "complete", "tracks": []})

    async with KTalkClient.from_settings(settings) as client:
        await client.get_transcript("REC-1")

    request = httpx_mock.get_request()
    assert request.headers.get("X-Auth-Token") == personal_api_key


# --- FR-3: обратная совместимость по умолчанию (только AC-2 — AC-1 см. test_client.py) ---


def test_ac_fr3_2_neither_set_raises_explicit_config_error_not_keyerror(monkeypatch):
    """AC FR-3/2: ни ключ, ни session-токен не заданы -> понятная ошибка конфигурации,
    не голый KeyError/AttributeError. Settings() сама по себе не падает (оба поля optional
    по ADR-003) — ошибка поднимается при обращении к .auth_mode."""
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    monkeypatch.delenv("KTALK_SESSION_TOKEN", raising=False)

    from ktalk_mcp.config import KTalkConfigError, Settings

    settings = Settings()
    with pytest.raises(KTalkConfigError):
        _ = settings.auth_mode


# --- FR-6: профиль эндпоинтов по режиму авторизации ------------------------------------


async def test_ac_fr6_1_session_mode_uses_internal_list_path(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """AC FR-6/1: session-режим -> список записей идёт по /api/recordings, не по Domain."""
    httpx_mock.add_response(json={"recordings": []})

    from ktalk_mcp.client import KTalkClient

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        await client.list_recordings()

    request = httpx_mock.get_request()
    assert "/api/recordings" in str(request.url)
    assert "/api/Domain" not in str(request.url)


async def test_ac_fr6_2_apikey_mode_uses_domain_v2_path(
    httpx_mock: HTTPXMock, base_url, personal_api_key
):
    """AC FR-6/2: api-key-режим -> список записей идёт по /api/Domain/recordings/v2."""
    httpx_mock.add_response(json={"entities": [], "nextPageToken": None, "prevPageToken": None})

    from ktalk_mcp.client import KTalkClient

    async with KTalkClient(base_url=base_url, personal_api_key=personal_api_key) as client:
        await client.list_recordings()

    request = httpx_mock.get_request()
    assert "/api/Domain/recordings/v2" in str(request.url)


async def test_ac_fr6_3_operation_without_profile_refuses_before_network_call(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """AC FR-6/3: операция из группы «аналога нет» (тут — архив) без активного ключа ->
    явное сообщение «доступна только в режиме персонального ключа», а не голый 401/403,
    и это решается ДО сети — httpx-мок не должен получить ни одного запроса."""
    from ktalk_mcp.client import KTalkClient, OperationNotAvailableError

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        with pytest.raises(OperationNotAvailableError):
            await client.list_archive(from_date="2026-01-01", to_date="2026-02-01")

    assert httpx_mock.get_requests() == []


# --- NFR-2: селектор режима протестирован на всех 4 комбинациях -----------------------


def test_ac_nfr2_priority_order_across_four_env_combinations(monkeypatch):
    """AC NFR-2: приоритет ключ -> сессия -> явная ошибка покрыт на всех 4 комбинациях
    присутствия/отсутствия KTALK_PERSONAL_API_KEY и KTALK_SESSION_TOKEN."""
    from ktalk_mcp.config import AuthMode, KTalkConfigError, Settings

    # 1. только ключ
    monkeypatch.setenv("KTALK_PERSONAL_API_KEY", "pk-1")
    monkeypatch.delenv("KTALK_SESSION_TOKEN", raising=False)
    assert Settings().auth_mode == AuthMode.API_KEY

    # 2. только сессия
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-1")
    assert Settings().auth_mode == AuthMode.SESSION

    # 3. оба заданы -> ключ побеждает
    monkeypatch.setenv("KTALK_PERSONAL_API_KEY", "pk-1")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-1")
    assert Settings().auth_mode == AuthMode.API_KEY

    # 4. ни один не задан -> явная ошибка
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    monkeypatch.delenv("KTALK_SESSION_TOKEN", raising=False)
    with pytest.raises(KTalkConfigError):
        _ = Settings().auth_mode
