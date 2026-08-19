"""AT-design: FR-40 — формат `--timezone` компоновщика (`ktalk_mcp.meeting_body`),
ADR-020 (`GMT[+-](0..14)`, класс ошибки `TimezoneFormatError`, отказ до сети/санкции).

Замер владельца (rooms-calendar-scheduling.md:357-368): единственная рабочая форма — `GMT+3`;
семь других (IANA, Windows ID, ISO-смещение, аббревиатура, минуты, RTZ-нотация,
человекочитаемое имя) отклонены сервером `CalendarTimeZoneParse`. Регулярка/диапазон
`GMT-14..GMT+14` и его регистрозависимость/обязательный знак — зафиксированы ADR-020-spec §1
(`_TIMEZONE_RE = re.compile(r"^GMT[+-](?:[0-9]|1[0-4])$")`) и её раздела «Edge cases»
(`gmt+3` отклоняется регистром, `GMT3` без знака отклоняется структурой регулярки) — не
свободный выбор этого файла.

Red by design: `TimezoneFormatError`/`_TIMEZONE_RE` не существуют в `meeting_body.py`,
`build_meeting_body` не проверяет форму `timezone`, `--help`/докстринг формат не называют.
Существующие `FULL_KWARGS` в `test_meeting_body.py`/`test_meeting_scheduling.py`/
`_MEETING_ARGS` в `test_cli_meeting*.py` используют `timezone="Europe/Moscow"` — после
реализации ADR-020 они станут красными по этому же дефекту; это дыра для Dev, не для
исправления здесь (владение этими файлами — не эта задача, см. CLAUDE.md «Куда класть
артефакты»/контракт QA-author: чужие тесты не трогать без изучения).
"""

from __future__ import annotations

import argparse
import inspect
import json

import pytest
from pytest_httpx import HTTPXMock

BAD_DB = "/nonexistent/path/does-not-exist/registry.db"

# Валидное тело за вычетом timezone — используем ЕДИНСТВЕННУЮ подтверждённую форму как базу,
# не `Europe/Moscow` (та форма сама по себе отклоняется этим же ADR — использовать её как
# "нейтральный" fixture было бы самопротиворечиво).
FULL_KWARGS = {
    "subject": "Синтетическая встреча",
    "start": "2026-08-20T10:00:00+03:00",
    "end": "2026-08-20T11:00:00+03:00",
    "timezone": "GMT+3",
    "room_name": "test-room-alpha",
    "required_attendee_keys": ["1001", "1002"],
    "description": "Синтетическое описание",
    "enable_auto_recording": True,
    "pin_code": "1234",
    "allow_anonymous": False,
}

# Семь форм замера владельца (rooms-calendar-scheduling.md:357-368), в порядке таблицы.
REJECTED_MEASURED_FORMS = [
    "Europe/Moscow",
    "Russian Standard Time",
    "+03:00",
    "MSK",
    "180",
    "RTZ 2 (MSK)",
    "(UTC+03:00) Москва, Санкт-Петербург",
]

_CLI_MEETING_ARGV = [
    "--subject",
    "Синтетическая встреча",
    "--start",
    "2026-08-20T10:00:00+03:00",
    "--end",
    "2026-08-20T11:00:00+03:00",
    "--room-name",
    "synthetic-room",
    "--required-attendee-key",
    "1001",
    "--enable-auto-recording",
    "true",
    "--no-pin-code",
    "--allow-anonymous",
    "false",
]


def _run(argv, monkeypatch, base_url="https://test.ktalk.ru"):
    monkeypatch.setenv("KTALK_BASE_URL", base_url)
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "sess-1")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)
    from ktalk_mcp.cli import main

    return main(["--db", BAD_DB, *argv])


# --- AC1: `GMT+3` принят, тело уходит без изменений -----------------------------------------


def test_ac1_gmt_plus_3_accepted_body_unchanged_snapshot():
    """AC FR-40/1: значение принимается и уходит в тело без изменений (снимок тела,
    не просто «не упало»)."""
    from ktalk_mcp.meeting_body import build_meeting_body

    body = build_meeting_body(**FULL_KWARGS)

    assert body["timezone"] == "GMT+3"
    # Снимок остального тела — проверка формы не мутирует прочие поля/не побочный эффект.
    assert body["subject"] == "Синтетическая встреча"
    assert body["roomName"] == "test-room-alpha"
    assert body["requiredAttendees"] == [
        {"type": "user", "key": "1001"},
        {"type": "user", "key": "1002"},
    ]


# --- AC2: семь отклонённых форм -> TimezoneFormatError до сети ------------------------------


@pytest.mark.parametrize("bad_timezone", REJECTED_MEASURED_FORMS)
def test_ac2_rejected_form_raises_timezoneformaterror_unit(bad_timezone):
    """AC FR-40/2, уровень чистой функции: каждая из семи отклонённых форм замера
    вызывает `TimezoneFormatError`, не пропускается в тело."""
    from ktalk_mcp.meeting_body import TimezoneFormatError, build_meeting_body

    kwargs = dict(FULL_KWARGS)
    kwargs["timezone"] = bad_timezone

    with pytest.raises(TimezoneFormatError):
        build_meeting_body(**kwargs)


@pytest.mark.parametrize("bad_timezone", REJECTED_MEASURED_FORMS)
def test_ac2_preview_surface_rejects_before_any_network_call(
    httpx_mock: HTTPXMock, monkeypatch, bad_timezone
):
    """AC FR-40/2, поверхность превью (`cli_meeting.py`): отказ до сети — подсчёт
    фактически отправленных запросов через `httpx_mock`, не чтение кода."""
    rc = _run(
        ["create-meeting-preview", *_CLI_MEETING_ARGV, "--timezone", bad_timezone],
        monkeypatch,
    )

    assert rc == 1
    assert httpx_mock.get_requests() == [], (
        "предпросмотр не должен делать сетевых запросов при неверном формате timezone, "
        f"фактически отправлено {len(httpx_mock.get_requests())}"
    )


@pytest.mark.parametrize("bad_timezone", REJECTED_MEASURED_FORMS)
def test_ac2_confirm_surface_rejects_before_any_network_call(
    httpx_mock: HTTPXMock, monkeypatch, bad_timezone
):
    """AC FR-40/2, поверхность подтверждения (`cli_meeting_confirm.py`): `build_meeting_body`
    вызывается внутри `preview(store)` раньше `_authorize`/сети — отказ по формату не требует
    ни санкции, ни валидного `--confirmation-id`, чтобы проявиться."""
    rc = _run(
        [
            "create-meeting-confirm",
            *_CLI_MEETING_ARGV,
            "--timezone",
            bad_timezone,
            "--confirmation-id",
            "irrelevant-never-reached",
        ],
        monkeypatch,
    )

    assert rc == 1
    assert httpx_mock.get_requests() == [], (
        "подтверждение не должно делать сетевых запросов при неверном формате timezone, "
        f"фактически отправлено {len(httpx_mock.get_requests())}"
    )


# --- AC3: бюджет санкции и confirmation_id не расходуются при отказе по формату -------------


def test_ac3_format_rejection_issues_no_confirmation_id():
    """AC FR-40/3: `PreviewService.preview` падает раньше `store.issue` — хранилище
    подтверждений остаётся пустым, id не выдан (проверка фактического состояния
    хранилища, не косвенный вывод по отсутствию исключения)."""
    from ktalk_mcp.confirmation import ConfirmationStore
    from ktalk_mcp.meeting_body import TimezoneFormatError
    from ktalk_mcp.meeting_scheduling import PreviewService

    store = ConfirmationStore()
    kwargs = dict(FULL_KWARGS)
    kwargs["timezone"] = "Europe/Moscow"

    with pytest.raises(TimezoneFormatError):
        PreviewService(store).preview(**kwargs)

    path = store.path
    records = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    assert records == {}, f"хранилище подтверждений не должно получить запись, получено: {records}"


def test_ac3_format_rejection_does_not_consume_write_sanction_budget(
    httpx_mock: HTTPXMock, monkeypatch
):
    """AC FR-40/3, санкционный канал (`cli_meeting_confirm.py`): отказ по формату
    происходит внутри `preview(store)`, раньше `_authorize`/`write_sanction.consume` —
    бюджет не тронут независимо от того, была ли санкция выдана вовсе. Проверяем
    фактический остаток бюджета до/после, не только код возврата."""
    from ktalk_mcp import write_sanction

    write_sanction.grant("create_meeting", hours=8, operations=3)
    remaining_before = write_sanction.read_state("create_meeting").remaining

    rc = _run(
        [
            "create-meeting-confirm",
            *_CLI_MEETING_ARGV,
            "--timezone",
            "Europe/Moscow",
            "--confirmation-id",
            "irrelevant-never-reached",
        ],
        monkeypatch,
    )

    remaining_after = write_sanction.read_state("create_meeting").remaining

    assert rc == 1
    assert httpx_mock.get_requests() == []
    assert remaining_after == remaining_before == 3, (
        f"бюджет санкции не должен списаться при отказе по формату timezone: "
        f"было {remaining_before}, стало {remaining_after}"
    )


# --- AC4: сообщение называет формат и пример, не сырой CalendarTimeZoneParse ----------------


def test_ac4_error_message_names_format_and_example_not_raw_server_text():
    """AC FR-40/4: текстовый снимок сообщения — требуемый формат (`GMT±N`) и
    единственный проверенный пример (`GMT+3`) присутствуют, сырой текст сервера
    `CalendarTimeZoneParse` отсутствует."""
    from ktalk_mcp.meeting_body import TimezoneFormatError, build_meeting_body

    kwargs = dict(FULL_KWARGS)
    kwargs["timezone"] = "Europe/Moscow"

    with pytest.raises(TimezoneFormatError) as exc_info:
        build_meeting_body(**kwargs)

    message = str(exc_info.value)
    assert "GMT" in message
    assert "GMT+3" in message
    assert "CalendarTimeZoneParse" not in message


# --- AC5: --help CLI и докстринг build_meeting_body называют формат явно --------------------


def test_ac5_cli_help_names_timezone_format():
    """AC FR-40/5: `--help` (через `parser.format_help()`, не чтение исходника
    `cli_meeting_args.py`) называет формат `GMT±N`/пример `GMT+3`."""
    from ktalk_mcp.cli_meeting_args import add_meeting_args

    parser = argparse.ArgumentParser()
    add_meeting_args(parser)

    help_text = parser.format_help()

    assert "GMT" in help_text
    assert "GMT+3" in help_text


def test_ac5_build_meeting_body_docstring_names_timezone_format():
    """AC FR-40/5: докстринг `build_meeting_body` (через `inspect.getdoc`, не чтение
    исходника) называет формат `GMT±N`/пример `GMT+3`."""
    from ktalk_mcp.meeting_body import build_meeting_body

    doc = inspect.getdoc(build_meeting_body) or ""

    assert "GMT" in doc
    assert "GMT+3" in doc


# --- Граница регулярки (ADR-020 §3, `^GMT[+-](?:[0-9]|1[0-4])$`) ----------------------------


@pytest.mark.parametrize("value", ["GMT+0", "GMT+14", "GMT-14"])
def test_boundary_regex_accepts_edge_of_declared_range(value):
    """Экстраполированная (не измеренная, ADR-020 §3) граница диапазона `0..14` на обеих
    сторонах знака принимается локальной проверкой — эта проверка ловит расхождение с
    регуляркой, не поведение сервера (сервер на этих значениях не замерялся)."""
    from ktalk_mcp.meeting_body import build_meeting_body

    kwargs = dict(FULL_KWARGS)
    kwargs["timezone"] = value

    body = build_meeting_body(**kwargs)
    assert body["timezone"] == value


@pytest.mark.parametrize(
    "value",
    ["GMT+15", "GMT+50", "GMT3", "gmt+3", ""],
    ids=["over-range-15", "over-range-50", "missing-sign", "lowercase", "empty-string"],
)
def test_boundary_regex_rejects_out_of_range_or_malformed(value):
    """Отклонённые формы: за пределами `0..14` (`GMT+15`, `GMT+50` — второе из issue,
    отклонённый вариант регулярки `0..99` пропустил бы), без знака (`GMT3`), в нижнем
    регистре (`gmt+3` — регулярка регистрозависима, ADR-020-spec §Edge cases) и пустая
    строка (не `None` — минует `MissingFieldError`, обязана дойти до проверки формы)."""
    from ktalk_mcp.meeting_body import TimezoneFormatError, build_meeting_body

    kwargs = dict(FULL_KWARGS)
    kwargs["timezone"] = value

    with pytest.raises(TimezoneFormatError):
        build_meeting_body(**kwargs)


def test_boundary_timezone_none_raises_missing_field_not_timezone_format():
    """ADR-020 §4/ADR-020-spec «Edge cases»: обязательность проверяется раньше формы —
    `timezone=None` обязана дать `MissingFieldError`, не `TimezoneFormatError`. Порядок
    проверок — решённый вопрос ADR (не открытый), тест фиксирует его как контракт."""
    from ktalk_mcp.meeting_body import MissingFieldError, build_meeting_body

    kwargs = dict(FULL_KWARGS)
    kwargs["timezone"] = None

    with pytest.raises(MissingFieldError):
        build_meeting_body(**kwargs)
