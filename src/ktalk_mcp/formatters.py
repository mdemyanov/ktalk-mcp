"""Converters from KTalk API JSON responses to markdown."""

from __future__ import annotations

import json
from datetime import datetime

_STATUS_MESSAGES = {
    "inProgress": "В обработке... Попробуйте позже.",
    "failed": "Ошибка обработки.",
    "notFound": "Не найдено.",
    "notAvailable": "Недоступно.",
    "serviceError": "Ошибка сервиса.",
    "recreateInProgress": "Пересоздаётся... Попробуйте позже.",
}

_SUMMARY_TYPE_TITLES = {
    "shortSummary": "Краткое резюме",
    "protocol": "Протокол",
}


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


def format_recording(data: dict) -> str:
    """Format single recording details to markdown."""
    title = data.get("title", "Без названия")
    lines = [f"# {title}", ""]

    lines.append(f"- **Ключ:** {data.get('id', data.get('key', 'N/A'))}")
    lines.append(f"- **Дата:** {_format_datetime(data.get('createdDate'))}")

    created_by = data.get("createdBy")
    if created_by:
        lines.append(f"- **Автор:** {_format_user_name_from_user(created_by)}")

    room = data.get("roomName")
    if room:
        lines.append(f"- **Комната:** {room}")

    lines.append(f"- **Длительность:** {_format_duration(data.get('duration', 0))}")

    participants = data.get("participants", [])
    count = data.get("participantsCount", len(participants))
    if participants:
        names = [_format_user_name(p) for p in participants]
        lines.append(f"- **Участники ({count}):** {', '.join(names)}")
    elif count:
        lines.append(f"- **Участники:** {count}")

    return "\n".join(lines)


def format_recordings_list(data: dict) -> str:
    """Format recordings list response to markdown table."""
    entities = data.get("recordings") or data.get("entities") or []

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


def format_transcript(data: dict) -> str:
    """Format transcript response to markdown dialogue."""
    status = data.get("status", "")

    if status == "inProgress":
        return "# Транскрипт\n\nВ обработке... Попробуйте позже."

    if status in ("error", "failed"):
        msg = data.get("statusMessage", "неизвестная ошибка")
        return f"# Транскрипт\n\nОшибка транскрипции: {msg}"

    tracks = data.get("tracks") or []
    if not tracks:
        return "# Транскрипт\n\nТранскрипт пуст."

    # Collect all chunks with speaker info, sorted by time
    entries: list[tuple[int, str, str]] = []
    for track in tracks:
        speaker_name = _format_user_name(track.get("speaker"))
        for chunk in track.get("chunks") or []:
            time_ms = chunk.get("startTimeOffsetInMillis", 0)
            text = chunk.get("text", "")
            entries.append((time_ms, speaker_name, text))

    entries.sort(key=lambda e: e[0])

    lines = ["# Транскрипт", ""]
    for time_ms, speaker, text in entries:
        timestamp = _format_timestamp(time_ms)
        lines.append(f"**{speaker}** [{timestamp}]: {text}")
        lines.append("")

    return "\n".join(lines).rstrip()


def _format_summary_chunks(chunks: list[dict] | None) -> str:
    """Render summary chunks to markdown text."""
    if not chunks:
        return ""

    lines: list[str] = []
    for chunk in chunks:
        chunk_type = chunk.get("type", "text")
        text = chunk.get("text", "")
        if chunk_type == "heading":
            lines.append(f"### {text}")
        else:
            lines.append(text)
        lines.append("")

    return "\n".join(lines).rstrip()


def format_summary(data: dict) -> str:
    """Format composite summary response (v2) to markdown."""
    lines = ["# Саммари", ""]

    short = data.get("shortSummaryV2", {})
    protocol = data.get("protocolV2", {})

    # Short summary section
    lines.append("## Краткое резюме")
    lines.append("")
    short_status = short.get("status", "notFound")
    if short_status == "success":
        lines.append(_format_summary_chunks(short.get("chunks")))
    else:
        lines.append(_STATUS_MESSAGES.get(short_status, f"Статус: {short_status}"))
    lines.append("")

    # Protocol section
    lines.append("## Протокол")
    lines.append("")
    protocol_status = protocol.get("status", "notFound")
    if protocol_status == "success":
        lines.append(_format_summary_chunks(protocol.get("chunks")))
    else:
        lines.append(_STATUS_MESSAGES.get(protocol_status, f"Статус: {protocol_status}"))

    return "\n".join(lines).rstrip()


def format_summary_by_type(data: dict, summary_type: str) -> str:
    """Format single summary type response to markdown."""
    title = _SUMMARY_TYPE_TITLES.get(summary_type, summary_type)
    status = data.get("status", "notFound")

    if status != "success":
        msg = _STATUS_MESSAGES.get(status, f"Статус: {status}")
        return f"# {title}\n\n{msg}"

    chunks_text = _format_summary_chunks(data.get("chunks"))
    return f"# {title}\n\n{chunks_text}"
