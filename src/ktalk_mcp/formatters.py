"""Converters from KTalk API JSON responses to markdown."""

from __future__ import annotations

import json
from datetime import datetime


def format_raw(data: dict) -> str:
    """Return raw JSON string."""
    return json.dumps(data, ensure_ascii=False, indent=2)


def _format_duration(seconds: int) -> str:
    """Format duration in seconds to human-readable Russian string."""
    if seconds < 3600:
        minutes = max(seconds // 60, 0 if seconds == 0 else 1)
        return f"{minutes} мин"
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    return f"{hours} ч {minutes} мин"


def _format_timestamp(millis: int) -> str:
    """Format milliseconds offset to HH:MM:SS."""
    total_seconds = millis // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _format_user_name(user_ref: dict | None) -> str:
    """Extract display name from TalkUserRef or TalkUserBaseInfoRef."""
    if not user_ref:
        return "Неизвестный"

    if user_ref.get("isAnonymous"):
        return user_ref.get("anonymousName") or "Неизвестный"

    user_info = user_ref.get("userInfo")
    if not user_info:
        return "Неизвестный"

    return _format_user_name_from_user(user_info)


def _format_user_name_from_user(user: dict | None) -> str:
    """Extract display name from TalkUser object."""
    if not user:
        return "Неизвестный"

    surname = user.get("surname")
    firstname = user.get("firstname")

    if surname and firstname:
        return f"{surname} {firstname}"
    if surname:
        return surname
    if firstname:
        return firstname
    return user.get("login") or "Неизвестный"


def _format_user_name_short(user: dict | None) -> str:
    """Format user name as 'Фамилия И.' for table display."""
    if not user:
        return "Неизвестный"

    surname = user.get("surname")
    firstname = user.get("firstname")

    if surname and firstname:
        return f"{surname} {firstname[0]}."
    if surname:
        return surname
    if firstname:
        return firstname
    return user.get("login") or "Неизвестный"


def _format_datetime(dt_string: str | None) -> str:
    """Format ISO 8601 datetime to 'YYYY-MM-DD HH:MM'."""
    if not dt_string:
        return ""
    try:
        dt_string = dt_string.replace("Z", "+00:00")
        dt = datetime.fromisoformat(dt_string)
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return dt_string


def format_recordings_list(data: dict) -> str:
    """Format recordings list response to markdown table."""
    entities = data.get("entities", [])

    if not entities:
        return "# Записи KTalk\n\nЗаписей не найдено."

    lines = [
        "# Записи KTalk",
        "",
        "| Название | Дата | Автор | Длительность | Участники |",
        "|----------|------|-------|-------------|-----------|",
    ]

    for rec in entities:
        title = rec.get("title", "Без названия")
        date = _format_datetime(rec.get("createdDate"))
        author = _format_user_name_short(rec.get("createdBy"))
        duration = _format_duration(rec.get("duration", 0))
        participants = rec.get("participantsCount", 0)
        lines.append(f"| {title} | {date} | {author} | {duration} | {participants} |")

    next_token = data.get("nextPageToken")
    if next_token:
        lines.append("")
        lines.append(f'> Следующая страница: используйте `page_token: "{next_token}"`')

    return "\n".join(lines)
