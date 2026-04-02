import json

import pytest


class TestHelpers:
    def test_format_duration_minutes_only(self):
        from ktalk_mcp.formatters import _format_duration

        assert _format_duration(300) == "5 мин"
        assert _format_duration(45) == "1 мин"
        assert _format_duration(0) == "0 мин"

    def test_format_duration_hours_and_minutes(self):
        from ktalk_mcp.formatters import _format_duration

        assert _format_duration(3600) == "1 ч 0 мин"
        assert _format_duration(4800) == "1 ч 20 мин"
        assert _format_duration(7260) == "2 ч 1 мин"

    def test_format_timestamp_millis(self):
        from ktalk_mcp.formatters import _format_timestamp

        assert _format_timestamp(0) == "00:00:00"
        assert _format_timestamp(15000) == "00:00:15"
        assert _format_timestamp(102000) == "00:01:42"
        assert _format_timestamp(3723000) == "01:02:03"

    def test_format_user_name_full(self):
        from ktalk_mcp.formatters import _format_user_name

        user_ref = {
            "userInfo": {"surname": "Иванов", "firstname": "Иван", "login": "iivanov"},
            "isAnonymous": False,
        }
        assert _format_user_name(user_ref) == "Иванов Иван"

    def test_format_user_name_login_fallback(self):
        from ktalk_mcp.formatters import _format_user_name

        user_ref = {
            "userInfo": {"surname": None, "firstname": None, "login": "iivanov"},
            "isAnonymous": False,
        }
        assert _format_user_name(user_ref) == "iivanov"

    def test_format_user_name_anonymous(self):
        from ktalk_mcp.formatters import _format_user_name

        user_ref = {
            "anonymousName": "Гость 1",
            "userInfo": None,
            "isAnonymous": True,
        }
        assert _format_user_name(user_ref) == "Гость 1"

    def test_format_user_name_no_info(self):
        from ktalk_mcp.formatters import _format_user_name

        assert _format_user_name(None) == "Неизвестный"
        assert _format_user_name({}) == "Неизвестный"

    def test_format_user_name_from_talk_user(self):
        from ktalk_mcp.formatters import _format_user_name_from_user

        user = {"surname": "Петрова", "firstname": "Мария", "login": "mpetrova"}
        assert _format_user_name_from_user(user) == "Петрова Мария"

    def test_format_user_name_from_talk_user_short(self):
        from ktalk_mcp.formatters import _format_user_name_short

        user = {"surname": "Иванов", "firstname": "Иван"}
        assert _format_user_name_short(user) == "Иванов И."

    def test_format_datetime(self):
        from ktalk_mcp.formatters import _format_datetime

        assert _format_datetime("2026-04-01T10:00:00Z") == "2026-04-01 10:00"
        assert _format_datetime("2026-04-01T10:30:45.123Z") == "2026-04-01 10:30"
        assert _format_datetime(None) == ""

    def test_format_raw(self):
        from ktalk_mcp.formatters import format_raw

        data = {"key": "value", "число": 42}
        result = format_raw(data)
        parsed = json.loads(result)
        assert parsed == data
        assert "число" in result  # ensure_ascii=False
