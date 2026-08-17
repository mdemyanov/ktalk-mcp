"""AT-design: FR-13/NFR-9 — компоновщик тела встречи (`ktalk_mcp.meeting_body`).

Покрывает NFR-9 (единственное AC, параметризовано таблицей из 8 строк -> 9
физических полей + `subject`), инвариант «isRecurring/recurrence и поля вне
согласованного состава физически недостижимы» (FR-13 AC про тело запроса), allow-list
состав тела, `canonical_body_hash`.

Красные по замыслу: `ktalk_mcp.meeting_body` не существует.
"""

from __future__ import annotations

import pytest

FULL_KWARGS = {
    "subject": "Синтетическая встреча",
    "start": "2026-08-15T10:00:00+03:00",
    "end": "2026-08-15T11:00:00+03:00",
    "timezone": "Europe/Moscow",
    "room_name": "test-room-alpha",
    "required_user_keys": ["synthetic-user-1", "synthetic-user-2"],
    "description": "Синтетическое описание",
    "enable_auto_recording": True,
    "enable_sip": True,
    "pin_code": "1234",
    "allow_anonymous": False,
}

# (kwarg, ожидаемое имя JSON-поля в сообщении об ошибке) — NFR-9 8 строк + subject
_REQUIRED_KWARG_TO_FIELD = [
    ("subject", "subject"),
    ("start", "start"),
    ("end", "end"),
    ("timezone", "timezone"),
    ("room_name", "roomName"),
    ("required_user_keys", "requiredUserKeys"),
    ("allow_anonymous", "allowAnonymous"),
    ("pin_code", "pinCode"),
    ("enable_sip", "enableSip"),
    ("enable_auto_recording", "enableAutoRecording"),
]


@pytest.mark.parametrize("kwarg, field_name", _REQUIRED_KWARG_TO_FIELD)
def test_nfr9_field_not_passed_explicitly_rejects_before_any_side_effect(kwarg, field_name):
    """AC NFR-9/FR-13: поле не передано явно (`None`) -> запрос отклоняется с указанием
    конкретного отсутствующего поля — параметризовано по всем 10 полям (9 физических
    строк NFR-9 + `subject`, обязателен по схеме)."""
    from ktalk_mcp.meeting_body import MissingFieldError, build_meeting_body

    kwargs = dict(FULL_KWARGS)
    kwargs[kwarg] = None

    with pytest.raises(MissingFieldError) as exc_info:
        build_meeting_body(**kwargs)

    assert field_name in str(exc_info.value)


def test_nfr9_empty_required_user_keys_list_is_a_valid_explicit_decision():
    """Явный пустой список участников — валидное явное решение «без обязательных
    участников», не то же самое, что «участники не указаны» (None)."""
    from ktalk_mcp.meeting_body import build_meeting_body

    kwargs = dict(FULL_KWARGS)
    kwargs["required_user_keys"] = []

    body = build_meeting_body(**kwargs)
    assert body["requiredUserKeys"] == []


def test_nfr9_empty_pin_code_string_is_a_valid_explicit_decision():
    """Явный пустой pinCode ("без пина") — валидное явное решение, отличное от
    отсутствия поля вовсе."""
    from ktalk_mcp.meeting_body import build_meeting_body

    kwargs = dict(FULL_KWARGS)
    kwargs["pin_code"] = ""

    body = build_meeting_body(**kwargs)
    assert body["pinCode"] == ""


@pytest.mark.parametrize("value", [True, False])
def test_nfr9_explicit_boolean_false_is_not_confused_with_missing(value):
    """`enableSip=False`/`enableAutoRecording=False`/`allowAnonymous=False` явно
    переданные — валидные решения, не путаются с отсутствием значения (`is None`,
    не truthiness)."""
    from ktalk_mcp.meeting_body import build_meeting_body

    kwargs = dict(FULL_KWARGS)
    kwargs["enable_sip"] = value
    kwargs["enable_auto_recording"] = value
    kwargs["allow_anonymous"] = value

    body = build_meeting_body(**kwargs)
    assert body["enableSip"] is value
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
    """Состав тела ровно allow-list — ни поля сверх названных постановкой (плюс
    `allowAnonymous`), ни `isRecurring`/`recurrence`."""
    from ktalk_mcp.meeting_body import build_meeting_body

    body = build_meeting_body(**FULL_KWARGS)

    expected_keys = {
        "subject",
        "start",
        "end",
        "timezone",
        "roomName",
        "requiredUserKeys",
        "description",
        "enableAutoRecording",
        "enableSip",
        "pinCode",
        "allowAnonymous",
    }
    assert set(body.keys()) == expected_keys


def test_build_meeting_body_has_no_parameter_for_recurrence_fields():
    """`isRecurring`/`recurrence` структурно недостижимы — проверка сигнатуры, не
    поведения (нет параметра, который можно было бы передать)."""
    import inspect

    from ktalk_mcp.meeting_body import build_meeting_body

    params = set(inspect.signature(build_meeting_body).parameters)
    assert "is_recurring" not in params
    assert "isRecurring" not in params
    assert "recurrence" not in params


def test_build_meeting_body_has_no_parameter_for_fields_outside_agreed_scope():
    """Поля вне согласованного состава (постановка «Вне рамок») структурно
    недостижимы — не рантайм-фильтрация."""
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
