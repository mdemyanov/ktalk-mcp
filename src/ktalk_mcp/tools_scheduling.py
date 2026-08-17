"""MCP-инструмент предпросмотра встречи: `ktalk_preview_meeting` (FR-13, §6.4).

Мутирующего MCP-инструмента нет и не появится — только предпросмотр (ADR-005
«Решение»): подтверждение/создание доступны исключительно подкомандой CLI
`create-meeting-confirm` за барьером `isatty()`.
"""

from __future__ import annotations

from fastmcp import FastMCP

from ktalk_mcp.client import KTalkError
from ktalk_mcp.confirmation import ConfirmationStore
from ktalk_mcp.formatters import format_meeting_preview, render_tool_output
from ktalk_mcp.meeting_scheduling import PreviewService

_AUTH_ERRORS = (KTalkError,)


def register(mcp: FastMCP) -> None:
    """Регистрирует инструмент предпросмотра встречи на переданном `mcp`."""

    @mcp.tool()
    async def ktalk_preview_meeting(
        subject: str | None = None,
        start: str | None = None,
        end: str | None = None,
        timezone: str | None = None,
        room_name: str | None = None,
        required_user_keys: list[str] | None = None,
        description: str | None = None,
        enable_auto_recording: bool | None = None,
        enable_sip: bool | None = None,
        pin_code: str | None = None,
        allow_anonymous: bool | None = None,
        format: str = "markdown",
    ) -> str:
        """Preview a single meeting to be created (FR-13) — zero network calls.

        Does not create anything, ever: there is no MCP tool that does. To
        actually create the meeting, run `create-meeting-confirm` in an
        interactive terminal (CLI) with the same parameters. The
        `confirmation_id` in the output is informational for a human to
        cross-check against the terminal prompt — it is not a machine-checkable
        link between this call and the CLI confirmation (separate processes).

        Args:
            subject: Meeting subject (required)
            start: Start time (ISO 8601, required)
            end: End time (ISO 8601, required)
            timezone: Timezone (required — no silent default, NFR-9)
            room_name: Room name (required)
            required_user_keys: Required attendee keys; explicit empty list is valid
            description: Optional description (only field with a silent default)
            enable_auto_recording: Whether the meeting is recorded (required, no silent default)
            enable_sip: Whether SIP dial-in is enabled (required, no silent default)
            pin_code: Room PIN code; explicit empty string is valid ("no PIN")
            allow_anonymous: Whether unauthenticated participants may join (required)
            format: Output format — "raw" (JSON) or "markdown"
        """
        try:
            service = PreviewService(ConfirmationStore())
            body, confirmation_id = service.preview(
                subject=subject,
                start=start,
                end=end,
                timezone=timezone,
                room_name=room_name,
                required_user_keys=required_user_keys,
                description=description,
                enable_auto_recording=enable_auto_recording,
                enable_sip=enable_sip,
                pin_code=pin_code,
                allow_anonymous=allow_anonymous,
            )
            data = {"body": body, "confirmation_id": confirmation_id}
            return render_tool_output(data, format, format_meeting_preview)
        except _AUTH_ERRORS as e:
            return str(e)
