# Transcript Chunking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add chunking support to `ktalk_get_transcript` so large transcripts are automatically split into manageable pieces with metadata for paged reading.

**Architecture:** Format-then-split. The existing `format_transcript` formatter is unchanged. Two new chunking functions in `formatters.py` split the formatted output at utterance boundaries. The tool function in `server.py` orchestrates: format → check size → chunk if needed → wrap with metadata.

**Tech Stack:** Python 3.12+, fastmcp, existing project conventions.

**Spec:** `docs/superpowers/specs/2026-04-03-transcript-chunking-design.md`

---

### Task 1: `chunk_transcript_markdown` — tests

**Files:**
- Modify: `tests/test_formatters.py` (add new test class at end of file, after line 462)
- Reference: `src/ktalk_mcp/formatters.py:182-214` (existing `format_transcript`)

- [ ] **Step 1: Write failing tests for `chunk_transcript_markdown`**

Add to `tests/test_formatters.py`:

```python
class TestChunkTranscriptMarkdown:
    def test_small_text_single_chunk(self):
        from ktalk_mcp.formatters import chunk_transcript_markdown

        text = "# Транскрипт\n\n**Иванов Иван** [00:00:15]: Короткая фраза."
        result = chunk_transcript_markdown(text, chunk_size=5000)
        assert result == [text]

    def test_splits_at_utterance_boundary(self):
        from ktalk_mcp.formatters import chunk_transcript_markdown

        # Build transcript with 3 utterances, ~50 chars each
        utterances = [
            "**Иванов Иван** [00:00:15]: Первая реплика тестовая.",
            "**Петрова Мария** [00:01:00]: Вторая реплика тестовая.",
            "**Иванов Иван** [00:02:00]: Третья реплика тестовая.",
        ]
        text = "# Транскрипт\n\n" + "\n\n".join(utterances)

        # chunk_size enough for header + 2 utterances but not 3
        header_len = len("# Транскрипт\n\n")
        two_utterances_len = len(utterances[0]) + 2 + len(utterances[1])
        chunk_size = header_len + two_utterances_len + 10  # small margin

        result = chunk_transcript_markdown(text, chunk_size=chunk_size)
        assert len(result) == 2
        assert result[0].startswith("# Транскрипт\n\n")
        assert result[1].startswith("# Транскрипт\n\n")
        assert "Первая реплика" in result[0]
        assert "Вторая реплика" in result[0]
        assert "Третья реплика" in result[1]

    def test_single_long_utterance_not_split(self):
        from ktalk_mcp.formatters import chunk_transcript_markdown

        long_text = "A" * 10000
        text = f"# Транскрипт\n\n**Иванов Иван** [00:00:00]: {long_text}"
        result = chunk_transcript_markdown(text, chunk_size=100)
        # Single utterance should never be split even if > chunk_size
        assert len(result) == 1
        assert long_text in result[0]

    def test_empty_transcript(self):
        from ktalk_mcp.formatters import chunk_transcript_markdown

        text = "# Транскрипт\n\nТранскрипт пуст."
        result = chunk_transcript_markdown(text, chunk_size=5000)
        assert result == [text]

    def test_error_status_not_split(self):
        from ktalk_mcp.formatters import chunk_transcript_markdown

        text = "# Транскрипт\n\nОшибка транскрипции: failed"
        result = chunk_transcript_markdown(text, chunk_size=5000)
        assert result == [text]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_formatters.py::TestChunkTranscriptMarkdown -v`
Expected: FAIL — `ImportError: cannot import name 'chunk_transcript_markdown'`

- [ ] **Step 3: Commit**

```bash
git add tests/test_formatters.py
git commit -m "test: add failing tests for chunk_transcript_markdown"
```

---

### Task 2: `chunk_transcript_markdown` — implementation

**Files:**
- Modify: `src/ktalk_mcp/formatters.py` (add function after `format_transcript`, around line 215)

- [ ] **Step 1: Implement `chunk_transcript_markdown`**

Add after `format_transcript` in `src/ktalk_mcp/formatters.py` (after line 214):

```python
def chunk_transcript_markdown(text: str, chunk_size: int) -> list[str]:
    """Split formatted markdown transcript into chunks at utterance boundaries.

    Returns a list of chunk strings. Each chunk includes the header.
    A single utterance longer than chunk_size is kept intact (never split mid-utterance).
    """
    # Find header boundary (everything before first utterance)
    header = ""
    body = text
    # Header is "# Транскрипт\n\n" — find first utterance marker
    first_utterance = text.find("\n\n**")
    if first_utterance != -1:
        header = text[: first_utterance + 2]  # include the \n\n
        body = text[first_utterance + 2 :]    # utterances start here
    else:
        # No utterances (empty/error/in-progress) — return as-is
        return [text]

    # Split body into individual utterances by \n\n
    utterances = body.split("\n\n")
    # Filter empty strings from trailing newlines
    utterances = [u for u in utterances if u.strip()]

    if not utterances:
        return [text]

    chunks: list[str] = []
    current_parts: list[str] = []
    current_len = len(header)

    for utterance in utterances:
        utterance_len = len(utterance)
        # +2 for the \n\n separator between utterances
        added_len = utterance_len + (2 if current_parts else 0)

        if current_parts and current_len + added_len > chunk_size:
            # Finalize current chunk
            chunks.append(header + "\n\n".join(current_parts))
            current_parts = [utterance]
            current_len = len(header) + utterance_len
        else:
            current_parts.append(utterance)
            current_len += added_len

    # Don't forget the last chunk
    if current_parts:
        chunks.append(header + "\n\n".join(current_parts))

    return chunks
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_formatters.py::TestChunkTranscriptMarkdown -v`
Expected: all 5 tests PASS

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: all existing tests still PASS

- [ ] **Step 4: Commit**

```bash
git add src/ktalk_mcp/formatters.py
git commit -m "feat: add chunk_transcript_markdown function"
```

---

### Task 3: `chunk_transcript_raw` — tests

**Files:**
- Modify: `tests/test_formatters.py` (add new test class after `TestChunkTranscriptMarkdown`)

- [ ] **Step 1: Write failing tests for `chunk_transcript_raw`**

Add to `tests/test_formatters.py`:

```python
class TestChunkTranscriptRaw:
    def _make_transcript_data(self, num_chunks_per_track=1, num_tracks=2):
        """Helper to build transcript API data with given number of entries."""
        tracks = []
        time_offset = 0
        for t in range(num_tracks):
            chunks = []
            for c in range(num_chunks_per_track):
                chunks.append({
                    "chunkId": f"c-{t}-{c}",
                    "startTimeOffsetInMillis": time_offset,
                    "endTimeOffsetInMillis": time_offset + 15000,
                    "text": f"Реплика {t}-{c} " + "x" * 50,
                })
                time_offset += 15000
            tracks.append({
                "trackId": f"track-{t}",
                "speaker": {
                    "userInfo": {"surname": f"Speaker{t}", "firstname": f"Name{t}"},
                    "isAnonymous": False,
                },
                "chunks": chunks,
            })
        return {"status": "complete", "tracks": tracks}

    def test_small_data_single_chunk(self):
        from ktalk_mcp.formatters import chunk_transcript_raw

        data = self._make_transcript_data(num_chunks_per_track=1, num_tracks=2)
        result = chunk_transcript_raw(data, chunk_size=50000)
        assert len(result) == 1
        parsed = json.loads(result[0])
        assert isinstance(parsed, list)
        assert len(parsed) == 2

    def test_splits_into_multiple_chunks(self):
        from ktalk_mcp.formatters import chunk_transcript_raw

        data = self._make_transcript_data(num_chunks_per_track=5, num_tracks=2)
        # 10 entries total, each ~100+ chars serialized, use small chunk_size
        result = chunk_transcript_raw(data, chunk_size=500)
        assert len(result) > 1
        # All entries present across chunks
        all_entries = []
        for chunk_str in result:
            all_entries.extend(json.loads(chunk_str))
        assert len(all_entries) == 10

    def test_entries_sorted_by_time(self):
        from ktalk_mcp.formatters import chunk_transcript_raw

        data = self._make_transcript_data(num_chunks_per_track=3, num_tracks=2)
        result = chunk_transcript_raw(data, chunk_size=50000)
        entries = json.loads(result[0])
        timestamps = [e["timestamp_ms"] for e in entries]
        assert timestamps == sorted(timestamps)

    def test_empty_tracks(self):
        from ktalk_mcp.formatters import chunk_transcript_raw

        data = {"status": "complete", "tracks": []}
        result = chunk_transcript_raw(data, chunk_size=5000)
        assert len(result) == 1
        assert json.loads(result[0]) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_formatters.py::TestChunkTranscriptRaw -v`
Expected: FAIL — `ImportError: cannot import name 'chunk_transcript_raw'`

- [ ] **Step 3: Commit**

```bash
git add tests/test_formatters.py
git commit -m "test: add failing tests for chunk_transcript_raw"
```

---

### Task 4: `chunk_transcript_raw` — implementation

**Files:**
- Modify: `src/ktalk_mcp/formatters.py` (add function after `chunk_transcript_markdown`)

- [ ] **Step 1: Implement `chunk_transcript_raw`**

Add after `chunk_transcript_markdown` in `src/ktalk_mcp/formatters.py`:

```python
def chunk_transcript_raw(data: dict, chunk_size: int) -> list[str]:
    """Split transcript API data into chunks of JSON-serialized entry arrays.

    Extracts entries from tracks, sorts by time, groups into chunks
    where each chunk's serialized JSON length <= chunk_size.
    Returns a list of JSON strings (each is a JSON array of entry objects).
    """
    tracks = data.get("tracks") or []
    entries: list[dict] = []
    for track in tracks:
        speaker_name = _format_user_name(track.get("speaker"))
        for chunk in track.get("chunks") or []:
            entries.append({
                "speaker": speaker_name,
                "timestamp_ms": chunk.get("startTimeOffsetInMillis", 0),
                "text": chunk.get("text", ""),
            })

    entries.sort(key=lambda e: e["timestamp_ms"])

    if not entries:
        return [json.dumps([], ensure_ascii=False, indent=2)]

    chunks: list[str] = []
    current_entries: list[dict] = []
    current_len = 2  # "[]" base length

    for entry in entries:
        entry_json = json.dumps(entry, ensure_ascii=False)
        # +2 for ",\n" separator, +4 for indentation in pretty-print
        entry_len = len(entry_json) + 6
        if current_entries and current_len + entry_len > chunk_size:
            chunks.append(json.dumps(current_entries, ensure_ascii=False, indent=2))
            current_entries = [entry]
            current_len = 2 + len(entry_json) + 4
        else:
            current_entries.append(entry)
            current_len += entry_len

    if current_entries:
        chunks.append(json.dumps(current_entries, ensure_ascii=False, indent=2))

    return chunks
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `uv run pytest tests/test_formatters.py::TestChunkTranscriptRaw -v`
Expected: all 4 tests PASS

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -v`
Expected: all tests PASS

- [ ] **Step 4: Commit**

```bash
git add src/ktalk_mcp/formatters.py
git commit -m "feat: add chunk_transcript_raw function"
```

---

### Task 5: Integrate chunking into `ktalk_get_transcript` tool — tests

**Files:**
- Modify: `tests/test_formatters.py` (add integration-style test class at end)
- Reference: `src/ktalk_mcp/server.py:99-115` (current tool function)

- [ ] **Step 1: Write failing tests for tool-level chunking behavior**

Add to `tests/test_formatters.py`:

```python
class TestTranscriptChunkingIntegration:
    """Test the complete chunking flow: format → chunk → metadata."""

    def _make_long_transcript_data(self, num_entries: int) -> dict:
        """Build transcript data that produces a large markdown output."""
        tracks = [{
            "trackId": "track-0",
            "speaker": {
                "userInfo": {"surname": "Тестов", "firstname": "Тест"},
                "isAnonymous": False,
            },
            "chunks": [
                {
                    "chunkId": f"c{i}",
                    "startTimeOffsetInMillis": i * 15000,
                    "text": f"Реплика номер {i}. " + "Текст " * 20,
                }
                for i in range(num_entries)
            ],
        }]
        return {"status": "complete", "tracks": tracks}

    def test_chunk0_small_returns_plain_string(self):
        """chunk=0 + small transcript → plain string (backward compat)."""
        from ktalk_mcp.formatters import format_transcript, chunk_transcript_markdown

        data = self._make_long_transcript_data(3)
        text = format_transcript(data)
        chunks = chunk_transcript_markdown(text, chunk_size=50000)
        assert len(chunks) == 1
        # When single chunk, tool should return plain text
        assert chunks[0] == text

    def test_chunk0_large_returns_first_chunk(self):
        """chunk=0 + large transcript → auto-chunks, returns first."""
        from ktalk_mcp.formatters import format_transcript, chunk_transcript_markdown

        data = self._make_long_transcript_data(50)
        text = format_transcript(data)
        assert len(text) > 1000  # sanity check it's big
        chunks = chunk_transcript_markdown(text, chunk_size=1000)
        assert len(chunks) > 1

    def test_chunk_metadata_structure(self):
        """Verify metadata JSON structure."""
        from ktalk_mcp.formatters import format_transcript, chunk_transcript_markdown

        data = self._make_long_transcript_data(50)
        text = format_transcript(data)
        chunks = chunk_transcript_markdown(text, chunk_size=1000)
        total = len(chunks)

        # Simulate what the tool would return for chunk=2
        metadata = {
            "result": chunks[1],
            "chunk": 2,
            "total_chunks": total,
            "has_more": 2 < total,
            "total_characters": len(text),
        }
        result = json.dumps(metadata, ensure_ascii=False, indent=2)
        parsed = json.loads(result)
        assert parsed["chunk"] == 2
        assert parsed["total_chunks"] == total
        assert parsed["has_more"] is True
        assert parsed["total_characters"] == len(text)
        assert "# Транскрипт" in parsed["result"]
```

- [ ] **Step 2: Run tests to verify they pass** (these test formatter functions which already exist)

Run: `uv run pytest tests/test_formatters.py::TestTranscriptChunkingIntegration -v`
Expected: PASS (these use already-implemented functions)

- [ ] **Step 3: Commit**

```bash
git add tests/test_formatters.py
git commit -m "test: add integration tests for transcript chunking flow"
```

---

### Task 6: Modify `ktalk_get_transcript` tool in `server.py`

**Files:**
- Modify: `src/ktalk_mcp/server.py:99-115` (tool function)
- Modify: `src/ktalk_mcp/server.py:9-16` (imports)

- [ ] **Step 1: Update imports in `server.py`**

In `src/ktalk_mcp/server.py`, change the import block (lines 9-16):

```python
from ktalk_mcp.formatters import (
    format_raw,
    format_recording,
    format_recordings_list,
    format_summary,
    format_summary_by_type,
    format_transcript,
)
```

to:

```python
from ktalk_mcp.formatters import (
    chunk_transcript_markdown,
    chunk_transcript_raw,
    format_raw,
    format_recording,
    format_recordings_list,
    format_summary,
    format_summary_by_type,
    format_transcript,
)
```

- [ ] **Step 2: Rewrite `ktalk_get_transcript` tool function**

Replace the existing `ktalk_get_transcript` function (lines 99-115) with:

```python
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
        client = _get_client()
        data = await client.get_transcript(recording_key)

        # Format the full transcript
        if format == "raw":
            full_text = format_raw(data)
        else:
            full_text = format_transcript(data)

        total_characters = len(full_text)

        # Determine if chunking is needed
        if chunk == 0 and total_characters <= chunk_size:
            # Small transcript — return as-is (backward compatible)
            return full_text

        # Split into chunks
        if format == "raw":
            chunks = chunk_transcript_raw(data, chunk_size)
        else:
            chunks = chunk_transcript_markdown(full_text, chunk_size)

        total_chunks = len(chunks)

        # For chunk=0 (auto), serve first chunk
        chunk_index = 0 if chunk == 0 else chunk - 1

        if chunk_index < 0 or chunk_index >= total_chunks:
            return f"Чанк {chunk} не существует. Всего чанков: {total_chunks}"

        return json.dumps({
            "result": chunks[chunk_index],
            "chunk": chunk_index + 1,
            "total_chunks": total_chunks,
            "has_more": chunk_index + 1 < total_chunks,
            "total_characters": total_characters,
        }, ensure_ascii=False, indent=2)

    except KTalkError as e:
        return str(e)
```

- [ ] **Step 3: Add `json` import to `server.py`**

Add at the top of `src/ktalk_mcp/server.py` (after line 2, `from __future__ import annotations`):

```python
import json
```

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest -v`
Expected: all tests PASS

- [ ] **Step 5: Run linter**

Run: `uv run ruff check .`
Expected: no errors

- [ ] **Step 6: Commit**

```bash
git add src/ktalk_mcp/server.py
git commit -m "feat: add chunking support to ktalk_get_transcript"
```

---

### Task 7: Update `CLAUDE.md` and verify end-to-end

**Files:**
- Modify: `CLAUDE.md` (update tool description)

- [ ] **Step 1: Update CLAUDE.md**

In the `## API Reference` or `## Architecture` section, add a note about chunking:

After the line `- Каждый MCP tool принимает параметр `format`: "raw" (JSON as-is) или "markdown" (human-readable)`, add:

```
- `ktalk_get_transcript` поддерживает чанкинг: `chunk` (0=авто, 1+=номер чанка), `chunk_size` (символов, по умолчанию 30000)
```

- [ ] **Step 2: Run full test suite one final time**

Run: `uv run pytest -v`
Expected: all tests PASS

Run: `uv run ruff check .`
Expected: no errors

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document transcript chunking in CLAUDE.md"
```

---

## Verification

After all tasks are complete:

1. **Unit tests:** `uv run pytest tests/test_formatters.py -v` — all chunking tests pass
2. **Full suite:** `uv run pytest -v` — no regressions
3. **Linter:** `uv run ruff check .` — clean
4. **Manual check** (if KTalk instance available): `uv run ktalk-mcp` and call `ktalk_get_transcript` with a long recording to see chunking in action
