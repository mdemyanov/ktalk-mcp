"""AT-design: корреляционная диагностика недокументированного контура (ADR-004, §3
rooms-calendar-spec.md).

Покрывает: `diagnose_undocumented_failure` (комбинаторная матрица недокументированный
ответ x контрольный ответ — ADR-004-spec «Слои проверки»/«Контракт с QA-author»),
`ContourDriftError`, `require_contract_field`. Не покрывает FR-17/FR-18/FR-13 напрямую
(их собственные модули покрывают `test_rooms.py`/`test_calendar.py`/
`test_meeting_scheduling.py`) — здесь только сам переиспользуемый механизм.

Контрольная операция для обоих режимов — `list_recordings(top=1)` (rooms-calendar-spec
§3, отступление от иллюстративного примера ADR-004-spec).

Красные по замыслу: `ktalk_cli.contour_diagnostics` не существует.
"""

from __future__ import annotations

import httpx
import pytest
from pytest_httpx import HTTPXMock


@pytest.fixture
def base_url():
    return "https://test.ktalk.ru"


@pytest.fixture
def session_token():
    return "test-session-token"


# --- ContourDriftError / require_contract_field (чистые, без сети) --------------------


def test_require_contract_field_missing_anchor_raises_contour_drift():
    """200 с телом, из которого пропало поле-якорь контракта -> ContourDriftError,
    не KeyError/None (ADR-004 «Механизм детекции» — деградация формы на коде 200)."""
    from ktalk_cli.contour_diagnostics import ContourDriftError, require_contract_field

    with pytest.raises(ContourDriftError):
        require_contract_field({"foo": "bar"}, "roomName", "get_room")


def test_require_contract_field_present_field_does_not_raise():
    from ktalk_cli.contour_diagnostics import require_contract_field

    require_contract_field({"roomName": "test-room-alpha"}, "roomName", "get_room")


def test_contour_drift_error_is_a_ktalk_error():
    """ContourDriftError — подкласс KTalkError (наследует обработку/маскирование
    ошибок CLI/MCP, не отдельная иерархия)."""
    from ktalk_cli.client import KTalkError
    from ktalk_cli.contour_diagnostics import ContourDriftError

    assert issubclass(ContourDriftError, KTalkError)


# --- Комбинаторная матрица diagnose_undocumented_failure (ADR-004-spec) ---------------


async def test_diag_404_undocumented_control_200_raises_contour_drift(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """недок=404 / контроль=200 -> контрольная операция в порядке, сбой локализован в
    недокументированном пути -> ContourDriftError."""
    from ktalk_cli.client import KTalkClient, KTalkNotFoundError
    from ktalk_cli.contour_diagnostics import ContourDriftError, diagnose_undocumented_failure

    httpx_mock.add_response(json={"recordings": []})  # control: list_recordings(top=1)

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        original = KTalkNotFoundError("Ресурс не найден.")
        with pytest.raises(ContourDriftError):
            await diagnose_undocumented_failure(client, "get_room", original)


async def test_diag_401_undocumented_control_401_reraises_original(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """недок=401 / контроль=401 -> контроль тоже провалился, это не дрейф контура,
    исходная ошибка перевыбрасывается как есть."""
    from ktalk_cli.client import KTalkAuthError, KTalkClient
    from ktalk_cli.contour_diagnostics import diagnose_undocumented_failure

    httpx_mock.add_response(status_code=401)  # control также 401

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        original = KTalkAuthError("Токен сессии истёк или невалиден.")
        with pytest.raises(KTalkAuthError) as exc_info:
            await diagnose_undocumented_failure(client, "get_calendar", original)
        assert exc_info.value is original


async def test_diag_403_undocumented_control_403_reraises_original(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """недок=403 / контроль=403 -> тот же принцип, что 401/401."""
    from ktalk_cli.client import KTalkAuthError, KTalkClient
    from ktalk_cli.contour_diagnostics import diagnose_undocumented_failure

    httpx_mock.add_response(status_code=403)

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        original = KTalkAuthError("Доступ запрещён: у текущей сессии нет прав на эту операцию.")
        with pytest.raises(KTalkAuthError) as exc_info:
            await diagnose_undocumented_failure(client, "get_calendar", original)
        assert exc_info.value is original


# --- DEV-008: исход контрольного вызова, когда он ТОЖЕ падает, не должен теряться -----


async def test_diag_401_control_also_401_attaches_control_probe_with_class_code_text(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """DEV-008: контроль тоже провалился -> на перевыброшенном исключении должен
    появиться атрибут с исходом контроля (класс/HTTP-код/текст), а не тишина —
    ровно то слепое пятно, что стоило четырёх боевых POST подряд."""
    from ktalk_cli.client import KTalkAuthError, KTalkClient
    from ktalk_cli.contour_diagnostics import diagnose_undocumented_failure

    httpx_mock.add_response(status_code=401)  # control также 401

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        original = KTalkAuthError("Токен сессии истёк или невалиден.")
        with pytest.raises(KTalkAuthError) as exc_info:
            await diagnose_undocumented_failure(client, "create_meeting", original)

    probe = exc_info.value.control_probe
    assert "list_recordings" in probe
    assert "KTalkAuthError" in probe
    assert "HTTP 401" in probe


async def test_diag_403_control_also_403_attaches_control_probe_with_class_code_text(
    httpx_mock: HTTPXMock, base_url, session_token
):
    from ktalk_cli.client import KTalkAuthError, KTalkClient
    from ktalk_cli.contour_diagnostics import diagnose_undocumented_failure

    httpx_mock.add_response(status_code=403)

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        original = KTalkAuthError("Доступ запрещён: у текущей сессии нет прав на эту операцию.")
        with pytest.raises(KTalkAuthError) as exc_info:
            await diagnose_undocumented_failure(client, "create_meeting", original)

    probe = exc_info.value.control_probe
    assert "list_recordings" in probe
    assert "KTalkAuthError" in probe
    assert "HTTP 403" in probe


async def test_diag_network_error_control_also_network_error_attaches_control_probe(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """Контроль падает не HTTP-кодом, а сетевой ошибкой -> явно «без HTTP-кода», не
    молчание и не выдуманный код."""
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.contour_diagnostics import diagnose_undocumented_failure

    httpx_mock.add_exception(httpx.ConnectError("connection refused"))

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        original = httpx.ConnectError("connection refused")
        with pytest.raises(httpx.ConnectError) as exc_info:
            await diagnose_undocumented_failure(client, "create_meeting", original)

    probe = exc_info.value.control_probe
    assert "ConnectError" in probe
    assert "без HTTP-кода" in probe


async def test_diag_unknown_400_undocumented_control_200_raises_contour_drift(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """недок=неизвестный 400 / контроль=200 -> ContourDriftError."""
    from ktalk_cli.client import KTalkClient, KTalkError
    from ktalk_cli.contour_diagnostics import ContourDriftError, diagnose_undocumented_failure

    httpx_mock.add_response(json={"recordings": []})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        original = KTalkError("Ошибка API Контур.Толк: HTTP 400.")
        with pytest.raises(ContourDriftError):
            await diagnose_undocumented_failure(client, "get_calendar", original)


async def test_diag_network_error_undocumented_control_200_raises_contour_drift(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """недок=сетевая ошибка / контроль=200 -> ContourDriftError (TRANSIENT_ERRORS
    включает httpx.HTTPError, не только KTalkError)."""
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.contour_diagnostics import ContourDriftError, diagnose_undocumented_failure

    httpx_mock.add_response(json={"recordings": []})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        original = httpx.ConnectError("connection refused")
        with pytest.raises(ContourDriftError):
            await diagnose_undocumented_failure(client, "get_room", original)


# --- ADR-008: KTalkWriteAuthMismatchError (401/403-session + контроль-200) -------------


async def test_diag_401_undocumented_control_200_raises_write_auth_mismatch(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """ADR-008: недок=401 / контроль=200 -> credential подтверждён рабочим в ту же
    секунду -> `KTalkWriteAuthMismatchError`, не `ContourDriftError`. Текст не советует
    обновить токен и называет операцию."""
    from ktalk_cli.client import KTalkAuthError, KTalkClient, KTalkWriteAuthMismatchError
    from ktalk_cli.contour_diagnostics import diagnose_undocumented_failure

    httpx_mock.add_response(json={"recordings": []})  # control: list_recordings(top=1)

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        original = KTalkAuthError("Токен сессии истёк или невалиден.")
        with pytest.raises(KTalkWriteAuthMismatchError) as exc_info:
            await diagnose_undocumented_failure(client, "create_meeting", original)

    text = str(exc_info.value)
    assert "create_meeting" in text
    assert "обновите токен" not in text.lower()
    assert "обновите ключ" not in text.lower()
    assert "обновлять" in text.lower()  # explicitly says updating is NOT the fix


async def test_diag_403_session_undocumented_control_200_raises_write_auth_mismatch(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """ADR-008: недок=403 session (без scope-контекста) / контроль=200 -> та же ветка —
    session-403 не является `KTalkScopeError` (подкласс только для api-key)."""
    from ktalk_cli.client import KTalkAuthError, KTalkClient, KTalkWriteAuthMismatchError
    from ktalk_cli.contour_diagnostics import diagnose_undocumented_failure

    httpx_mock.add_response(json={"recordings": []})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        original = KTalkAuthError("Доступ запрещён: у текущей сессии нет прав на эту операцию.")
        with pytest.raises(KTalkWriteAuthMismatchError):
            await diagnose_undocumented_failure(client, "create_meeting", original)


async def test_diag_403_scope_undocumented_control_200_raises_contour_drift_not_mismatch(
    httpx_mock: HTTPXMock, base_url
):
    """ADR-008: недок=403 api-key `KTalkScopeError` / контроль=200 -> ветка
    `KTalkWriteAuthMismatchError` не срабатывает (scope-ошибка исключена явно) —
    поведение как до ADR-008 (`ContourDriftError`), regression на уровне модуля
    (сценарий вне рамок `create_meeting`, где api-key fail-closed)."""
    from ktalk_cli.client import KTalkClient, KTalkScopeError, KTalkWriteAuthMismatchError
    from ktalk_cli.contour_diagnostics import ContourDriftError, diagnose_undocumented_failure

    httpx_mock.add_response(json={"recordings": []})

    async with KTalkClient(base_url=base_url, session_token="dummy-session") as client:
        original = KTalkScopeError(
            "Ключу не хватает разрешения «Записи» (application.recording.read)."
        )
        with pytest.raises(ContourDriftError) as exc_info:
            await diagnose_undocumented_failure(client, "get_transcript", original)

    assert not isinstance(exc_info.value, KTalkWriteAuthMismatchError)


async def test_write_auth_mismatch_error_is_subclass_of_ktalk_auth_error():
    """Обратная совместимость: `except KTalkAuthError` продолжает ловить новый класс."""
    from ktalk_cli.client import KTalkAuthError, KTalkWriteAuthMismatchError

    assert issubclass(KTalkWriteAuthMismatchError, KTalkAuthError)


async def test_response_body_attribute_transfers_through_correlation_to_write_auth_mismatch(
    httpx_mock: HTTPXMock, base_url, session_token
):
    """ADR-008 §3: `response_body`, прикреплённый к исходной ошибке до вызова
    `diagnose_undocumented_failure`, переносится на `KTalkWriteAuthMismatchError`."""
    from ktalk_cli.client import KTalkAuthError, KTalkClient, KTalkWriteAuthMismatchError
    from ktalk_cli.contour_diagnostics import diagnose_undocumented_failure

    httpx_mock.add_response(json={"recordings": []})

    async with KTalkClient(base_url=base_url, session_token=session_token) as client:
        original = KTalkAuthError("Токен сессии истёк или невалиден.")
        original.response_body = "тело ответа 401"
        with pytest.raises(KTalkWriteAuthMismatchError) as exc_info:
            await diagnose_undocumented_failure(client, "create_meeting", original)

    assert exc_info.value.response_body == "тело ответа 401"


async def test_diag_transient_errors_tuple_covers_ktalk_error_and_httpx_error():
    """TRANSIENT_ERRORS — публичная константа, используемая вызывающими модулями
    (`rooms.py`/`calendar_reader.py`) в `except TRANSIENT_ERRORS`."""
    from ktalk_cli.client import KTalkError
    from ktalk_cli.contour_diagnostics import TRANSIENT_ERRORS

    assert KTalkError in TRANSIENT_ERRORS
    assert httpx.HTTPError in TRANSIENT_ERRORS
