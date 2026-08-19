"""AT-design: FR-13/NFR-9 — компоновщик тела встречи (`ktalk_mcp.meeting_body`).

ADR-009: состав тела приведён к живому снимку DevTools — `enableSip`/
`requiredUserKeys` удалены (структурно недостижимы), `requiredAttendees`
заменяет `requiredUserKeys` (объекты `{"type": "user", "key": str}`), `start`/
`end` конвертируются в UTC с `Z`, `pinCode` различает «не решено»/«явно нет»,
`anonymousAccessExpirationDate` условно обязателен, три поля —
архитектурные литералы (`isRecurring`, `autoRunDeepFakeDetection`,
`maskingSettings`).
"""

from __future__ import annotations

import pytest

FULL_KWARGS = {
    "subject": "Синтетическая встреча",
    "start": "2026-08-15T10:00:00+03:00",
    "end": "2026-08-15T11:00:00+03:00",
    "timezone": "GMT+3",
    "room_name": "test-room-alpha",
    "required_attendee_keys": ["1001", "1002"],
    "description": "Синтетическое описание",
    "enable_auto_recording": True,
    "pin_code": "1234",
    "allow_anonymous": False,
}

# (kwarg, ожидаемое имя JSON-поля в сообщении об ошибке) — общий `_REQUIRED`-цикл
# (без pinCode/anonymousAccessExpirationDate — у них своя развилка, см. ниже)
_REQUIRED_KWARG_TO_FIELD = [
    ("subject", "subject"),
    ("start", "start"),
    ("end", "end"),
    ("timezone", "timezone"),
    ("room_name", "roomName"),
    ("required_attendee_keys", "requiredAttendees"),
    ("allow_anonymous", "allowAnonymous"),
    ("enable_auto_recording", "enableAutoRecording"),
]


@pytest.mark.parametrize("kwarg, field_name", _REQUIRED_KWARG_TO_FIELD)
def test_nfr9_field_not_passed_explicitly_rejects_before_any_side_effect(kwarg, field_name):
    """AC NFR-9/FR-13: поле не передано явно (`None`) -> запрос отклоняется с указанием
    конкретного отсутствующего поля."""
    from ktalk_mcp.meeting_body import MissingFieldError, build_meeting_body

    kwargs = dict(FULL_KWARGS)
    kwargs[kwarg] = None

    with pytest.raises(MissingFieldError) as exc_info:
        build_meeting_body(**kwargs)

    assert field_name in str(exc_info.value)


def test_nfr9_empty_required_attendee_keys_list_is_a_valid_explicit_decision():
    """Явный пустой список участников — валидное явное решение «без обязательных
    участников», не то же самое, что «участники не указаны» (None)."""
    from ktalk_mcp.meeting_body import build_meeting_body

    kwargs = dict(FULL_KWARGS)
    kwargs["required_attendee_keys"] = []

    body = build_meeting_body(**kwargs)
    assert body["requiredAttendees"] == []


@pytest.mark.parametrize("value", [True, False])
def test_nfr9_explicit_boolean_false_is_not_confused_with_missing(value):
    """`enableAutoRecording`/`allowAnonymous` явно переданные `False` — валидные
    решения, не путаются с отсутствием значения (`is None`, не truthiness)."""
    from ktalk_mcp.meeting_body import build_meeting_body

    kwargs = dict(FULL_KWARGS)
    kwargs["enable_auto_recording"] = value
    kwargs["allow_anonymous"] = value
    if value is True:
        kwargs["anonymous_access_expiration"] = "2026-08-18T20:59:59.999Z"

    body = build_meeting_body(**kwargs)
    assert body["enableAutoRecording"] is value
    assert body["allowAnonymous"] is value


def test_description_omitted_gets_quiet_empty_string_default():
    """`description` — единственное поле с разрешённым тихим дефолтом (NFR-9)."""
    from ktalk_mcp.meeting_body import build_meeting_body

    kwargs = dict(FULL_KWARGS)
    kwargs["description"] = None

    body = build_meeting_body(**kwargs)
    assert body["description"] == ""


def test_build_meeting_body_full_valid_kwargs_produces_exact_allow_list():
    """ADR-009: состав тела — ровно 13 ключей снимка DevTools, не 11 (ADR-005)."""
    from ktalk_mcp.meeting_body import build_meeting_body

    body = build_meeting_body(**FULL_KWARGS)

    expected_keys = {
        "subject",
        "start",
        "end",
        "timezone",
        "roomName",
        "requiredAttendees",
        "description",
        "enableAutoRecording",
        "pinCode",
        "allowAnonymous",
        "anonymousAccessExpirationDate",
        "isRecurring",
        "autoRunDeepFakeDetection",
        "maskingSettings",
    }
    assert set(body.keys()) == expected_keys
    assert len(expected_keys) == 14  # 13 из спеки + subject уже учтён в счёте спеки


def test_build_meeting_body_has_no_parameter_for_recurrence_fields():
    """`isRecurring`/`recurrence` структурно недостижимы — проверка сигнатуры, не
    поведения (нет параметра, который можно было бы передать)."""
    import inspect

    from ktalk_mcp.meeting_body import build_meeting_body

    params = set(inspect.signature(build_meeting_body).parameters)
    assert "is_recurring" not in params
    assert "isRecurring" not in params
    assert "recurrence" not in params


def test_build_meeting_body_has_no_parameter_for_enable_sip_or_required_user_keys():
    """ADR-009: `enable_sip`/`required_user_keys` удалены из сигнатуры целиком —
    вызывающий код, передающий их, получает `TypeError` времени правки, не
    рантайм-ошибку построения тела."""
    import inspect

    from ktalk_mcp.meeting_body import build_meeting_body

    params = set(inspect.signature(build_meeting_body).parameters)
    assert "enable_sip" not in params
    assert "required_user_keys" not in params


def test_build_meeting_body_rejects_removed_kwargs_with_type_error():
    from ktalk_mcp.meeting_body import build_meeting_body

    kwargs = dict(FULL_KWARGS)
    kwargs["enable_sip"] = True
    with pytest.raises(TypeError):
        build_meeting_body(**kwargs)


def test_build_meeting_body_has_no_parameter_for_fields_outside_agreed_scope():
    """Поля вне согласованного состава (постановка «Вне рамок») структурно
    недостижимы — не рантайм-фильтрация. `masking_settings`/
    `auto_run_deep_fake_detection` — архитектурные литералы (ADR-009 §2), не
    параметры вызывающего."""
    import inspect

    from ktalk_mcp.meeting_body import build_meeting_body

    params = set(inspect.signature(build_meeting_body).parameters)
    out_of_scope = {
        "optional_user_keys",
        "required_external_attendees_emails",
        "option_external_attendees_emails",
        "simultaneous_translation",
        "custom_meeting_url",
        "masking_settings",
        "auto_run_deep_fake_detection",
        "is_all_day_event",
        "controlled_via_external_system",
    }
    assert not (params & out_of_scope)


# --- ADR-009 §2: _FIXED архитектурные литералы --------------------------------------


def test_fixed_literals_present_regardless_of_caller_input():
    from ktalk_mcp.meeting_body import build_meeting_body

    body = build_meeting_body(**FULL_KWARGS)

    assert body["isRecurring"] is False
    assert body["autoRunDeepFakeDetection"] is None
    assert body["maskingSettings"] == {
        "nameMaskingMode": "none",
        "postMaskingMode": "none",
        "showAdditionalInfo": True,
    }


# --- ADR-009 §1: start/end -> UTC с Z и миллисекундами -------------------------------


def test_start_end_converted_to_utc_with_z_suffix_and_milliseconds():
    from ktalk_mcp.meeting_body import build_meeting_body

    body = build_meeting_body(**FULL_KWARGS)

    # Europe/Moscow +03:00 -> UTC: 10:00 -> 07:00, 11:00 -> 08:00
    assert body["start"] == "2026-08-15T07:00:00.000Z"
    assert body["end"] == "2026-08-15T08:00:00.000Z"


# --- ADR-009 §4: requiredAttendees ----------------------------------------------------


def test_build_required_attendees_wraps_numeric_keys_as_user_type_objects():
    from ktalk_mcp.meeting_body import build_required_attendees

    assert build_required_attendees(["1001", "1002"]) == [
        {"type": "user", "key": "1001"},
        {"type": "user", "key": "1002"},
    ]


def test_build_meeting_body_does_not_validate_attendee_key_format():
    """Edge case контракта QA-author: логин вместо числового id не отвергается
    компоновщиком — задокументированный предел, не баг."""
    from ktalk_mcp.meeting_body import build_meeting_body

    kwargs = dict(FULL_KWARGS)
    kwargs["required_attendee_keys"] = ["vkuznetsov"]

    body = build_meeting_body(**kwargs)
    assert body["requiredAttendees"] == [{"type": "user", "key": "vkuznetsov"}]


# --- ADR-009 §2: pinCode — три исхода (None/explicit-None/строка) --------------------


def test_pin_code_none_without_explicit_flag_raises_missing_field_error():
    from ktalk_mcp.meeting_body import MissingFieldError, build_meeting_body

    kwargs = dict(FULL_KWARGS)
    kwargs["pin_code"] = None

    with pytest.raises(MissingFieldError) as exc_info:
        build_meeting_body(**kwargs)
    assert "pinCode" in str(exc_info.value)


def test_pin_code_explicit_none_produces_json_null():
    from ktalk_mcp.meeting_body import build_meeting_body

    kwargs = dict(FULL_KWARGS)
    kwargs["pin_code"] = None
    kwargs["pin_code_explicit_none"] = True

    body = build_meeting_body(**kwargs)
    assert body["pinCode"] is None


def test_pin_code_string_value_is_passed_through():
    from ktalk_mcp.meeting_body import build_meeting_body

    body = build_meeting_body(**FULL_KWARGS)
    assert body["pinCode"] == "1234"


def test_pin_code_explicit_none_wins_over_conflicting_string_value():
    """Оба сигнала переданы одновременно — `pin_code_explicit_none=True`
    побеждает (порядок разрешения конфликта — решение Dev, зафиксировано тестом)."""
    from ktalk_mcp.meeting_body import build_meeting_body

    kwargs = dict(FULL_KWARGS)
    kwargs["pin_code"] = "1234"
    kwargs["pin_code_explicit_none"] = True

    body = build_meeting_body(**kwargs)
    assert body["pinCode"] is None


# --- ADR-009 §3: anonymousAccessExpirationDate — условная обязательность -------------


def test_allow_anonymous_true_without_expiration_raises_missing_field_error():
    from ktalk_mcp.meeting_body import MissingFieldError, build_meeting_body

    kwargs = dict(FULL_KWARGS)
    kwargs["allow_anonymous"] = True
    kwargs["anonymous_access_expiration"] = None

    with pytest.raises(MissingFieldError) as exc_info:
        build_meeting_body(**kwargs)
    assert "anonymousAccessExpirationDate" in str(exc_info.value)


def test_allow_anonymous_true_with_expiration_sets_field():
    from ktalk_mcp.meeting_body import build_meeting_body

    kwargs = dict(FULL_KWARGS)
    kwargs["allow_anonymous"] = True
    kwargs["anonymous_access_expiration"] = "2026-08-18T20:59:59.999Z"

    body = build_meeting_body(**kwargs)
    assert body["anonymousAccessExpirationDate"] == "2026-08-18T20:59:59.999Z"


def test_allow_anonymous_false_expiration_field_is_none():
    from ktalk_mcp.meeting_body import build_meeting_body

    body = build_meeting_body(**FULL_KWARGS)  # allow_anonymous=False в FULL_KWARGS
    assert body["anonymousAccessExpirationDate"] is None


def test_allow_anonymous_false_with_expiration_value_passed_is_dropped_not_raised():
    """Edge case контракта QA-author: `allow_anonymous=False` + значение передано
    -> значение отбрасывается (поле неприменимо), не ошибка (решение Dev)."""
    from ktalk_mcp.meeting_body import build_meeting_body

    kwargs = dict(FULL_KWARGS)
    kwargs["allow_anonymous"] = False
    kwargs["anonymous_access_expiration"] = "2026-08-18T20:59:59.999Z"

    body = build_meeting_body(**kwargs)
    assert body["anonymousAccessExpirationDate"] is None


# --- canonical_body_hash ---------------------------------------------------------------


def test_canonical_body_hash_stable_regardless_of_key_insertion_order():
    from ktalk_mcp.meeting_body import canonical_body_hash

    a = {"subject": "X", "roomName": "R1"}
    b = {"roomName": "R1", "subject": "X"}
    assert canonical_body_hash(a) == canonical_body_hash(b)


def test_canonical_body_hash_differs_when_a_field_changes():
    from ktalk_mcp.meeting_body import canonical_body_hash

    a = {"subject": "X", "roomName": "R1"}
    b = {"subject": "X", "roomName": "R2"}
    assert canonical_body_hash(a) != canonical_body_hash(b)


def test_canonical_body_hash_of_full_body_matches_build_meeting_body_output():
    from ktalk_mcp.meeting_body import build_meeting_body, canonical_body_hash

    body1 = build_meeting_body(**FULL_KWARGS)
    body2 = build_meeting_body(**FULL_KWARGS)
    assert canonical_body_hash(body1) == canonical_body_hash(body2)
