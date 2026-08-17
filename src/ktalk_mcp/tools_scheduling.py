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
        required_attendee_keys: list[str] | None = None,
        description: str | None = None,
        enable_auto_recording: bool | None = None,
        pin_code: str | None = None,
        pin_code_explicit_none: bool = False,
        allow_anonymous: bool | None = None,
        anonymous_access_expiration: str | None = None,
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
            start: Local ISO 8601 start time with offset (required) — converted
                to UTC internally (ADR-009)
            end: Local ISO 8601 end time with offset (required) — converted to
                UTC internally (ADR-009)
            timezone: Timezone (required — no silent default, NFR-9)
            room_name: Room name (required)
            required_attendee_keys: Numeric attendee ids as strings (not logins,
                ADR-009); explicit empty list is valid
            description: Optional description (only field with a silent default)
            enable_auto_recording: Whether the meeting is recorded (required, no silent default)
            pin_code: Room PIN code
            pin_code_explicit_none: True means "explicitly no PIN" (JSON null);
                without either signal, pin_code is required
            allow_anonymous: Whether unauthenticated participants may join (required)
            anonymous_access_expiration: Required only if allow_anonymous is True
                (ADR-009 §3 — no computed default)
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
                required_attendee_keys=required_attendee_keys,
                description=description,
                enable_auto_recording=enable_auto_recording,
                pin_code=pin_code,
                pin_code_explicit_none=pin_code_explicit_none,
                allow_anonymous=allow_anonymous,
                anonymous_access_expiration=anonymous_access_expiration,
            )
            data = {"body": body, "confirmation_id": confirmation_id}
            return render_tool_output(data, format, format_meeting_preview)
        except _AUTH_ERRORS as e:
            return str(e)
