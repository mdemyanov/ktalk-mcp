"""AT-design: полный состав участников (FR-8).

Покрывает: FR-8 AC-1 (дообогащение по условию `len(participants) < participantsCount`,
строгое `<`, не `<=`), AC-2 (анонимные участники не отбрасываются), AC-3 — механизм
двойного источника + флаг `incomplete` из ADR-003-spec «Закрытые открытые вопросы BA» п.2
(боевая проверка реального случая >10 участников остаётся ручной — зонд подтвердил
только 8 из 8, помечено отдельно в at-design.md).

Красные по замыслу: модуль `ktalk_cli.enrichment` (`enrich_batch`, `map_participants`)
и метод `KTalkClient.get_full_participants` не существуют.

Примечание об импортах: имена ключей в возвращаемых словарях участников
(`ktalk_id`/`name`, `incomplete`) взяты дословно из client-modules-spec.md §4
(докстрока `enrich_batch`, докстрока `map_participants`). Форма единичного участника в
`get_full_participants` — рабочая гипотеза (по аналогии с `map_participants`), точный
набор ключей — решение Dev; сама проверка «объединение без потерь и без дублей» не
зависит от точных имён ключей сверх `ktalk_id`/`anonymous_id`.
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


async def test_ac_fr8_1_enrich_batch_enriches_when_participants_shorter_than_count(
    httpx_mock: HTTPXMock, base_url
):
    """AC FR-8/1: participants[] короче participantsCount -> клиент дообогащает через
    запрос по конкретной записи, а не доверяет списковому ответу."""
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.enrichment import enrich_batch

    list_response = _fixture_json("recording-list-item-session.json")
    record = list_response["recordings"][0]
    assert len(record["participants"]) < record["participantsCount"]  # предпосылка фикстуры

    httpx_mock.add_response(json=_fixture_json("recording-detail-session-full-participants.json"))

    async with KTalkClient(base_url=base_url, session_token="sess-1") as client:
        result = await enrich_batch([record], client, concurrency=2)

    assert "REC-SYNC-001" in result
    assert len(result["REC-SYNC-001"]) == 8


async def test_ac_fr8_1b_no_enrichment_when_participants_count_matches_exactly(
    httpx_mock: HTTPXMock, base_url
):
    """Boundary FR-8/1: participantsCount == len(participants) -> НЕ должно вызывать
    дообогащение (строгое `<`, не `<=`) — не регистрируем httpx-ответ, любой сетевой
    вызов провалит тест как неожиданный запрос."""
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.enrichment import enrich_batch

    record = {
        "id": "REC-FULL",
        "participantsCount": 2,
        "participants": [
            {"userInfo": {"key": "u1", "surname": "Иванов", "firstname": "Пётр"}},
            {"userInfo": {"key": "u2", "surname": "Петров", "firstname": "Анна"}},
        ],
    }

    async with KTalkClient(base_url=base_url, session_token="sess-1") as client:
        result = await enrich_batch([record], client, concurrency=2)

    assert result == {}


def test_ac_fr8_2_anonymous_participant_not_dropped():
    """AC FR-8/2: анонимный участник (isAnonymous: true, без userInfo) присутствует в
    результате с различимым представлением — сегодняшний participants_from_api его
    молча выбрасывает (registry.py заморожен, поэтому новый маппер — map_participants)."""
    from ktalk_cli.enrichment import map_participants

    raw = [{"anonymousName": "Гость 1", "anonymousId": "anon-1", "isAnonymous": True}]
    result = map_participants(raw)

    assert result == [{"ktalk_id": "anon-1", "name": "Гость 1"}]


def test_map_participants_named_user_matches_participants_from_api_schema():
    """map_participants сохраняет ту же схему id/name, что и существующий (замороженный)
    participants_from_api — без изменения формата participants в SQLite."""
    from ktalk_cli.enrichment import map_participants

    raw = [{"userInfo": {"key": "u1", "surname": "Иванов", "firstname": "Пётр", "login": "ivanov"}}]
    result = map_participants(raw)

    assert result == [{"ktalk_id": "u1", "name": "Иванов Пётр"}]


async def test_ac_fr8_3_dual_source_merge_dedups_and_flags_incomplete(
    httpx_mock: HTTPXMock, base_url
):
    """Решение открытого вопроса BA (ADR-003-spec): get_full_participants в session-режиме
    объединяет get_recording (participants[]) и get_conference (artifacts.participants) по
    уникальному участнику, не строгое подмножество друг друга. Если объединение всё равно
    короче participantsCount -> явный флаг incomplete=True, без тихого укорачивания.
    Боевая проверка реального случая >10 участников — отдельно, ручная (см. at-design.md)."""
    from ktalk_cli.client import KTalkClient

    detail = _fixture_json("recording-detail-session-oversized-partial.json")
    conference = _fixture_json("conference-history-session-oversized.json")
    assert detail["participantsCount"] == 12
    httpx_mock.add_response(json=detail)
    httpx_mock.add_response(json=conference)

    async with KTalkClient(base_url=base_url, session_token="sess-1") as client:
        result = await client.get_full_participants("REC-BIG")

    participants = result["participants"]
    ids = [p.get("ktalk_id") or p.get("anonymous_id") for p in participants]

    assert len(ids) == len(set(ids))  # без дублей между источниками
    # detail: u1..u9 (9 именованных). conference: u5..u10 (6 именованных, 5 общих с
    # detail + u10 новый) + anon-1. Объединение: u1..u10 (10) + anon-1 (1) = 11 уникальных.
    assert len(ids) == 11
    assert result["incomplete"] is True  # 11 < participantsCount=12


async def test_enrich_batch_partial_failure_does_not_abort_others(
    httpx_mock: HTTPXMock, base_url
):
    """Edge case client-modules-spec §4: одна из N записей отдаёт 500 — остальные N-1
    должны успешно дозавершиться, sync/enrich_batch не падает целиком."""
    from ktalk_cli.client import KTalkClient
    from ktalk_cli.enrichment import enrich_batch

    record_fail = {"id": "R-FAIL", "participantsCount": 3, "participants": [{}]}
    record_ok = {"id": "R-OK", "participantsCount": 3, "participants": [{}]}

    # Dev-фикс стаба: session-режим всегда добавляет ?sessionToken=... ко всем запросам
    # (архитектура клиента, ADR-003) — точный `url=` матчер pytest_httpx требует
    # ПОЛНОГО совпадения query-строки, иначе матч не срабатывает никогда независимо
    # от реализации (root cause подтверждён systematic-debugging, см. отчёт Dev).
    httpx_mock.add_response(
        url=f"{base_url}/api/recordings/R-FAIL?sessionToken=sess-1", status_code=500
    )
    httpx_mock.add_response(
        url=f"{base_url}/api/recordings/R-OK?sessionToken=sess-1",
        json={
            "id": "R-OK", "participantsCount": 3,
            "participants": [
                {"userInfo": {"key": "u1", "surname": "A", "firstname": "B"}},
                {"userInfo": {"key": "u2", "surname": "C", "firstname": "D"}},
                {"userInfo": {"key": "u3", "surname": "E", "firstname": "F"}},
            ],
        },
    )

    async with KTalkClient(base_url=base_url, session_token="sess-1") as client:
        result = await enrich_batch([record_fail, record_ok], client, concurrency=2)

    assert "R-OK" in result
    assert len(result["R-OK"]) == 3
    assert "R-FAIL" not in result
