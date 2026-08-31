"""AT-design: FR-39 — включительная правая граница окна чтения календаря
(`content/40-architecture/at-design-rooms-calendar.md`, раздел «FR-39»).

Покрывает 6 AC FR-39 из `content/30-requirements/rooms-calendar-scheduling.md`
(BA-009, волна 7): CLI `--start D --end D` (AC-1), окно шире 7 дней без потерь на стыках
сегментов (AC-3), три однодневных окна на начале/середине/конце диапазона (AC-4),
`start > end` отклоняется до сети (AC-5), честное «встреч нет» неотличимо кодом возврата
от отклонённого некорректного окна (AC-6, класс «замаскированный отказ»). AC-2 (паритет с
MCP `ktalk_list_calendar`) проверялся отдельным тестом — ADR-022 снимает MCP-слой целиком,
проверка удалена вместе с `server.py`; паритет по-прежнему верен (оба входа делят
`get_calendar_window`), просто у MCP-стороны больше нет входа для сравнения.

Мок сервера воспроизводит РЕАЛЬНУЮ полуоткрытость сервера (Ф-60 RES-004: `[start 00:00,
end 00:00)`, `end`-день никогда не включён) и реальные пороги (Ф-63: `(end-start).days<=7`,
Ф-64: `start>end` -> 400 буквальным текстом) — фильтрует фикстуры по датам ЗАПРОШЕННЫХ
`start`/`end`, а не отдаёт заготовленный список. Тест ловит любую реализацию, которая не
компенсирует полуоткрытость (текущий код), а не только конкретную форму фикса.

Красные по замыслу: дефект уже есть в `calendar_reader.py`/`cli_meetings_read.py`/
`tools_meetings.py` сегодня (не отсутствующий код) — стабы падают на `assert`, не на
импорте. Реализация фикса — DEV-013 (после ADR-017 SA).
"""

from __future__ import annotations

import json
from datetime import date

import httpx
import pytest
from pytest_httpx import HTTPXMock


# --- честный мок сервера: фильтрует по [start 00:00, end 00:00), не заготовка --------------


def _item(item_id: str, day: date) -> dict:
    return {
        "id": item_id,
        "roomName": "test-room-alpha",
        "start": f"{day.isoformat()}T10:00:00+03:00",
        "subject": "Синт.",
    }


def _honest_calendar_callback(events: list[tuple[str, date]]):
    """events: (id, день) — сервер отдаёт элемент, только если его день лежит в
    [start 00:00, end 00:00) РЕАЛЬНО запрошенных параметров (Ф-60), не заранее."""

    def callback(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        start_raw = params.get("start")
        end_raw = params.get("end")
        if start_raw is None or end_raw is None:
            return httpx.Response(400, text="Дата начала является обязательной для заполнения")
        start_d = date.fromisoformat(start_raw[:10])
        end_d = date.fromisoformat(end_raw[:10])
        if start_d > end_d:
            return httpx.Response(400, text="Дата окончания должна быть больше даты начала")
        if (end_d - start_d).days > 7:
            return httpx.Response(400, text="Период запроса не должен превышать 7 дней")
        items = [
            _item(item_id, day) for item_id, day in events if start_d <= day < end_d
        ]
        return httpx.Response(200, json={"items": items})

    return callback


def _mount_honest_mock(httpx_mock: HTTPXMock, events: list[tuple[str, date]]) -> None:
    httpx_mock.add_callback(_honest_calendar_callback(events), is_reusable=True)


def _run_cli(argv, monkeypatch, base_url="https://test.ktalk.ru", session_token="sess-fr39"):
    monkeypatch.setenv("KTALK_BASE_URL", base_url)
    monkeypatch.setenv("KTALK_SESSION_TOKEN", session_token)
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    from ktalk_cli.cli import main

    return main(["--db", "/nonexistent/path/does-not-exist/registry.db", *argv])


# === AC-1: CLI --start D --end D отдаёт встречи этого дня ==================================


def test_ac1_cli_single_day_window_returns_that_days_meetings(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    _mount_honest_mock(httpx_mock, [("E1", date(2026, 8, 17))])

    rc = _run_cli(
        ["list-calendar", "--start", "2026-08-17", "--end", "2026-08-17", "--json"], monkeypatch
    )
    captured = capsys.readouterr()

    assert rc == 0, f"неожиданный отказ: {captured.err}"
    data = json.loads(captured.out)
    ids = {i["id"] for i in data["items"]}
    assert ids == {"E1"}, (
        "AC-1: --start 2026-08-17 --end 2026-08-17 должен отдать встречу дня 17-го, "
        f"а получил {ids} — правая граница `end` уходит в сервер как исключающая "
        "(Ф-60 RES-004), день D никогда не попадает в [D 00:00, D 00:00)"
    )


# === AC-3: окно шире 7 дней — без потерь, включая стык сегментов ===========================


def test_ac3_wide_window_17_to_30_covers_every_day_no_loss_no_dup(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """17-30 августа: `split_window(17, 30, max_days=7)` режет на сегменты (17,23) и
    (24,30) сегодня. Оба правых края (23 и 30) уходят в сервер как исключающая
    граница -> оба дня молча теряются, не только правый край всего окна."""
    events = [(f"E{d}", date(2026, 8, d)) for d in range(17, 31)]  # E17..E30
    _mount_honest_mock(httpx_mock, events)

    rc = _run_cli(
        ["list-calendar", "--start", "2026-08-17", "--end", "2026-08-30", "--json"], monkeypatch
    )
    captured = capsys.readouterr()
    assert rc == 0, f"неожиданный отказ: {captured.err}"
    data = json.loads(captured.out)
    ids = [i["id"] for i in data["items"]]

    expected = {f"E{d}" for d in range(17, 31)}
    assert set(ids) == expected, (
        f"AC-3: окно 17-30 должно вернуть все 14 дней, получили {sorted(set(ids))}, "
        f"пропали {sorted(expected - set(ids))} — потери на стыке сегментов "
        "(`calendar_reader.py:56-68` инклюзивный `seg_end`) и на правом крае окна"
    )
    assert len(ids) == len(set(ids)), "AC-3: не должно быть дублей по id на стыках"


def test_ac3_stitch_boundary_day_23_not_lost_not_just_right_edge_day_30(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """Узкий прицельный тест на день 23-го — стык между сегментом (17,23) и (24,30).
    Изолирует «потерю на стыке» от «потери на правом крае всего окна» (день 30):
    фикс, чинящий только последний сегмент, здесь всё равно красный."""
    events = [("E23", date(2026, 8, 23)), ("E24", date(2026, 8, 24))]
    _mount_honest_mock(httpx_mock, events)

    rc = _run_cli(
        ["list-calendar", "--start", "2026-08-17", "--end", "2026-08-30", "--json"], monkeypatch
    )
    captured = capsys.readouterr()
    assert rc == 0, f"неожиданный отказ: {captured.err}"
    data = json.loads(captured.out)
    ids = {i["id"] for i in data["items"]}

    assert "E23" in ids, (
        "AC-3 (стык сегментов): 23-е число — правый край первого сегмента (17,23) и не "
        "покрывается вторым сегментом (24,30) — теряется молча, отдельно от потери "
        "правого края всего окна (30-е)"
    )


# === AC-4: три однодневных окна — начало/середина/конец диапазона ==========================


@pytest.mark.parametrize(
    "day, label",
    [
        (date(2026, 8, 17), "начало диапазона"),
        (date(2026, 8, 20), "середина диапазона"),
        (date(2026, 8, 23), "конец диапазона"),
    ],
)
def test_ac4_single_day_window_at_start_middle_end_returns_that_day(
    httpx_mock: HTTPXMock, monkeypatch, capsys, day, label
):
    events = [(f"E-{day.isoformat()}", day)]
    _mount_honest_mock(httpx_mock, events)

    rc = _run_cli(
        ["list-calendar", "--start", day.isoformat(), "--end", day.isoformat(), "--json"],
        monkeypatch,
    )
    captured = capsys.readouterr()
    assert rc == 0, f"неожиданный отказ ({label}): {captured.err}"
    data = json.loads(captured.out)
    ids = {i["id"] for i in data["items"]}

    assert ids == {f"E-{day.isoformat()}"}, (
        f"AC-4 ({label}, {day.isoformat()}): однодневное окно должно отдать встречу "
        f"этого дня, получили {ids}"
    )


# === AC-5: start > end отклоняется до сети, без пересказа сырого 400 =======================


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_ac5_start_after_end_rejected_before_network_call(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """`start > end` — испорченный ввод (перепутанные границы окна): инструмент обязан
    отказать сам, до сети, не переслав дословный текст сервера Ф-64."""
    _mount_honest_mock(httpx_mock, [])  # если дойдёт до сети — вернёт честный 400

    rc = _run_cli(
        ["list-calendar", "--start", "2026-08-20", "--end", "2026-08-17", "--json"], monkeypatch
    )
    captured = capsys.readouterr()

    assert rc != 0, "AC-5: start > end обязан завершаться кодом != 0"
    assert httpx_mock.get_requests() == [], (
        "AC-5: start > end должен отклоняться ДО сетевого запроса — "
        f"фактически отправлено {len(httpx_mock.get_requests())} запрос(ов)"
    )
    assert "Дата окончания должна быть больше даты начала" not in captured.err, (
        "AC-5: сообщение не должно быть сырым пересказом текста 400 сервера (Ф-64 RES-004), "
        f"а получено: {captured.err!r}"
    )


# === AC-6: честное «пусто» (код 0) и отклонённый ввод (код != 0) никогда не совпадают ======


def test_ac6_honest_empty_day_and_rejected_reversed_window_never_share_exit_code(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    # Честно пустой день (в фикстуре вообще нет событий) -> код 0, пустой items.
    _mount_honest_mock(httpx_mock, [])
    rc_empty = _run_cli(
        ["list-calendar", "--start", "2026-08-19", "--end", "2026-08-19", "--json"], monkeypatch
    )
    empty_captured = capsys.readouterr()
    assert rc_empty == 0
    assert json.loads(empty_captured.out)["items"] == []

    # Обратный интервал -> отклонён, код != 0.
    rc_invalid = _run_cli(
        ["list-calendar", "--start", "2026-08-20", "--end", "2026-08-19", "--json"], monkeypatch
    )
    invalid_captured = capsys.readouterr()
    assert rc_invalid != 0

    assert rc_empty != rc_invalid, (
        "AC-6: честное «встреч нет» и отклонённый некорректный ввод не должны делить код "
        f"возврата, получили одинаковый {rc_empty}"
    )


def test_ac6_masked_failure_day_with_real_events_must_not_report_as_honest_empty(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """Замаскированный отказ: день реально ИМЕЕТ встречу, но полуоткрытая граница
    отдаёт код 0 / items=[] — тот же исход, каким система честно докладывает «встреч
    нет». Наблюдающий (оператор/агент) не может различить эти два случая по коду
    возврата — ровно тот дефект, который FR-39 называет «код не различает»."""
    _mount_honest_mock(httpx_mock, [("E1", date(2026, 8, 19))])

    rc = _run_cli(
        ["list-calendar", "--start", "2026-08-19", "--end", "2026-08-19", "--json"], monkeypatch
    )
    captured = capsys.readouterr()
    assert rc == 0, f"неожиданный отказ: {captured.err}"
    data = json.loads(captured.out)

    assert data["items"] != [], (
        "AC-6 (замаскированный отказ): день 19-го реально содержит встречу E1, но выдача "
        "пуста при коде 0 — неотличимо от честного «встреч нет», хотя это молчаливая "
        "потеря дня на исключающей границе `end`, не факт об отсутствии встреч"
    )
