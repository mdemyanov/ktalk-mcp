import pytest
from pytest_httpx import HTTPXMock


@pytest.fixture
def base_url():
    return "https://test.ktalk.ru"


@pytest.fixture
def session_token():
    return "test-session-token"


async def test_list_recordings(httpx_mock: HTTPXMock, base_url, session_token):
    response_data = {"recordings": []}
    httpx_mock.add_response(json=response_data)

    from ktalk_mcp.client import KTalkClient

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        result = await client.list_recordings(top=30, order_mode="byTimeNewFirst")

    assert result == response_data
    request = httpx_mock.get_request()
    assert "sessionToken=test-session-token" in str(request.url)
    assert "/api/recordings?" in str(request.url)


async def test_list_recordings_with_filters(httpx_mock: HTTPXMock, base_url, session_token):
    response_data = {"recordings": []}
    httpx_mock.add_response(json=response_data)

    from ktalk_mcp.client import KTalkClient

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        result = await client.list_recordings(
            query="standup",
            start_from="2026-03-01T00:00:00",
            start_to="2026-04-01T00:00:00",
            top=10,
        )

    assert result == response_data
    request = httpx_mock.get_request()
    assert "query=standup" in str(request.url)
    assert "startFrom=2026-03-01" in str(request.url)


async def test_get_recording(httpx_mock: HTTPXMock, base_url, session_token):
    response_data = {"id": "rec-123", "title": "Test Recording"}
    httpx_mock.add_response(json=response_data)

    from ktalk_mcp.client import KTalkClient

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        result = await client.get_recording("rec-123")

    assert result == response_data
    request = httpx_mock.get_request()
    assert "/api/recordings/rec-123" in str(request.url)


async def test_get_transcript(httpx_mock: HTTPXMock, base_url, session_token):
    response_data = {"status": "complete", "tracks": []}
    httpx_mock.add_response(json=response_data)

    from ktalk_mcp.client import KTalkClient

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        result = await client.get_transcript("rec-123")

    assert result == response_data
    request = httpx_mock.get_request()
    assert "/api/recordings/rec-123/transcript" in str(request.url)


async def test_get_summary(httpx_mock: HTTPXMock, base_url, session_token):
    response_data = {
        "shortSummaryV2": {"status": "success", "chunks": []},
        "protocolV2": {"status": "success", "chunks": []},
        "transcriptionV2": {"status": "success", "tracks": []},
    }
    httpx_mock.add_response(json=response_data)

    from ktalk_mcp.client import KTalkClient

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        result = await client.get_summary("rec-123")

    assert result == response_data
    request = httpx_mock.get_request()
    assert "/api/recordings/v2/rec-123/summary" in str(request.url)


async def test_get_summary_by_type(httpx_mock: HTTPXMock, base_url, session_token):
    response_data = {"status": "success", "chunks": []}
    httpx_mock.add_response(json=response_data)

    from ktalk_mcp.client import KTalkClient

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        result = await client.get_summary_by_type("rec-123", "shortSummary")

    assert result == response_data
    request = httpx_mock.get_request()
    assert "/api/recordings/rec-123/summary/shortSummary" in str(request.url)


async def test_error_401(httpx_mock: HTTPXMock, base_url, session_token):
    httpx_mock.add_response(status_code=401, text="Unauthorized")

    from ktalk_mcp.client import KTalkAuthError, KTalkClient

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        with pytest.raises(KTalkAuthError, match="Токен сессии истёк"):
            await client.list_recordings()


async def test_error_403(httpx_mock: HTTPXMock, base_url, session_token):
    httpx_mock.add_response(status_code=403, text="Forbidden")

    from ktalk_mcp.client import KTalkAuthError, KTalkClient

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        with pytest.raises(KTalkAuthError, match="Токен сессии истёк"):
            await client.list_recordings()


async def test_error_404(httpx_mock: HTTPXMock, base_url, session_token):
    httpx_mock.add_response(status_code=404, text="Not Found")

    from ktalk_mcp.client import KTalkClient, KTalkNotFoundError

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        with pytest.raises(KTalkNotFoundError, match="не найден"):
            await client.get_recording("bad-key")
