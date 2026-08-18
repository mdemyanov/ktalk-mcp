"""MCP-инструменты сущности «Запись»: 5 существующих (перенесены из `server.py`
дословно, NFR-1) + `ktalk_get_participants` (FR-8) + `ktalk_download_recording` (FR-7)."""

from __future__ import annotations

from fastmcp import FastMCP

from ktalk_mcp.client import KTalkError, get_shared_client
from ktalk_mcp.config import KTalkConfigError
from ktalk_mcp.download import download_recording_file
from ktalk_mcp.formatters import (
    format_download_result,
    format_participants,
    format_recording,
    format_recordings_list,
    format_summary,
    format_summary_by_type,
    render_tool_output,
    render_transcript_output,
)

_AUTH_ERRORS = (KTalkError, KTalkConfigError)


def register(mcp: FastMCP) -> None:
    """Регистрирует инструменты сущности «Запись» на переданном `mcp`."""

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
            top: Number of recordings per page (1-100, default 30). The API rejects
                values above 100 with HTTP 400.
            order: Sort order (byTimeNewFirst, byTimeOldFirst, byTitle,
                bySizeBigFirst, bySizeSmallFirst)
            page_token: Pagination token from previous response
            format: Output format — "raw" (JSON) or "markdown" (human-readable table)
        """
        try:
            client = get_shared_client()
            data = await client.list_recordings(
                query=query,
                start_from=start_from,
                start_to=start_to,
                top=top,
                order_mode=order,
                page_token=page_token,
            )
            return render_tool_output(data, format, format_recordings_list)
        except _AUTH_ERRORS as e:
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
            client = get_shared_client()
            data = await client.get_recording(recording_key)
            return render_tool_output(data, format, format_recording)
        except _AUTH_ERRORS as e:
            return str(e)

    @mcp.tool()
    async def ktalk_get_transcript(
        recording_key: str,
        format: str = "markdown",
        chunk: int = 0,
        chunk_size: int = 30000,
    ) -> str:
        """Get transcript of a KTalk recording (speech-to-text by speakers).

        Args:
            recording_key: Recording key/identifier (required)
            format: Output format — "raw" (JSON) or "markdown" (dialogue with timecodes)
            chunk: Chunk number. 0 = auto (returns full text if small, first chunk if large).
                1+ = specific chunk number for paged reading.
            chunk_size: Max characters per chunk (~7500 tokens at 30000). Soft limit —
                chunks split at utterance boundaries, never mid-utterance.
        """
        try:
            client = get_shared_client()
            data = await client.get_transcript(recording_key)
            return render_transcript_output(data, format, chunk, chunk_size)
        except _AUTH_ERRORS as e:
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
            client = get_shared_client()
            data = await client.get_summary(recording_key)
            return render_tool_output(data, format, format_summary)
        except _AUTH_ERRORS as e:
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
            client = get_shared_client()
            data = await client.get_summary_by_type(recording_key, summary_type)
            return render_tool_output(
                data, format, format_summary_by_type, summary_type=summary_type
            )
        except _AUTH_ERRORS as e:
            return str(e)

    @mcp.tool()
    async def ktalk_get_participants(
        recording_key: str,
        format: str = "markdown",
    ) -> str:
        """Get the full participant list of a KTalk recording (FR-8).

        Unlike the list/details response (capped by `maxParticipantCount`), this
        dedicated tool enriches the result so records with more participants than
        the default page shows are still complete.

        Args:
            recording_key: Recording key/identifier (required)
            format: Output format — "raw" (JSON) or "markdown"
        """
        try:
            client = get_shared_client()
            data = await client.get_full_participants(recording_key)
            return render_tool_output(data, format, format_participants)
        except _AUTH_ERRORS as e:
            return str(e)

    @mcp.tool()
    async def ktalk_download_recording(
        recording_key: str,
        target_path: str,
        quality: str | None = None,
        format: str = "markdown",
    ) -> str:
        """Download a KTalk recording video file to disk, streamed (FR-7).

        Args:
            recording_key: Recording key/identifier (required)
            target_path: Filesystem path to write the file to (required). Parent
                directories are created; an existing file is not overwritten.
            quality: Requested video quality (e.g. "900p"). None picks a sensible
                default from the record's available qualities.
            format: Output format for the returned metadata — "raw" (JSON) or "markdown"
        """
        try:
            client = get_shared_client()
            result = await download_recording_file(client, recording_key, target_path, quality)
            return render_tool_output(result, format, format_download_result)
        except _AUTH_ERRORS as e:
            return str(e)
