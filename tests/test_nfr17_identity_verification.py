"""AT-design: NFR-17 — обнаружимость подмены транскрипта под конкуренцией
(`content/40-architecture/at-design-adr023-open-issues.md`, раздел «NFR-17»;
волна 2 (ADR-024, Д1/Д3) — `content/40-architecture/at-design-adr024-open-issues-wave2.md`).

Покрывает 5 AC NFR-17 из `content/30-requirements/transcript-identity-observability.md`
(BA-014, вход RES-006) через `#### Scenario:` капабилити-спеки
`openspec/specs/recording-data-access/spec.md`, раздел «A transcript response's
recording identity is independently verifiable, not assumed from a successful call»:
- NFR17-AC1 — независимый признак сверки обнаруживает подмену (mismatch на
  расходящихся составах).
- NFR17-AC2 — признак не ложноположит на заведомо консистентном ответе (match).
- NFR17-AC3 — недоступность независимого источника отдаёт явный сигнал
  «не сверено» (`not_checked`), не тихое умолчание о совпадении; основной результат
  транскрипта возвращается в любом случае.
- NFR17-AC4 (ADR-024 Д1, issue #5, новый сценарий капабилити-спеки «A detected
  mismatch fails loudly, not silently») — `mismatch` обязан завершать `get-transcript`
  кодом возврата 3, отдельным от 0 (успех), 1 (отказ вызова) и 2 (usage error);
  тело ответа (`transcript`+`identity_check`) не пустеет. Причина исходной подмены
  этим НЕ устраняется (ADR-024 §Д1) — тест проверяет только громкость отказа.
- NFR17-AC5 (ADR-024 Д3, issue #9, новый сценарий «An out-of-range chunk request
  does not silently drop the verification signal») — `--chunk` вне диапазона
  обязан (а) не платить сетевым вызовом `get_recording` вовсе, (б) отдавать явный
  `identity_check.result == "not_checked"`, `reason == "chunk_out_of_range"` в
  валидном `--json`-конверте, отличимо от «сверка прошла и совпало».

ADR-024 Д2 (issue #8) не меняет код — устойчивость `anonymousId` подтверждена
измерением на живом контуре (companion-спека §2), не тестом; регрессия ключа
сравнения анонимов уже покрыта ниже
(`test_nfr17_boundary_anonymous_participants_identified_by_anonymous_id`).

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
- **NFR17-AC4 (Д1), испорченный ввод** — N/A, явно, не по умолчанию: `mismatch` —
  сигнатура серверной кросс-контаминации (RES-006), не опечатки `recording_key`.
  Опечатанный ключ, для которого сервер отдаёт СОГЛАСОВАННЫЙ (тот же неверный ключ)
  ответ и на транскрипт, и на `get_recording`, даёт `match` на СВОЁМ (чужом) составе,
  не `mismatch` — нет воспроизводимого триггера подмены со стороны клиентского ввода
  (ADR-024 §Д1: причина не локализована, тест на неё не проектируется).
- **NFR17-AC4 (Д1), замаскированный отказ** — это и есть самый предмет решения:
  до ADR-024 код возврата 0 на `mismatch` МАСКИРОВАЛ обнаруженное расхождение от
  потребителей, читающих только код (не тело ответа). `test_nfr17_ac4_…` проверяет
  явно, что маска снята: `rc == 3`, отдельно от 0/1/2.
- **NFR17-AC5 (Д3), испорченный ввод** — отрицательный номер чанка
  (`--chunk -1`) — не просто «вне диапазона», а структурно бессмысленное значение,
  которое пользователь мог ввести по опечатке; должно давать тот же исход
  (`not_checked`/`chunk_out_of_range`, ноль сетевых вызовов), не отдельную ветку.
- **NFR17-AC5 (Д3), замаскированный отказ** — до ADR-024 результат сверки на этой
  ветке ВЫЧИСЛЯЛСЯ (сетевой вызов оплачивался), но ТИХО терялся сборкой `--json`
  (`JSONDecodeError` -> печать как есть, без `identity_check`) — неотличимо от
  «сверка прошла успешно» на уровне общей формы ответа. Тесты проверяют явно:
  ноль вызовов `get_recording` (не просто «результат не виден») и присутствие
  структурированного `identity_check.reason == "chunk_out_of_range"` в JSON.
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


def _count_recording_calls(httpx_mock: HTTPXMock, key: str) -> int:
    """Число сетевых вызовов ИМЕННО `get_recording` (не транскрипта) — ADR-024 Д3
    требует ровно 0 на `--chunk` вне диапазона, не «меньше вызовов вообще»."""
    pattern = _recording_url_re(key)
    return sum(1 for req in httpx_mock.get_requests() if pattern.search(str(req.url)))


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
def test_nfr17_ac4_mismatch_exits_with_code_3_and_still_carries_full_body(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """NFR17-AC1+AC4 (ADR-024 Д1, issue #5): конкурентная подмена (расходящиеся
    составы) -> потребитель получает наблюдаемый признак ПРЕЖДЕ, чем содержимое
    использовано дальше (признак доступен уже в самом `--json`-ответе, AC1), И код
    возврата 3 — отдельный от 0/1/2 (AC4, ADR-024 Д1).

    ПРАВКА КОНТРАКТА (не регресс, не находка QA-runner): до ADR-024 этот же тест
    закреплял `assert rc == 0` на mismatch — ровно то тихое поведение, которое
    решение Д1 отменяет («отказ становится громким», не «гонка устранена» —
    ADR-024 §Д1 дословно). Старое утверждение: `assert rc == 0`. Новое: `assert
    rc == 3`. Причина исходной подмены (issue #5) этим НЕ локализована — тест не
    проверяет большего, чем громкость отказа."""
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

    assert out["identity_check"]["result"] == "mismatch", (
        f"NFR17-AC1: составы {{'u9'}} vs {{'u1'}} не пересекаются — ожидался mismatch "
        f"в самом --json ответе, получено {out.get('identity_check')}"
    )
    assert rc == 3, (
        "NFR17-AC4 (ADR-024 Д1, замаскированный отказ до правки): `mismatch` обязан "
        f"завершать команду кодом 3, отдельным от 0/1/2 — фактический код {rc}. "
        "Старый контракт (`rc == 0` даже на mismatch) отменён этим ADR — это НЕ "
        "регресс покрытия, а сознательная правка теста под новое решение."
    )
    assert rc not in (0, 1, 2), (
        f"NFR17-AC4: код 3 обязан быть отличим от успеха(0)/отказа вызова(1)/usage error(2), "
        f"получено {rc}"
    )
    assert out.get("transcript") is not None, (
        "NFR17-AC4 (замаскированный отказ): код 3 не должен опустошать тело ответа — "
        f"`transcript` обязан присутствовать целиком, получено {out}"
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
# NFR17-AC5 (ADR-024 Д3, issue #9) — `--chunk` вне диапазона: сверка не оплачивается,
# сигнал `not_checked`/`chunk_out_of_range` не теряется сборкой `--json`
# ============================================================================================


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_nfr17_ac5_out_of_range_chunk_with_default_verify_skips_network_call_and_signals_not_checked(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """ПРАВКА КОНТРАКТА (не регресс — ADR-024 Д3 отменяет прежнее поведение,
    называвшееся issue #9 недостаточным): старый тест
    (`test_nfr17_out_of_range_chunk_with_default_verify_does_not_crash_on_json_parse`)
    закреплял РОВНО ДВА сетевых вызова (транскрипт + `get_recording`) и печать
    НЕСТРОГО-JSON текста "Чанк N не существует..." как есть — то самое тихое
    выбрасывание уже вычисленного `identity_check`, которое Д3 устраняет. Старое
    утверждение: `len(httpx_mock.get_requests()) == 2` и `rc == 0` без проверки формы
    JSON. Новое: `get_recording` НЕ вызывается вовсе (0, не 2 вызова на сверку —
    сетевая цена не оплачивается на заведомо неверном чанке), а `--json`-вывод —
    валидный JSON с явным `identity_check.result == "not_checked"`,
    `reason == "chunk_out_of_range"`, отличимым от `match`."""
    key = "REC-1"
    httpx_mock.add_response(
        json={"status": "complete", "tracks": []}, url=_transcript_url_re(key)
    )
    # get_recording МОК присутствует специально: если реализация (сегодняшняя,
    # непочиненная) всё же вызовет его — вызов должен УСПЕШНО пройти и быть
    # засчитан `_count_recording_calls`, а не свалить тест сторонней ошибкой
    # pytest_httpx «нет зарегистрированного ответа».
    httpx_mock.add_response(
        json={"id": key, "participants": [{"userInfo": {"key": "u1"}}]},
        url=_recording_url_re(key),
    )

    rc = _run(
        ["get-transcript", key, "--json", "--chunk", "99", "--chunk-size", "10"], monkeypatch
    )
    raw = capsys.readouterr().out

    assert rc == 0, (
        f"NFR17-AC5: чанк вне диапазона — usage error нет, команда не должна "
        f"падать, stdout: {raw!r}"
    )
    assert _count_recording_calls(httpx_mock, key) == 0, (
        "NFR17-AC5 (ADR-024 Д3): `--chunk` вне диапазона НЕ должен запускать сверку "
        f"по сети вовсе — фактически вызовов get_recording: "
        f"{_count_recording_calls(httpx_mock, key)}"
    )

    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        pytest.fail(
            "NFR17-AC5 (замаскированный отказ до правки): `--json`-вывод на чанке "
            f"вне диапазона обязан быть валидным JSON-конвертом, а не нестрого-JSON "
            f"текстом сообщения — получено {raw!r}"
        )

    identity_check = out.get("identity_check")
    assert identity_check is not None, (
        f"NFR17-AC5 (замаскированный отказ): `identity_check` не должен тихо "
        f"пропадать при сборке `--json` на этой ветке, получено {out}"
    )
    assert identity_check["result"] == "not_checked", (
        f"NFR17-AC5: чанк вне диапазона -> `not_checked`, получено {identity_check}"
    )
    assert identity_check.get("reason") == "chunk_out_of_range", (
        "NFR17-AC5: причина обязана называть именно чанк вне диапазона (переиспользуя "
        f"словарь исходов `not_checked`, ADR-024 §Д3), получено {identity_check}"
    )
    assert identity_check["result"] != "match", (
        "NFR17-AC5 (замаскированный отказ): пропуск сверки не должен путаться с "
        "успешным совпадением"
    )
    assert "error" in out and "99" in out["error"], (
        f"сообщение о несуществующем чанке обязано дойти до пользователя под ключом "
        f"`error`, получено {out}"
    )


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_nfr17_malformed_negative_chunk_index_also_skips_network_call_and_signals_not_checked(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """Класс «испорченный/опечатанный ввод» для NFR17-AC5: `--chunk -1` — не просто
    большое число вне диапазона, а структурно бессмысленное значение (пользователь
    мог опечататься, введя отрицательный номер) — обязано давать тот же честный
    исход, что и положительное значение вне диапазона, не отдельную непроверенную
    ветку (например, не должно случайно попасть в валидный `chunk_index` через
    Python-семантику отрицательной индексации где-то в реализации)."""
    key = "REC-1"
    httpx_mock.add_response(
        json={"status": "complete", "tracks": []}, url=_transcript_url_re(key)
    )
    httpx_mock.add_response(
        json={"id": key, "participants": [{"userInfo": {"key": "u1"}}]},
        url=_recording_url_re(key),
    )

    rc = _run(
        ["get-transcript", key, "--json", "--chunk", "-1", "--chunk-size", "10"], monkeypatch
    )
    raw = capsys.readouterr().out

    assert rc == 0
    assert _count_recording_calls(httpx_mock, key) == 0, (
        "NFR17-AC5 (испорченный ввод, отрицательный чанк): сверка не должна "
        f"запускаться, фактически вызовов get_recording: "
        f"{_count_recording_calls(httpx_mock, key)}"
    )
    out = json.loads(raw)
    assert out.get("identity_check", {}).get("reason") == "chunk_out_of_range", (
        f"отрицательный `--chunk` обязан классифицироваться как вне диапазона, "
        f"получено {out}"
    )


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
def test_nfr17_out_of_range_chunk_with_no_verify_identity_is_unaffected_by_hardening(
    httpx_mock: HTTPXMock, monkeypatch, capsys
):
    """Регресс-guard (companion-спека, «Edge cases»): `--no-verify-identity` +
    `--chunk` вне диапазона — поведение НЕ меняется ADR-024 Д3 (сверка и без того
    отключена явным флагом, `identity_check` не появляется вовсе); ожидание — уже
    верно на сегодняшнем дереве, тест закрепляет это (green guard), не проектирует
    новое поведение."""
    key = "REC-1"
    httpx_mock.add_response(
        json={"status": "complete", "tracks": []}, url=_transcript_url_re(key)
    )

    rc = _run(
        [
            "get-transcript",
            key,
            "--json",
            "--chunk",
            "99",
            "--chunk-size",
            "10",
            "--no-verify-identity",
        ],
        monkeypatch,
    )
    raw = capsys.readouterr().out

    assert rc == 0
    assert _count_recording_calls(httpx_mock, key) == 0, (
        "`--no-verify-identity`: сверка не должна запускаться независимо от чанка"
    )
    assert "identity_check" not in raw, (
        f"`--no-verify-identity`: `identity_check` не должен появляться вовсе, "
        f"получено {raw!r}"
    )
    assert "не существует" in raw, (
        f"сообщение о несуществующем чанке должно дойти до пользователя как есть, "
        f"получено: {raw!r}"
    )


# ============================================================================================
# NFR17-AC5, unit — `formatters.resolve_chunk_range` (новая чистая функция, ADR-024 §3)
# ============================================================================================


def _five_entry_raw_transcript() -> dict:
    """5 треков по одной реплике из 30 символов -> с `chunk_size=80` даёт РОВНО 5
    raw-чанков (проверено на сегодняшнем `chunk_transcript_raw`, до правки —
    фикстура объективна, не подогнана под ожидаемый ответ новой функции)."""
    tracks = []
    for i in range(5):
        tracks.append(
            {
                "speaker": {"userInfo": {"key": f"u{i}"}, "isAnonymous": False},
                "chunks": [{"startTimeOffsetInMillis": i * 1000, "text": "x" * 30}],
            }
        )
    return {"status": "complete", "tracks": tracks}


def test_nfr17_ac5_resolve_chunk_range_reports_in_range_for_a_middle_chunk():
    from ktalk_cli.formatters import resolve_chunk_range

    data = _five_entry_raw_transcript()

    in_range, total_chunks = resolve_chunk_range(data, "raw", 3, 80)

    assert total_chunks == 5, f"фикстура даёт 5 raw-чанков, получено {total_chunks}"
    assert in_range is True, "чанк 3 из 5 — валидный номер, ожидался in_range=True"


def test_nfr17_ac5_resolve_chunk_range_boundary_last_valid_chunk_is_in_range():
    from ktalk_cli.formatters import resolve_chunk_range

    data = _five_entry_raw_transcript()

    in_range, total_chunks = resolve_chunk_range(data, "raw", 5, 80)

    assert total_chunks == 5
    assert in_range is True, (
        "граница: последний валидный номер чанка (== total_chunks) обязан быть "
        "in_range=True"
    )


def test_nfr17_ac5_resolve_chunk_range_one_past_last_chunk_is_out_of_range():
    from ktalk_cli.formatters import resolve_chunk_range

    data = _five_entry_raw_transcript()

    in_range, total_chunks = resolve_chunk_range(data, "raw", 6, 80)

    assert total_chunks == 5
    assert in_range is False, (
        "граница: total_chunks + 1 обязан быть out_of_range — ровно этот случай "
        "воспроизводит issue #9"
    )


def test_nfr17_ac5_resolve_chunk_range_auto_chunk_zero_maps_to_first_chunk():
    """`--chunk 0` (умолчание, «авто») -> при тексте длиннее `chunk_size` эквивалентен
    первому чанку, та же семантика, что `render_transcript_output` сегодня
    (`chunk_index = 0 if chunk == 0 else chunk - 1`) — новая функция не должна менять
    этот выбор, только вынести его в переиспользуемую форму."""
    from ktalk_cli.formatters import resolve_chunk_range

    data = _five_entry_raw_transcript()

    in_range, total_chunks = resolve_chunk_range(data, "raw", 0, 80)

    assert total_chunks == 5
    assert in_range is True, "`--chunk 0` при длинном тексте обязан маппиться на первый чанк"


def test_nfr17_malformed_resolve_chunk_range_negative_chunk_is_out_of_range():
    """Класс «испорченный/опечатанный ввод» на уровне чистой функции: отрицательный
    номер чанка — не «просто больше total_chunks», а сам по себе структурно
    невалидный ввод; не должен случайно стать валидным через Python-семантику
    отрицательной индексации где-то в реализации `resolve_chunk_range`."""
    from ktalk_cli.formatters import resolve_chunk_range

    data = _five_entry_raw_transcript()

    in_range, total_chunks = resolve_chunk_range(data, "raw", -1, 80)

    assert total_chunks == 5
    assert in_range is False, f"отрицательный чанк обязан быть out_of_range, total_chunks={total_chunks}"
