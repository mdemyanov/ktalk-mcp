"""MCP-инструменты сущности «Встреча/архив/чат»: `ktalk_list_archive` (FR-9),
`ktalk_get_chat_messages` (FR-10), `ktalk_list_calendar` (FR-18)."""

from __future__ import annotations

from datetime import date

from fastmcp import FastMCP

from ktalk_mcp.calendar_reader import get_calendar_window
from ktalk_mcp.client import KTalkError, get_shared_client
from ktalk_mcp.config import KTalkConfigError
from ktalk_mcp.formatters import (
    format_archive_list,
    format_calendar,
    format_chat_messages,
    render_tool_output,
)

_AUTH_ERRORS = (KTalkError, KTalkConfigError)


def register(mcp: FastMCP) -> None:
    """Регистрирует инструменты сущности «Встреча» на переданном `mcp`."""

    @mcp.tool()
    async def ktalk_list_archive(
        from_date: str,
        to_date: str,
        room_names: list[str] | None = None,
        format: str = "markdown",
    ) -> str:
        """List archived meetings within a date window (FR-9, personal API key only).

        Reads the whole window client-side across all pages — unlike
        `ktalk_list_recordings`, this returns the full result in one call.

        Args:
            from_date: Window start date (ISO 8601)
            to_date: Window end date (ISO 8601)
            room_names: Optional filter by room name(s)
            format: Output format — "raw" (JSON) or "markdown"
        """
        try:
            client = get_shared_client()
            meetings = await client.list_archive(
                from_date=from_date, to_date=to_date, room_names=room_names
            )
            return render_tool_output(meetings, format, format_archive_list)
        except _AUTH_ERRORS as e:
            return str(e)

    @mcp.tool()
    async def ktalk_get_chat_messages(
        recording_key: str | None = None,
        conference_key: str | None = None,
        channel: str | None = None,
        format: str = "markdown",
    ) -> str:
        """Get chat messages of a meeting (FR-10).

        Either `recording_key` or `conference_key` must be given; if `channel`
        is omitted, an available channel is resolved automatically instead of
        failing with a raw "channel field is required" error.

        Args:
            recording_key: Recording key/identifier (resolves the meeting bridge)
            conference_key: Meeting/conference key (used directly if given)
            channel: Chat channel name (e.g. "general"); auto-resolved if omitted
            format: Output format — "raw" (JSON) or "markdown"
        """
        try:
            client = get_shared_client()
            messages = await client.get_chat_messages(
                recording_key=recording_key, conference_key=conference_key, channel=channel
            )
            return render_tool_output(messages, format, format_chat_messages)
        except _AUTH_ERRORS as e:
            return str(e)

    @mcp.tool()
    async def ktalk_list_calendar(
        start: str | None = None,
        end: str | None = None,
        room_name: str | None = None,
        format: str = "markdown",
    ) -> str:
        """List scheduled meetings visible to the active authorization (FR-18).

        Reports meetings this session/key can see — not necessarily a personal
        calendar. Window is segmented server-side into <=7-day chunks transparently;
        segments hitting the 100-item cap are flagged.

        Args:
            start: Window start date (ISO 8601), required
            end: Window end date (ISO 8601), required
            room_name: Optional filter by room name
            format: Output format — "raw" (JSON) or "markdown"
        """
        if start is None or end is None:
            raise ValueError("Нужно указать и начало (start), и конец (end) окна.")
        try:
            client = get_shared_client()
            result = await get_calendar_window(
                client, date.fromisoformat(start), date.fromisoformat(end), room_name=room_name
            )
            data = {
                "items": result.items,
                "incomplete_segments": [
                    [s.isoformat(), e.isoformat()] for s, e in result.incomplete_segments
                ],
            }
            return render_tool_output(data, format, format_calendar)
        except _AUTH_ERRORS as e:
            return str(e)
