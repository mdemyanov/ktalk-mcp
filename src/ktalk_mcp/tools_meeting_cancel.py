"""MCP-инструмент предпросмотра отмены встречи: `ktalk_preview_cancel_meeting`
(ADR-011-spec §5).

Мутирующего MCP-инструмента для отмены нет и не появится — только
предпросмотр, тем же приёмом, что `tools_scheduling.ktalk_preview_meeting`:
подтверждение/отмена доступны исключительно подкомандой CLI
`cancel-meeting-confirm` за барьером `isatty()`.
"""

from __future__ import annotations

from fastmcp import FastMCP

from ktalk_mcp.client import KTalkError
from ktalk_mcp.confirmation import ConfirmationStore
from ktalk_mcp.formatters import format_cancel_preview, render_tool_output
from ktalk_mcp.meeting_cancel import CancelPreviewService

_AUTH_ERRORS = (KTalkError,)


def register(mcp: FastMCP) -> None:
    """Регистрирует инструмент предпросмотра отмены встречи на переданном `mcp`."""

    @mcp.tool()
    async def ktalk_preview_cancel_meeting(
        id: str, reason: str = "", format: str = "markdown"
    ) -> str:
        """Preview cancellation of a single meeting (ADR-011) — zero network calls.

        Does not cancel anything, ever: there is no MCP tool that does. To
        actually cancel the meeting, run `cancel-meeting-confirm` in an
        interactive terminal (CLI) with the same parameters.

        Args:
            id: Base64 meeting id (from `create-meeting-confirm` output or
                calendar reads) — not resolved by name/date, not stored
            reason: Optional cancellation reason (default "" — the only
                confirmed working configuration, Ф-50)
            format: Output format — "raw" (JSON) or "markdown"
        """
        try:
            service = CancelPreviewService(ConfirmationStore())
            payload, confirmation_id = service.preview(id=id, reason=reason)
            data = {"payload": payload, "confirmation_id": confirmation_id}
            return render_tool_output(data, format, format_cancel_preview)
        except _AUTH_ERRORS as e:
            return str(e)
