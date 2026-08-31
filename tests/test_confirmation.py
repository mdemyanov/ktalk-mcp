"""AT-design: FR-13 — хранилище подтверждений (`ktalk_cli.confirmation`).

Покрывает ADR-005-spec «Форма подтверждения»/«Сценарии отказа»: issue/match/consume,
TTL, single-use, hash-drift — с инжектируемыми часами (тестируемость без реального
времени ожидания).

Красные по замыслу: `ktalk_cli.confirmation` не существует.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

HASH_A = "a" * 64  # синтетический sha256-подобный хеш
HASH_B = "b" * 64


class _FakeClock:
    def __init__(self, start: datetime) -> None:
        self._now = start

    def __call__(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


def _store(clock: _FakeClock):
    from ktalk_cli.confirmation import ConfirmationStore

    return ConfirmationStore(clock=clock)


@pytest.fixture
def clock():
    return _FakeClock(datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc))


def test_issue_returns_a_token_not_derived_from_the_hash(clock):
    """`issue` -> непредсказуемый id, не производный от `body_hash` — иначе агент
    вычислил бы id локально, минуя факт вызова предпросмотра."""
    store = _store(clock)

    confirmation_id = store.issue(HASH_A)

    assert confirmation_id != HASH_A
    assert HASH_A not in confirmation_id


def test_two_issues_of_the_same_hash_give_different_tokens(clock):
    store = _store(clock)

    id1 = store.issue(HASH_A)
    id2 = store.issue(HASH_A)

    assert id1 != id2


def test_match_true_right_after_issue_with_same_hash(clock):
    store = _store(clock)

    confirmation_id = store.issue(HASH_A)

    assert store.match(confirmation_id, HASH_A) is True


def test_match_false_for_unknown_confirmation_id(clock):
    """FR-13 AC-3: вызов создания без предшествующего успешного предпросмотра/ссылки
    на него отклоняется — даже если вызывающий сам придумал строку id."""
    store = _store(clock)

    assert store.match("never-issued-id-invented-by-caller", HASH_A) is False


def test_match_false_when_hash_does_not_match_issued_hash(clock):
    """Confirm с телом, отличающимся от preview хотя бы одним полем -> хеш не
    совпадает, отказ."""
    store = _store(clock)

    confirmation_id = store.issue(HASH_A)

    assert store.match(confirmation_id, HASH_B) is False


def test_consume_then_match_returns_false_single_use(clock):
    """Повторный confirm тем же `confirmation_id` после потребления -> отказ, вторая
    сетевая попытка не выполняется."""
    store = _store(clock)

    confirmation_id = store.issue(HASH_A)
    assert store.match(confirmation_id, HASH_A) is True
    store.consume(confirmation_id)

    assert store.match(confirmation_id, HASH_A) is False


def test_ttl_expiry_makes_match_false_even_with_correct_hash(clock):
    """Confirm после истечения TTL -> отказ, даже если хеш совпал бы."""
    from ktalk_cli.confirmation import CONFIRMATION_TTL

    store = _store(clock)
    confirmation_id = store.issue(HASH_A)

    clock.advance(CONFIRMATION_TTL + timedelta(seconds=1))

    assert store.match(confirmation_id, HASH_A) is False


def test_within_ttl_match_still_true():
    """Незадолго до истечения TTL — подтверждение всё ещё действительно."""
    from ktalk_cli.confirmation import CONFIRMATION_TTL

    start = datetime(2026, 8, 13, 12, 0, 0, tzinfo=timezone.utc)
    clock = _FakeClock(start)
    store = _store(clock)
    confirmation_id = store.issue(HASH_A)

    clock.advance(CONFIRMATION_TTL - timedelta(seconds=1))

    assert store.match(confirmation_id, HASH_A) is True


def test_confirmation_ttl_is_ten_minutes():
    """Дизайн-выбор ADR-005-spec — 10 минут, не измеренная величина, но фиксируемое
    значение (снимок-регрессия)."""
    from ktalk_cli.confirmation import CONFIRMATION_TTL

    assert CONFIRMATION_TTL == timedelta(minutes=10)


def test_confirmation_id_never_starts_with_a_dash():
    """DEV-012: id уходит на командную строку (`--confirmation-id <id>`), а
    `token_urlsafe` умеет начинаться с `-` — argparse принимал такой id за флаг.
    Регрессия на плавающий отказ примерно в каждом двадцатом вызове."""
    from ktalk_cli.confirmation import ConfirmationStore

    store = ConfirmationStore()
    assert all(not store.issue("hash").startswith("-") for _ in range(500))
