"""KTalk MCP Server — access Kontur Talk recordings, transcripts, and summaries."""

from __future__ import annotations

from fastmcp import FastMCP

from ktalk_mcp.client import KTalkError, get_shared_client
from ktalk_mcp.config import KTalkConfigError
from ktalk_mcp.formatters import format_auth_status, render_tool_output
from ktalk_mcp.tools_meetings import register as register_meetings_tools
from ktalk_mcp.tools_recordings import register as register_recordings_tools
from ktalk_mcp.tools_rooms import register as register_rooms_tools
from ktalk_mcp.tools_scheduling import register as register_scheduling_tools

mcp = FastMCP(
    "KTalk",
    instructions="Access Kontur Talk (KTalk) recordings, transcripts, and summaries",
)

_AUTH_ERRORS = (KTalkError, KTalkConfigError)

register_recordings_tools(mcp)
register_meetings_tools(mcp)
register_rooms_tools(mcp)
register_scheduling_tools(mcp)


@mcp.tool()
async def ktalk_auth_status(format: str = "markdown") -> str:
    """Diagnose the active authorization mechanism (FR-11).

    Reports whether the personal API key or session token is alive, and — for
    the API key — its scopes and expiration, when available.

    Args:
        format: Output format — "raw" (JSON) or "markdown"
    """
    try:
        client = get_shared_client()
        status = await client.get_auth_status()
        data = {
            "alive": status.alive,
            "scopes": status.scopes,
            "expired_at": status.expired_at,
            "note": status.note,
        }
        return render_tool_output(data, format, format_auth_status)
    except _AUTH_ERRORS as e:
        return str(e)


def main():
    mcp.run()
