"""MCP-инструмент сущности «Комната»: `ktalk_get_room` (FR-17)."""

from __future__ import annotations

from fastmcp import FastMCP

from ktalk_mcp.client import KTalkError, get_shared_client
from ktalk_mcp.config import KTalkConfigError
from ktalk_mcp.formatters import format_room, render_tool_output
from ktalk_mcp.rooms import get_room

_AUTH_ERRORS = (KTalkError, KTalkConfigError)


def register(mcp: FastMCP) -> None:
    """Регистрирует инструменты сущности «Комната» на переданном `mcp`."""

    @mcp.tool()
    async def ktalk_get_room(room_name: str, format: str = "markdown") -> str:
        """Get room details (FR-17, session mode only — no confirmed API-key profile).

        WARNING — SIDE EFFECT (ADR-006): the server returns 200 for any room
        name, including one never seen before, with an identically shaped
        response (never a 404). Calling this with a name not yet read in this
        contour CREATES the room object as a side effect of reading; this is
        irreversible — the project has no delete operation. Do NOT use this
        tool to check whether a name is available/occupied — the check itself
        creates the occupancy.

        Args:
            room_name: Room name (path-quoted before the request)
            format: Output format — "raw" (JSON) or "markdown"
        """
        try:
            client = get_shared_client()
            room = await get_room(client, room_name)
            return render_tool_output(room, format, format_room)
        except _AUTH_ERRORS as e:
            return str(e)
