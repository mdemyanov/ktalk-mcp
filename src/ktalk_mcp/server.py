"""KTalk MCP Server — access Kontur Talk recordings, transcripts, and summaries."""

from __future__ import annotations

from fastmcp import FastMCP

from ktalk_mcp.client import KTalkClient, KTalkError
from ktalk_mcp.config import Settings
from ktalk_mcp.formatters import (
    format_raw,
    format_recording,
    format_recordings_list,
    format_summary,
    format_summary_by_type,
    format_transcript,
)

mcp = FastMCP(
    "KTalk",
    instructions="Access Kontur Talk (KTalk) recordings, transcripts, and summaries",
)

_client: KTalkClient | None = None


def _get_client() -> KTalkClient:
    global _client
    if _client is None:
        settings = Settings()
        _client = KTalkClient(
            base_url=settings.ktalk_base_url,
            session_token=settings.ktalk_session_token,
        )
    return _client


def _format_output(data: dict, fmt: str, formatter, **kwargs) -> str:
    if fmt == "raw":
        return format_raw(data)
    return formatter(data, **kwargs)


@mcp.tool()
async def ktalk_list_recordings(
    query: str | None = None,
    start_from: str | None = None,
    start_to: str | None = None,
    top: int = 30,
    order: str = "byTimeNewFirst",
    page_token: str | None = None,
    format: str = "markdown",
) -> str:
    """List available KTalk conference recordings.

    Args:
        query: Search by title, room name, or author
        start_from: Start date filter (ISO 8601, e.g. 2026-03-01)
        start_to: End date filter (ISO 8601)
        top: Number of recordings per page (1-1000, default 30)
        order: Sort order (byTimeNewFirst, byTimeOldFirst, byTitle,
            bySizeBigFirst, bySizeSmallFirst)
        page_token: Pagination token from previous response
        format: Output format — "raw" (JSON) or "markdown" (human-readable table)
    """
    try:
        client = _get_client()
        data = await client.list_recordings(
            query=query,
            start_from=start_from,
            start_to=start_to,
            top=top,
            order_mode=order,
            page_token=page_token,
        )
        return _format_output(data, format, format_recordings_list)
    except KTalkError as e:
        return str(e)


@mcp.tool()
async def ktalk_get_recording(
    recording_key: str,
    format: str = "markdown",
) -> str:
    """Get details of a specific KTalk recording.

    Args:
        recording_key: Recording key/identifier (required)
        format: Output format — "raw" (JSON) or "markdown" (human-readable)
    """
    try:
        client = _get_client()
        data = await client.get_recording(recording_key)
        return _format_output(data, format, format_recording)
    except KTalkError as e:
        return str(e)


@mcp.tool()
async def ktalk_get_transcript(
    recording_key: str,
    format: str = "markdown",
) -> str:
    """Get transcript of a KTalk recording (speech-to-text by speakers).

    Args:
        recording_key: Recording key/identifier (required)
        format: Output format — "raw" (JSON) or "markdown" (dialogue with timecodes)
    """
    try:
        client = _get_client()
        data = await client.get_transcript(recording_key)
        return _format_output(data, format, format_transcript)
    except KTalkError as e:
        return str(e)


@mcp.tool()
async def ktalk_get_summary(
    recording_key: str,
    format: str = "markdown",
) -> str:
    """Get full summary of a KTalk recording (short summary + protocol + transcription).

    Args:
        recording_key: Recording key/identifier (required)
        format: Output format — "raw" (JSON) or "markdown" (structured summary)
    """
    try:
        client = _get_client()
        data = await client.get_summary(recording_key)
        return _format_output(data, format, format_summary)
    except KTalkError as e:
        return str(e)


@mcp.tool()
async def ktalk_get_summary_by_type(
    recording_key: str,
    summary_type: str,
    format: str = "markdown",
) -> str:
    """Get a specific type of summary for a KTalk recording.

    Args:
        recording_key: Recording key/identifier (required)
        summary_type: Type of summary — "shortSummary" or "protocol" (required)
        format: Output format — "raw" (JSON) or "markdown"
    """
    try:
        client = _get_client()
        data = await client.get_summary_by_type(recording_key, summary_type)
        return _format_output(data, format, format_summary_by_type, summary_type=summary_type)
    except KTalkError as e:
        return str(e)


def main():
    mcp.run()
