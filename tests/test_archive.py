"""AT-design: архив встреч (FR-9), кроме AC-2 (см. test_pagination.py).

Покрывает: FR-9 AC-3 (session-режим без ключа -> явное сообщение "архив доступен только
в api-key-режиме", не голый 401, и это решается до сети). FR-9 AC-1 (окно дат + границы
пагинации 1-100 на боевом домене) и AC-4 (фильтр по комнатам) — ручная проверка на
боевом домене, см. at-design.md (архив как эндпоинт под ключом эмпирически не проверен —
Ф-11: ключ выдан без application.reporting.read).

Красные по замыслу: `KTalkClient.list_archive(...)` не существует.
"""

from __future__ import annotations

import pytest
from pytest_httpx import HTTPXMock


@pytest.fixture
def base_url():
    return "https://test.ktalk.ru"


async def test_ac_fr9_3_session_mode_archive_explicit_message_not_raw_401(
    httpx_mock: HTTPXMock, base_url
):
    """AC FR-9/3: session-режим (ключ не задан) -> пользователь получает явное сообщение
    о том, что архив доступен только в api-key-режиме, а не голый 401 — и это решается
    до сетевого вызова (httpx-мок не должен получить ни одного запроса)."""
    from ktalk_mcp.client import KTalkClient, OperationNotAvailableError

    async with KTalkClient(base_url=base_url, session_token="sess-1") as client:
        with pytest.raises(OperationNotAvailableError, match="архив"):
            await client.list_archive(from_date="2026-01-01", to_date="2026-02-01")

    assert httpx_mock.get_requests() == []
