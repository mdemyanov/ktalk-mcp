"""AT-design: NFR-17 — обнаружимость подмены транскрипта под конкуренцией
(`content/40-architecture/at-design-adr023-open-issues.md`, раздел «NFR-17»).

Покрывает 3 AC NFR-17 из `content/30-requirements/transcript-identity-observability.md`
(BA-014, вход RES-006) через `#### Scenario:` капабилити-спеки
`openspec/specs/recording-data-access/spec.md`, раздел «A transcript response's
recording identity is independently verifiable, not assumed from a successful call»:
- NFR17-AC1 — независимый признак сверки обнаруживает подмену (mismatch на
  расходящихся составах).
- NFR17-AC2 — признак не ложноположит на заведомо консистентном ответе (match).
- NFR17-AC3 — недоступность независимого источника отдаёт явный сигнал
  «не сверено» (`not_checked`), не тихое умолчание о совпадении; основной результат
  транскрипта возвращается в любом случае.

Решение SA, ПОПРАВЛЕННОЕ владельцем на gate-sa (ADR-023, ред. 2a2f6e3, НЕ 81b379a):
сверка ВКЛЮЧЕНА ПО УМОЛЧАНИЮ у `get-transcript`; флаг `--no-verify-identity` её
ОТКЛЮЧАЕТ. Более ранняя редакция (`--verify-identity` как opt-in) — отклонённый
вариант из Alternatives Considered, не действующее решение; тесты ниже проверяют
именно умолчание-включено, это самая вероятная точка регресса при реализации.

Четыре исхода (`transcript_identity.check_identity`, ADR-023-spec «Компоненты —
NFR-17»): `match` (пересечение непусто), `mismatch` (оба множества непусты и не
пересекаются), `inconclusive` (любое множество пусто — сравнивать не с чем),
`not_checked` (сам вызов `get_recording` упал — формируется на уровне оркестрации
`cmd_get_transcript`, не внутри `check_identity`).

Пирамида (контракт QA-author companion-спеки): match/mismatch/inconclusive — unit на
чистых функциях `transcript_identity.py`; not_checked/умолчание-включено/
`--no-verify-identity` — integration с моком транспорта `KTalkClient`, оркестрация
двух вызовов через `cmd_get_transcript`.

Красные по замыслу: модуль `ktalk_cli.transcript_identity` не существует вовсе
(`ModuleNotFoundError` внутри тела unit-тестов — собственная причина падения, не
опечатка и не общая ошибка коллекции файла: импорт — внутри каждой тест-функции,
как `test_enrichment.py`/`test_fr40_timezone_format.py`, тесты собираются
индивидуально). CLI не знает флага `--no-verify-identity` (`argparse` -> `SystemExit(2)`
— тоже собственная причина, не коллекция). CLI-оркестрационные тесты, не требующие
нового модуля/флага (умолчание-включено без флага), падают на явном `assert`
(второй сетевой вызов `get_recording` сегодня не происходит вовсе — `_cmd_get_transcript`
вызывает только `client.get_transcript`, `cli_content.py`).

Классы обязательного покрытия (контракт QA-author):
- **Испорченный/опечатанный ввод** — NFR17-malformed: `recording_key`, опечатанный
  пользователем, транскрипт которого сервер тем не менее отдаёт (RES-006: подмена
  не связана с валидностью самого запроса), но независимый источник (`get_recording`
  на тот же неверный/несуществующий ключ) отвечает `404` — специфическая форма
  недоступности источника (NFR17-AC3), отличная от сетевого сбоя.
- **Замаскированный отказ** — NFR17-AC3 и есть этот класс дословно: недоступность
  источника не должна тихо трактоваться как подтверждение соответствия. Отдельные
  усиленные тесты ниже проверяют явно: (а) поле `identity_check` не пропущено, (б)
  результат не «match» по умолчанию при отказе, (в) `--no-verify-identity` даёт
  ИМЕННО отсутствие второго вызова, а не тихий always-on второй вызов вопреки флагу.
"""

from __future__ import annotations

import json
import re

import httpx
import pytest
from pytest_httpx import HTTPXMock

BASE_URL = "https://test.ktalk.ru"


@pytest.fixture(autouse=True)
def _session_env(monkeypatch):
    monkeypatch.setenv("KTALK_BASE_URL", BASE_URL)
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "tok-nfr17")
    monkeypatch.delenv("KTALK_PERSONAL_API_KEY", raising=False)


def _run(argv, monkeypatch):
    from ktalk_cli.cli import main

    return main(["--db", "/nonexistent/path/does-not-exist/registry.db", *argv])


def _transcript_url_re(key: str) -> re.Pattern:
    return re.compile(rf"{re.escape(BASE_URL)}/api/recordings/{re.escape(key)}/transcript(\?.*)?$")


def _recording_url_re(key: str) -> re.Pattern:
    return re.compile(rf"{re.escape(BASE_URL)}/api/recordings/{re.escape(key)}(\?.*)?$")


# ============================================================================================
# Unit — transcript_identity.py (чистые функции, входы — фикстуры JSON)
# ============================================================================================


def _transcript(speaker_specs: list[dict | None]) -> dict:
    tracks = []
    for i, spec in enumerate(speaker_specs):
        tracks.append({"trackId": f"t{i}", "speaker": spec, "chunks": []})
    return {"status": "complete", "tracks": tracks}


def _recording(participant_specs: list[dict]) -> dict:
    return {"id": "REC-1", "participants": participant_specs}


def test_nfr17_ac1_check_identity_mismatch_on_disjoint_nonempty_sets():
    """NFR17-AC1: составы непусты и не пересекаются -> `mismatch` — сигнатура именно
    того искажения, что видит RES-006 («другой состав спикеров целиком»)."""
    from ktalk_cli.transcript_identity import check_identity

    transcript = _transcript(
        [
            {"userInfo": {"key": "u9"}, "isAnonymous": False},
            {"userInfo": {"key": "u10"}, "isAnonymous": False},
        ]
    )
    recording = _recording(
        [
            {"userInfo": {"key": "u1"}},
            {"userInfo": {"key": "u2"}},
        ]
    )

    result = check_identity(transcript, recording)

    assert result["result"] == "mismatch", (
        f"NFR17-AC1: составы {{'u9','u10'}} и {{'u1','u2'}} не пересекаются — ожидался "
        f"mismatch, получено {result}"
    )


def test_nfr17_ac2_check_identity_match_on_genuinely_overlapping_response():
    """NFR17-AC2: заведомо консистентный ответ (спикер транскрипта — подмножество
    участников записи) НЕ должен сигнализировать mismatch."""
    from ktalk_cli.transcript_identity import check_identity

    transcript = _transcript(
        [
            {"userInfo": {"key": "u1"}, "isAnonymous": False},
            {"userInfo": {"key": "u2"}, "isAnonymous": False},
        ]
    )
    recording = _recording(
        [
            {"userInfo": {"key": "u1"}},
            {"userInfo": {"key": "u2"}},
            {"userInfo": {"key": "u3"}},  # участник записи, не говоривший — не портит match
        ]
    )

    result = check_identity(transcript, recording)

    assert result["result"] == "match", (
        f"NFR17-AC2: пересечение {{'u1','u2'}} непусто — не должно быть mismatch, "
        f"получено {result}"
    )
    assert result["result"] != "mismatch"


def test_nfr17_boundary_check_identity_inconclusive_when_transcript_has_no_speakers():
    """Boundary (companion-спека «Edge cases»): пустой состав спикеров -> `inconclusive`,
    не `match` и не `mismatch` — сравнивать не с чем, это не совпадение."""
    from ktalk_cli.transcript_identity import check_identity

    transcript = _transcript([])
    recording = _recording([{"userInfo": {"key": "u1"}}])

    result = check_identity(transcript, recording)

    assert result["result"] == "inconclusive", (
        f"пустой состав спикеров транскрипта -> inconclusive, получено {result}"
    )


def test_nfr17_boundary_check_identity_inconclusive_when_recording_has_no_participants():
    from ktalk_cli.transcript_identity import check_identity

    transcript = _transcript([{"userInfo": {"key": "u1"}, "isAnonymous": False}])
    recording = _recording([])

    result = check_identity(transcript, recording)

    assert result["result"] == "inconclusive", (
        f"пустой состав участников записи -> inconclusive, получено {result}"
    )


def test_nfr17_boundary_check_identity_inconclusive_when_both_sets_empty():
    """Ловит наивную реализацию `not ts and not rp -> match` (два пустых множества
    формально «пересекаются» пустым пересечением, но это НЕ основание для match)."""
    from ktalk_cli.transcript_identity import check_identity

    transcript = _transcript([])
    recording = _recording([])

    result = check_identity(transcript, recording)

    assert result["result"] == "inconclusive"
    assert result["result"] != "match", (
        "оба множества пусты одновременно — не должно трактоваться как совпадение"
    )


def test_nfr17_boundary_speaker_identities_falls_back_to_diarized_speaker():
    """Companion-спека §«transcript_identity.py»: `speaker`, при отсутствии —
    `diarizedSpeaker` — не должен молча выбрасывать трек, где нет `speaker`, но есть
    диаризованный спикер."""
    from ktalk_cli.transcript_identity import speaker_identities

    transcript = {
        "status": "complete",
        "tracks": [
            {
                "trackId": "t0",
                "speaker": None,
                "diarizedSpeaker": {"userInfo": {"key": "u5"}, "isAnonymous": False},
                "chunks": [],
            },
        ],
    }

    identities = speaker_identities(transcript)

    assert "u5" in identities, (
        f"трек без `speaker`, но с `diarizedSpeaker` не должен теряться, "
        f"получено {identities}"
    )


def test_nfr17_boundary_speaker_identities_drops_track_without_any_speaker_info():
    """И `speaker`, и `diarizedSpeaker` отсутствуют -> трек не добавляет `None` в
    множество (набор из `{None}` — не легитимная идентичность, испортил бы
    сравнение любым другим `None`)."""
    from ktalk_cli.transcript_identity import speaker_identities

    transcript = {
        "status": "complete",
        "tracks": [{"trackId": "t0", "speaker": None, "chunks": []}],
    }

    identities = speaker_identities(transcript)

    assert None not in identities
    assert identities == set()


def test_nfr17_boundary_anonymous_participants_identified_by_anonymous_id():
    """Анонимный спикер/участник (без `userInfo`) всё равно даёт идентичность через
    `anonymousId` — иначе анонимные встречи были бы систематически `inconclusive`."""
    from ktalk_cli.transcript_identity import check_identity

    transcript = _transcript(
        [{"anonymousName": "Гость 1", "anonymousId": "anon-1", "isAnonymous": True}]
    )
    recording = _recording(
        [{"anonymousName": "Гость 1", "anonymousId": "anon-1", "isAnonymous": True}]
    )

    result = check_identity(transcript, recording)

    assert result["result"] == "match", (
        f"анонимный участник с общим anonymousId должен давать match, получено {result}"
    )


# ============================================================================================
# Integration — оркестрация `cmd_get_transcript` (умолчание-включено, ADR-023 поправка)
# ============================================================================================


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_nfr17_default_on_no_flag_calls_get_recording_and_adds_identity_check(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """Решение владельца (ADR-023, ред. 2a2f6e3): сверка включена БЕЗ флага — ни один
    флаг не передан, второй вызов `get_recording` обязан произойти сам."""
    key = "REC-1"
    httpx_mock.add_response(
        json={
            "status": "complete",
            "tracks": [{"speaker": {"userInfo": {"key": "u1"}, "isAnonymous": False}, "chunks": []}],
        },
        url=_transcript_url_re(key),
    )
    httpx_mock.add_response(
        json={"id": key, "participants": [{"userInfo": {"key": "u1"}}]},
        url=_recording_url_re(key),
    )

    rc = _run(["get-transcript", key, "--json"], monkeypatch)
    out = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert len(httpx_mock.get_requests()) == 2, (
        "NFR17 (умолчание-включено): без флага обязаны произойти ДВА сетевых вызова "
        f"(транскрипт + get_recording), фактически {len(httpx_mock.get_requests())}"
    )
    assert "identity_check" in out, (
        f"NFR17-AC1: ответ обязан нести `identity_check` по умолчанию, получено: {out}"
    )
    assert out["identity_check"]["result"] == "match"


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_nfr17_no_verify_identity_flag_skips_second_call_entirely(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """`--no-verify-identity` — единственный способ вернуться к нулевой цене (ADR-023
    §1, «Цена»): второй сетевой вызов не должен произойти вовсе, не только поле в
    выводе должно отсутствовать."""
    key = "REC-1"
    httpx_mock.add_response(
        json={"status": "complete", "tracks": []}, url=_transcript_url_re(key)
    )

    rc = _run(["get-transcript", key, "--json", "--no-verify-identity"], monkeypatch)
    out = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert len(httpx_mock.get_requests()) == 1, (
        "`--no-verify-identity`: обязан произойти РОВНО один сетевой вызов (только "
        f"транскрипт), фактически {len(httpx_mock.get_requests())}"
    )
    assert "identity_check" not in out, (
        f"`--no-verify-identity`: поле `identity_check` не должно появляться в ответе, "
        f"получено: {out}"
    )


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_nfr17_ac1_mismatch_surfaced_in_default_on_json_response(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """NFR17-AC1 буквально: конкурентная подмена (расходящиеся составы) -> потребитель
    получает наблюдаемый признак ПРЕЖДЕ, чем содержимое использовано дальше — признак
    доступен уже в самом `--json`-ответе `get-transcript`, не требует отдельного вызова."""
    key = "REC-1"
    httpx_mock.add_response(
        json={
            "status": "complete",
            "tracks": [
                {"speaker": {"userInfo": {"key": "u9"}, "isAnonymous": False}, "chunks": []},
            ],
        },
        url=_transcript_url_re(key),
    )
    httpx_mock.add_response(
        json={"id": key, "participants": [{"userInfo": {"key": "u1"}}]},
        url=_recording_url_re(key),
    )

    rc = _run(["get-transcript", key, "--json"], monkeypatch)
    out = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert out["identity_check"]["result"] == "mismatch", (
        f"NFR17-AC1: составы {{'u9'}} vs {{'u1'}} не пересекаются — ожидался mismatch "
        f"в самом --json ответе, получено {out.get('identity_check')}"
    )


# ============================================================================================
# Integration — NFR17-AC3: недоступность источника сверки
# ============================================================================================


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_nfr17_ac3_get_recording_network_failure_yields_not_checked_transcript_still_returned(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    key = "REC-1"
    httpx_mock.add_response(
        json={"status": "complete", "tracks": []}, url=_transcript_url_re(key)
    )
    httpx_mock.add_exception(
        httpx.ConnectError("connection refused"), url=_recording_url_re(key)
    )

    rc = _run(["get-transcript", key, "--json"], monkeypatch)
    out = json.loads(capsys.readouterr().out)

    assert rc == 0, (
        "NFR17-AC3: основной результат транскрипта обязан вернуться, даже если "
        "независимый источник сверки недоступен"
    )
    assert "transcript" in out or "status" in out, (
        f"NFR17-AC3: основное содержимое транскрипта не должно теряться, получено {out}"
    )
    identity_check = out.get("identity_check")
    assert identity_check is not None, (
        "NFR17-AC3 (замаскированный отказ): поле `identity_check` не должно быть "
        f"тихо пропущено при отказе источника, получен ответ: {out}"
    )
    assert identity_check["result"] == "not_checked", (
        f"NFR17-AC3: отказ get_recording обязан дать `not_checked`, получено {identity_check}"
    )
    assert identity_check["result"] != "match", (
        "NFR17-AC3 (замаскированный отказ): недоступность источника не должна тихо "
        "трактоваться как подтверждение соответствия"
    )


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_nfr17_malformed_mistyped_recording_key_get_recording_404_yields_not_checked(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """Класс «испорченный/опечатанный ввод»: пользователь опечатал `recording_key` —
    сам транскрипт сервер тем не менее отдаёт (RES-006 не связывает причину подмены с
    валидностью запроса), а независимый источник (`get_recording` на тот же неверный
    ключ) отвечает `404` — конкретно эта форма недоступности, отличная от общего
    сетевого сбоя выше, обязана давать тот же честный `not_checked`, не падение всей
    команды и не тихую отметку `match`."""
    key = "REC-TYPO-123"
    httpx_mock.add_response(
        json={"status": "complete", "tracks": []}, url=_transcript_url_re(key)
    )
    httpx_mock.add_response(status_code=404, json={}, url=_recording_url_re(key))

    rc = _run(["get-transcript", key, "--json"], monkeypatch)
    out = json.loads(capsys.readouterr().out)

    assert rc == 0
    identity_check = out.get("identity_check")
    assert identity_check is not None
    assert identity_check["result"] == "not_checked", (
        f"опечатанный recording_key -> get_recording 404 -> not_checked, получено "
        f"{identity_check}"
    )


# ============================================================================================
# Регресс — граница `--chunk` вне диапазона + умолчание-включено + `--json`
# ============================================================================================


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_nfr17_out_of_range_chunk_with_default_verify_does_not_crash_on_json_parse(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """Companion-спека, «Оркестрация», edge case: `render_transcript_output` при
    `--chunk N` вне диапазона отдаёт НЕСТРОГО-JSON текст ("Чанк N не существует...")
    — `json.loads` этого текста бросает исключение; наивная реализация обёртки
    `{"transcript": parsed, "identity_check": ...}` крашится на этом пути. Ожидание:
    команда не падает (`rc == 0`), сообщение о несуществующем чанке доходит до
    пользователя как есть."""
    key = "REC-1"
    httpx_mock.add_response(
        json={"status": "complete", "tracks": []}, url=_transcript_url_re(key)
    )
    httpx_mock.add_response(
        json={"id": key, "participants": []}, url=_recording_url_re(key)
    )

    rc = _run(
        ["get-transcript", key, "--json", "--chunk", "99", "--chunk-size", "10"], monkeypatch
    )
    raw = capsys.readouterr().out

    assert len(httpx_mock.get_requests()) == 2, (
        "NFR17 (edge case чанкинга, умолчание-включено): сверка обязана произойти "
        f"даже на этом пути (два вызова), фактически {len(httpx_mock.get_requests())}"
    )
    assert rc == 0, f"NFR17 (edge case чанкинга): команда не должна падать, stdout: {raw!r}"
    assert "не существует" in raw, (
        f"сообщение о несуществующем чанке должно дойти до пользователя как есть, "
        f"получено: {raw!r}"
    )
