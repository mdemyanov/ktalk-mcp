"""MCP-инструмент резолюции контактов: `ktalk_search_contacts` (ADR-010-spec §Dev).

Читающий, без побочных эффектов — тот же приём, что `tools_rooms.ktalk_get_room`.
"""

from __future__ import annotations

from fastmcp import FastMCP

from ktalk_mcp.client import KTalkError, get_shared_client
from ktalk_mcp.config import KTalkConfigError
from ktalk_mcp.contacts import search_contacts
from ktalk_mcp.formatters import format_search_contacts, render_tool_output

_AUTH_ERRORS = (KTalkError, KTalkConfigError)


def register(mcp: FastMCP) -> None:
    """Регистрирует инструмент поиска контактов на переданном `mcp`."""

    @mcp.tool()
    async def ktalk_search_contacts(query: str, format: str = "markdown") -> str:
        """Search the KTalk contacts directory to resolve a numeric attendee
        `key` (ADR-010) — session mode only, no confirmed API-key profile.

        Never auto-selects a candidate: 0 matches is a refusal, 1 match is
        shown explicitly (not applied anywhere), >1 matches are listed in
        full without ranking. The resolved `key` still has to be passed
        explicitly to meeting creation (`required_attendee_keys`) — this tool
        does not feed it there automatically.

        Args:
            query: Free-text name/surname (not a login — unverified, ADR-010 §4)
            format: Output format — "raw" (JSON) or "markdown"
        """
        try:
            client = get_shared_client()
            candidates = await search_contacts(client, query)
            return render_tool_output(
                candidates, format, lambda data: format_search_contacts(data, query=query)
            )
        except _AUTH_ERRORS as e:
            return str(e)
