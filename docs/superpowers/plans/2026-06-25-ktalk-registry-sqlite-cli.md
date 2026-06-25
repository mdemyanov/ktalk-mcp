# KTalk Registry: SQLite + CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the Kontur Talk recordings registry off hand-edited markdown tables onto a SQLite operational store driven by a new `ktalk` CLI, while leaving the MCP server as the content channel.

**Architecture:** Add two new modules to the existing `ktalk_mcp` package — `registry.py` (stdlib `sqlite3` data layer with WAL) and `cli.py` (argparse subcommands). They reuse `client.py`/`config.py`. A second console entry point `ktalk` is registered. The vault skill/agent stop parsing markdown and instead call the CLI; `ktalk export` regenerates a read-only markdown mirror for git.

**Tech Stack:** Python 3.12+, stdlib `sqlite3` + `argparse`, existing httpx `KTalkClient`, pydantic-settings, pytest + pytest-httpx, ruff.

## Global Constraints

- Python `>=3.12`; no new runtime dependencies — `sqlite3` and `argparse` are stdlib.
- ruff config is fixed: `line-length = 100`, lint `select = ["E", "F", "I", "N", "W"]`, `target-version = "py312"`. Every file must pass `uv run ruff check .`.
- pytest runs with `asyncio_mode = "auto"`; async tests need no decorator. Tests import the module under test *inside* the test body (existing convention in `tests/test_client.py`).
- New `.py` files start with `from __future__ import annotations`.
- All user-facing CLI text and error messages are in Russian (repo convention).
- `--json` output contract: valid JSON to **stdout** only; errors go to **stderr** with a non-zero exit code. The skill/agent parse stdout.
- SQLite: open every connection with `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000`; one transaction per mutating operation (commit after each write).
- Dates are stored as `YYYY-MM-DD` strings. Functions that stamp "now" take an explicit `now: str` parameter (default via `today_str()`) so tests are deterministic.
- Default DB path: `95_TRANSCRIPTS/.registry.db` (relative to cwd). Resolution precedence: `--db` flag > `KTALK_REGISTRY_DB` env > default.

---

## File Structure

- `src/ktalk_mcp/config.py` — **modify**: add `DEFAULT_DB_PATH` constant and `resolve_db_path(cli_db)` helper (reads `KTALK_REGISTRY_DB` directly via `os.environ`, does **not** touch the token-requiring `Settings`).
- `src/ktalk_mcp/registry.py` — **create**: schema DDL, `Registry` class (connection + pragmas + CRUD + status transitions + expiration + meta), API→row mappers, markdown migration parsers, markdown-mirror renderer, `today_str()`.
- `src/ktalk_mcp/cli.py` — **create**: argparse parser, subcommand handlers, `main(argv) -> int`.
- `pyproject.toml` — **modify**: add `ktalk = "ktalk_mcp.cli:main"` script.
- `src/ktalk_mcp/__init__.py` — **modify**: (version already 0.3.0; bump to 0.4.0 with the feature).
- `tests/test_registry.py` — **create**: schema, CRUD, dedup, expiration, transitions, participants, mappers, concurrency.
- `tests/test_migration.py` — **create**: parse fixtures → rows/participants, idempotency, dry-run.
- `tests/test_cli.py` — **create**: each subcommand's text + `--json` output, exit codes, sync via pytest-httpx, export.
- `tests/fixtures/registry.md`, `tests/fixtures/registry-archive-2026-04.md` — **create**: trimmed migration fixtures.

Part 2 (vault skill/agent/docs) lives under `/Users/mdemyanov/Documents/naumen-cto` and is covered by the final tasks.

---

### Task 1: DB path resolution in config

**Files:**
- Modify: `src/ktalk_mcp/config.py`
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `DEFAULT_DB_PATH: str = "95_TRANSCRIPTS/.registry.db"`; `resolve_db_path(cli_db: str | None = None) -> pathlib.Path`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py` (create the file with this content if it does not yet exist):

```python
from pathlib import Path


def test_resolve_db_path_default(monkeypatch):
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)
    from ktalk_mcp.config import DEFAULT_DB_PATH, resolve_db_path

    assert resolve_db_path() == Path(DEFAULT_DB_PATH)


def test_resolve_db_path_env(monkeypatch):
    monkeypatch.setenv("KTALK_REGISTRY_DB", "/tmp/from-env.db")
    from ktalk_mcp.config import resolve_db_path

    assert resolve_db_path() == Path("/tmp/from-env.db")


def test_resolve_db_path_flag_wins(monkeypatch):
    monkeypatch.setenv("KTALK_REGISTRY_DB", "/tmp/from-env.db")
    from ktalk_mcp.config import resolve_db_path

    assert resolve_db_path("/tmp/from-flag.db") == Path("/tmp/from-flag.db")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `ImportError: cannot import name 'resolve_db_path'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/ktalk_mcp/config.py`:

```python
import os
from pathlib import Path

DEFAULT_DB_PATH = "95_TRANSCRIPTS/.registry.db"


def resolve_db_path(cli_db: str | None = None) -> Path:
    """Resolve the registry DB path: --db flag > KTALK_REGISTRY_DB env > default."""
    if cli_db:
        return Path(cli_db)
    env = os.environ.get("KTALK_REGISTRY_DB")
    if env:
        return Path(env)
    return Path(DEFAULT_DB_PATH)
```

Move the `import os` / `from pathlib import Path` lines to the top of the file with the other imports to satisfy ruff `E402`/`I`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config.py -v && uv run ruff check src/ktalk_mcp/config.py`
Expected: PASS, no ruff errors.

- [ ] **Step 5: Commit**

```bash
git add src/ktalk_mcp/config.py tests/test_config.py
git commit -m "feat: add registry DB path resolution to config"
```

---

### Task 2: Registry schema, connection, and meta store

**Files:**
- Create: `src/ktalk_mcp/registry.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Produces:
  - `today_str() -> str` (returns `date.today().isoformat()`).
  - `class Registry` with `__init__(self, db_path: str | Path)`, `close(self) -> None`, context-manager protocol (`__enter__`/`__exit__`).
  - `Registry.get_meta(self, key: str) -> str | None`, `Registry.set_meta(self, key: str, value: str) -> None`.
  - On construction: applies `journal_mode=WAL` + `busy_timeout=5000`, creates schema if absent, sets `meta['schema_version'] = '1'`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_registry.py`:

```python
from __future__ import annotations

from pathlib import Path


def test_schema_and_pragmas(tmp_path: Path):
    from ktalk_mcp.registry import Registry

    db = tmp_path / "r.db"
    with Registry(db) as reg:
        mode = reg._conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode.lower() == "wal"
        tables = {
            row[0]
            for row in reg._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"recordings", "participants", "meta"} <= tables
        assert reg.get_meta("schema_version") == "1"


def test_meta_roundtrip(tmp_path: Path):
    from ktalk_mcp.registry import Registry

    with Registry(tmp_path / "r.db") as reg:
        assert reg.get_meta("missing") is None
        reg.set_meta("last_synced", "2026-06-25")
        assert reg.get_meta("last_synced") == "2026-06-25"
        reg.set_meta("last_synced", "2026-06-26")  # upsert overwrites
        assert reg.get_meta("last_synced") == "2026-06-26"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ktalk_mcp.registry'`

- [ ] **Step 3: Write minimal implementation**

Create `src/ktalk_mcp/registry.py`:

```python
"""SQLite operational store for the KTalk recordings registry."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

SCHEMA_VERSION = "1"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS recordings (
    recording_id    TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    date            TEXT NOT NULL,
    duration_min    INTEGER,
    status          TEXT NOT NULL,
    meeting_type    TEXT,
    transcript_path TEXT,
    protocol_path   TEXT,
    processed_at    TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    raw_json        TEXT
);

CREATE TABLE IF NOT EXISTS participants (
    recording_id TEXT NOT NULL REFERENCES recordings(recording_id) ON DELETE CASCADE,
    ktalk_id     TEXT NOT NULL,
    name         TEXT NOT NULL,
    vault_id     TEXT,
    PRIMARY KEY (recording_id, ktalk_id)
);

CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_recordings_status ON recordings(status);
CREATE INDEX IF NOT EXISTS idx_recordings_date   ON recordings(date);
"""


def today_str() -> str:
    """Today's date as YYYY-MM-DD."""
    return date.today().isoformat()


class Registry:
    """SQLite-backed registry. One connection per instance; commit per write."""

    def __init__(self, db_path: str | Path) -> None:
        self._conn = sqlite3.connect(str(db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        if self.get_meta("schema_version") is None:
            self.set_meta("schema_version", SCHEMA_VERSION)

    def __enter__(self) -> Registry:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def close(self) -> None:
        self._conn.close()

    def get_meta(self, key: str) -> str | None:
        row = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
        self._conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_registry.py -v && uv run ruff check src/ktalk_mcp/registry.py`
Expected: PASS, no ruff errors.

- [ ] **Step 5: Commit**

```bash
git add src/ktalk_mcp/registry.py tests/test_registry.py
git commit -m "feat: add registry SQLite schema, connection, and meta store"
```

---

### Task 2.5: Recording upsert, dedup, and participants

**Files:**
- Modify: `src/ktalk_mcp/registry.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Consumes: `Registry`, `today_str` from Task 2.
- Produces (methods on `Registry`):
  - `upsert_recording(self, fields: dict, participants: list[dict] | None = None, *, now: str | None = None) -> str` — inserts when new (returns `"inserted"`), or updates mutable content fields when the `recording_id` already exists (returns `"updated"`). On insert: sets `status` from `fields.get("status", "new")`, `created_at`/`updated_at` to `now`. On update: refreshes `name`, `date`, `duration_min`, `raw_json`, `updated_at` but **never** overwrites `status`, paths, or `processed_at` (idempotent re-sync). `fields` keys: `recording_id` (required), `name`, `date`, `duration_min`, `raw_json`, optional `status`. If `participants` given, replaces that recording's participant rows.
  - `get_recording(self, recording_id: str) -> dict | None` — row as dict (sqlite3.Row → dict), or `None`.
  - `get_participants(self, recording_id: str) -> list[dict]` — list of `{recording_id, ktalk_id, name, vault_id}` dicts ordered by `ktalk_id`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_registry.py`:

```python
def _rec(rid: str, **over):
    base = {
        "recording_id": rid,
        "name": "Standup",
        "date": "2026-06-20",
        "duration_min": 30,
        "raw_json": "{}",
    }
    base.update(over)
    return base


def test_upsert_inserts_with_default_new_status(tmp_path: Path):
    from ktalk_mcp.registry import Registry

    with Registry(tmp_path / "r.db") as reg:
        assert reg.upsert_recording(_rec("a"), now="2026-06-20") == "inserted"
        row = reg.get_recording("a")
        assert row["status"] == "new"
        assert row["name"] == "Standup"
        assert row["created_at"] == "2026-06-20"
        assert reg.get_recording("missing") is None


def test_upsert_is_idempotent_and_preserves_status(tmp_path: Path):
    from ktalk_mcp.registry import Registry

    with Registry(tmp_path / "r.db") as reg:
        reg.upsert_recording(_rec("a"), now="2026-06-20")
        reg.set_status("a", "done")  # simulate processing
        # Re-sync the same id with a changed title — must NOT revert status.
        result = reg.upsert_recording(_rec("a", name="Standup (renamed)"), now="2026-06-21")
        assert result == "updated"
        row = reg.get_recording("a")
        assert row["status"] == "done"
        assert row["name"] == "Standup (renamed)"
        assert row["updated_at"] == "2026-06-21"
        # No duplicate rows.
        count = reg._conn.execute("SELECT COUNT(*) FROM recordings").fetchone()[0]
        assert count == 1


def test_upsert_replaces_participants(tmp_path: Path):
    from ktalk_mcp.registry import Registry

    with Registry(tmp_path / "r.db") as reg:
        reg.upsert_recording(
            _rec("a"),
            participants=[
                {"ktalk_id": "668", "name": "Демьянов Максим"},
                {"ktalk_id": "412", "name": "Муратов Алексей"},
            ],
            now="2026-06-20",
        )
        parts = reg.get_participants("a")
        assert [p["ktalk_id"] for p in parts] == ["412", "668"]
        assert parts[0]["vault_id"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_registry.py -k upsert -v`
Expected: FAIL with `AttributeError: 'Registry' object has no attribute 'upsert_recording'`
(Note: `test_upsert_is_idempotent_...` also exercises `set_status`, added in Task 3 — if running before Task 3, expect that one to error on `set_status`; that is acceptable, it passes once Task 3 lands. To keep this task green standalone, also add `set_status` in Step 3 below.)

- [ ] **Step 3: Write minimal implementation**

Append to `src/ktalk_mcp/registry.py`:

```python
    def _row_to_dict(self, row: sqlite3.Row | None) -> dict | None:
        return dict(row) if row is not None else None

    def get_recording(self, recording_id: str) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM recordings WHERE recording_id=?", (recording_id,)
        ).fetchone()
        return self._row_to_dict(row)

    def get_participants(self, recording_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT * FROM participants WHERE recording_id=? ORDER BY ktalk_id",
            (recording_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert_recording(
        self,
        fields: dict,
        participants: list[dict] | None = None,
        *,
        now: str | None = None,
    ) -> str:
        now = now or today_str()
        rid = fields["recording_id"]
        existing = self.get_recording(rid)
        if existing is None:
            self._conn.execute(
                "INSERT INTO recordings("
                "recording_id, name, date, duration_min, status, raw_json, "
                "created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    rid,
                    fields.get("name", ""),
                    fields.get("date", ""),
                    fields.get("duration_min"),
                    fields.get("status", "new"),
                    fields.get("raw_json"),
                    now,
                    now,
                ),
            )
            result = "inserted"
        else:
            self._conn.execute(
                "UPDATE recordings SET name=?, date=?, duration_min=?, raw_json=?, "
                "updated_at=? WHERE recording_id=?",
                (
                    fields.get("name", existing["name"]),
                    fields.get("date", existing["date"]),
                    fields.get("duration_min", existing["duration_min"]),
                    fields.get("raw_json", existing["raw_json"]),
                    now,
                    rid,
                ),
            )
            result = "updated"
        if participants is not None:
            self._conn.execute(
                "DELETE FROM participants WHERE recording_id=?", (rid,)
            )
            self._conn.executemany(
                "INSERT INTO participants(recording_id, ktalk_id, name, vault_id) "
                "VALUES(?,?,?,?)",
                [
                    (rid, p["ktalk_id"], p["name"], p.get("vault_id"))
                    for p in participants
                ],
            )
        self._conn.commit()
        return result
```

(`set_status` is implemented in Task 3; if executing tasks strictly in order, temporarily add a minimal `set_status` here or run `-k upsert and not idempotent` first, then complete Task 3.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_registry.py -v && uv run ruff check src/ktalk_mcp/registry.py`
Expected: PASS (assuming Task 3 `set_status` present), no ruff errors.

- [ ] **Step 5: Commit**

```bash
git add src/ktalk_mcp/registry.py tests/test_registry.py
git commit -m "feat: add recording upsert/dedup and participants to registry"
```

---

### Task 3: Status transitions

**Files:**
- Modify: `src/ktalk_mcp/registry.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Consumes: `Registry.get_recording`, `today_str`.
- Produces (methods on `Registry`):
  - `set_status(self, recording_id: str, status: str, *, now: str | None = None, **fields) -> None` — sets `status`, refreshes `updated_at`; accepts optional `transcript_path`, `protocol_path`, `meeting_type`, `processed_at` kwargs to update alongside. Raises `KeyError` if the recording does not exist. Validates `status` is one of `new|processing|done|skipped|partial`, else `ValueError`.
  - `mark_processing(self, recording_id, *, now=None)` → status `processing`.
  - `mark_done(self, recording_id, *, transcript_path=None, protocol_path=None, meeting_type=None, now=None)` → status `done`, sets `processed_at=now`.
  - `mark_partial(self, recording_id, *, transcript_path=None, protocol_path=None, now=None)` → status `partial`.
  - `mark_skipped(self, recording_id, *, now=None)` → status `skipped`, sets `processed_at=now`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_registry.py`:

```python
VALID = {"new", "processing", "done", "skipped", "partial"}


def test_mark_done_sets_paths_and_processed_at(tmp_path: Path):
    from ktalk_mcp.registry import Registry

    with Registry(tmp_path / "r.db") as reg:
        reg.upsert_recording(_rec("a"), now="2026-06-20")
        reg.mark_processing("a", now="2026-06-21")
        assert reg.get_recording("a")["status"] == "processing"
        reg.mark_done(
            "a",
            transcript_path="95_TRANSCRIPTS/2026/x.md",
            protocol_path="10_PEOPLE/x.md",
            meeting_type="1-1",
            now="2026-06-22",
        )
        row = reg.get_recording("a")
        assert row["status"] == "done"
        assert row["transcript_path"] == "95_TRANSCRIPTS/2026/x.md"
        assert row["protocol_path"] == "10_PEOPLE/x.md"
        assert row["meeting_type"] == "1-1"
        assert row["processed_at"] == "2026-06-22"


def test_set_status_rejects_unknown_status(tmp_path: Path):
    import pytest

    from ktalk_mcp.registry import Registry

    with Registry(tmp_path / "r.db") as reg:
        reg.upsert_recording(_rec("a"), now="2026-06-20")
        with pytest.raises(ValueError):
            reg.set_status("a", "bogus")


def test_set_status_missing_recording_raises(tmp_path: Path):
    import pytest

    from ktalk_mcp.registry import Registry

    with Registry(tmp_path / "r.db") as reg:
        with pytest.raises(KeyError):
            reg.set_status("nope", "done")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_registry.py -k "status or mark_done" -v`
Expected: FAIL — `set_status`/`mark_done` not defined.

- [ ] **Step 3: Write minimal implementation**

Append to `src/ktalk_mcp/registry.py` (add `_VALID_STATUSES` near the top constants):

```python
_VALID_STATUSES = {"new", "processing", "done", "skipped", "partial"}
```

```python
    def set_status(
        self, recording_id: str, status: str, *, now: str | None = None, **fields
    ) -> None:
        if status not in _VALID_STATUSES:
            raise ValueError(f"Недопустимый статус: {status}")
        if self.get_recording(recording_id) is None:
            raise KeyError(recording_id)
        now = now or today_str()
        cols = ["status=?", "updated_at=?"]
        vals: list = [status, now]
        for key in ("transcript_path", "protocol_path", "meeting_type", "processed_at"):
            if key in fields:
                cols.append(f"{key}=?")
                vals.append(fields[key])
        vals.append(recording_id)
        self._conn.execute(
            f"UPDATE recordings SET {', '.join(cols)} WHERE recording_id=?", vals
        )
        self._conn.commit()

    def mark_processing(self, recording_id: str, *, now: str | None = None) -> None:
        self.set_status(recording_id, "processing", now=now)

    def mark_done(
        self,
        recording_id: str,
        *,
        transcript_path: str | None = None,
        protocol_path: str | None = None,
        meeting_type: str | None = None,
        now: str | None = None,
    ) -> None:
        now = now or today_str()
        self.set_status(
            recording_id,
            "done",
            now=now,
            transcript_path=transcript_path,
            protocol_path=protocol_path,
            meeting_type=meeting_type,
            processed_at=now,
        )

    def mark_partial(
        self,
        recording_id: str,
        *,
        transcript_path: str | None = None,
        protocol_path: str | None = None,
        now: str | None = None,
    ) -> None:
        self.set_status(
            recording_id,
            "partial",
            now=now,
            transcript_path=transcript_path,
            protocol_path=protocol_path,
        )

    def mark_skipped(self, recording_id: str, *, now: str | None = None) -> None:
        now = now or today_str()
        self.set_status(recording_id, "skipped", now=now, processed_at=now)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_registry.py -v && uv run ruff check src/ktalk_mcp/registry.py`
Expected: PASS, no ruff errors.

- [ ] **Step 5: Commit**

```bash
git add src/ktalk_mcp/registry.py tests/test_registry.py
git commit -m "feat: add status transitions to registry"
```

---

### Task 4: list_recordings, set_vault_id, and expiration

**Files:**
- Modify: `src/ktalk_mcp/registry.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Consumes: `Registry`, `today_str`.
- Produces (methods on `Registry`):
  - `list_recordings(self, status: str | None = None) -> list[dict]` — all recordings (optionally filtered by status), ordered by `date DESC, recording_id`.
  - `set_vault_id(self, recording_id: str, ktalk_id: str, vault_id: str) -> None` — sets a participant's `vault_id`; raises `KeyError` if no such participant row.
  - `expire_new(self, *, now: str | None = None, days: int = 7) -> list[str]` — moves `new` recordings strictly older than `days` (i.e. `date < now - days`) to `skipped`, sets their `processed_at=now`, returns the list of expired `recording_id`s. A recording exactly `days` old is **not** expired.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_registry.py`:

```python
def test_list_recordings_filter_and_order(tmp_path: Path):
    from ktalk_mcp.registry import Registry

    with Registry(tmp_path / "r.db") as reg:
        reg.upsert_recording(_rec("a", date="2026-06-20"), now="2026-06-20")
        reg.upsert_recording(_rec("b", date="2026-06-22"), now="2026-06-22")
        reg.set_status("b", "done")
        all_recs = reg.list_recordings()
        assert [r["recording_id"] for r in all_recs] == ["b", "a"]  # date DESC
        new_only = reg.list_recordings(status="new")
        assert [r["recording_id"] for r in new_only] == ["a"]


def test_set_vault_id(tmp_path: Path):
    import pytest

    from ktalk_mcp.registry import Registry

    with Registry(tmp_path / "r.db") as reg:
        reg.upsert_recording(
            _rec("a"),
            participants=[{"ktalk_id": "668", "name": "Демьянов Максим"}],
            now="2026-06-20",
        )
        reg.set_vault_id("a", "668", "mdemyanov")
        assert reg.get_participants("a")[0]["vault_id"] == "mdemyanov"
        with pytest.raises(KeyError):
            reg.set_vault_id("a", "999", "x")


def test_expire_new_boundary_exactly_7_days(tmp_path: Path):
    from ktalk_mcp.registry import Registry

    with Registry(tmp_path / "r.db") as reg:
        # now = 2026-06-25, days = 7 -> cutoff 2026-06-18
        reg.upsert_recording(_rec("keep", date="2026-06-18"), now="2026-06-18")  # age 7
        reg.upsert_recording(_rec("gone", date="2026-06-17"), now="2026-06-17")  # age 8
        reg.upsert_recording(_rec("fresh", date="2026-06-25"), now="2026-06-25")
        reg.upsert_recording(_rec("done", date="2026-06-10"), now="2026-06-10")
        reg.set_status("done", "done")  # not 'new' -> never expired

        expired = reg.expire_new(now="2026-06-25", days=7)
        assert expired == ["gone"]
        assert reg.get_recording("keep")["status"] == "new"
        assert reg.get_recording("gone")["status"] == "skipped"
        assert reg.get_recording("gone")["processed_at"] == "2026-06-25"
        assert reg.get_recording("done")["status"] == "done"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_registry.py -k "list_recordings or vault_id or expire" -v`
Expected: FAIL — methods not defined.

- [ ] **Step 3: Write minimal implementation**

Append to `src/ktalk_mcp/registry.py` (add `from datetime import date, timedelta` — extend the existing datetime import):

```python
    def list_recordings(self, status: str | None = None) -> list[dict]:
        if status is None:
            rows = self._conn.execute(
                "SELECT * FROM recordings ORDER BY date DESC, recording_id"
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM recordings WHERE status=? ORDER BY date DESC, recording_id",
                (status,),
            ).fetchall()
        return [dict(r) for r in rows]

    def set_vault_id(self, recording_id: str, ktalk_id: str, vault_id: str) -> None:
        cur = self._conn.execute(
            "UPDATE participants SET vault_id=? WHERE recording_id=? AND ktalk_id=?",
            (vault_id, recording_id, ktalk_id),
        )
        if cur.rowcount == 0:
            raise KeyError((recording_id, ktalk_id))
        self._conn.commit()

    def expire_new(self, *, now: str | None = None, days: int = 7) -> list[str]:
        now = now or today_str()
        cutoff = (date.fromisoformat(now) - timedelta(days=days)).isoformat()
        rows = self._conn.execute(
            "SELECT recording_id FROM recordings WHERE status='new' AND date < ? "
            "ORDER BY recording_id",
            (cutoff,),
        ).fetchall()
        expired = [r[0] for r in rows]
        if expired:
            self._conn.execute(
                "UPDATE recordings SET status='skipped', processed_at=?, updated_at=? "
                "WHERE status='new' AND date < ?",
                (now, now, cutoff),
            )
            self._conn.commit()
        return expired
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_registry.py -v && uv run ruff check src/ktalk_mcp/registry.py`
Expected: PASS, no ruff errors.

- [ ] **Step 5: Commit**

```bash
git add src/ktalk_mcp/registry.py tests/test_registry.py
git commit -m "feat: add list, set-vault-id, and expiration to registry"
```

---

### Task 5: Concurrent writers safety

**Files:**
- Test: `tests/test_registry.py`

**Interfaces:**
- Consumes: `Registry` (WAL + busy_timeout already configured in Task 2). No new production code expected — this task proves the concurrency guarantee and only adds code if the test fails.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_registry.py`:

```python
def test_concurrent_writers_both_persist(tmp_path: Path):
    import threading

    from ktalk_mcp.registry import Registry

    db = tmp_path / "r.db"
    # Seed two recordings via one connection, then close it.
    with Registry(db) as seed:
        seed.upsert_recording(_rec("a"), now="2026-06-20")
        seed.upsert_recording(_rec("b"), now="2026-06-20")

    errors: list[Exception] = []

    def writer(rid: str):
        try:
            reg = Registry(db)
            reg.mark_done(rid, transcript_path=f"t-{rid}.md", now="2026-06-22")
            reg.close()
        except Exception as exc:  # noqa: BLE001 - test captures any failure
            errors.append(exc)

    t1 = threading.Thread(target=writer, args=("a",))
    t2 = threading.Thread(target=writer, args=("b",))
    t1.start(); t2.start(); t1.join(); t2.join()

    assert errors == []
    with Registry(db) as reg:
        assert reg.get_recording("a")["status"] == "done"
        assert reg.get_recording("b")["status"] == "done"
        assert reg.get_recording("a")["transcript_path"] == "t-a.md"
        assert reg.get_recording("b")["transcript_path"] == "t-b.md"
```

- [ ] **Step 2: Run test to verify it passes (concurrency already handled)**

Run: `uv run pytest tests/test_registry.py -k concurrent -v`
Expected: PASS (WAL + `busy_timeout=5000` serialize the two writes). If it fails with `database is locked`, raise `busy_timeout` and ensure each method commits promptly — do **not** introduce a global lock.

- [ ] **Step 3: Commit**

```bash
git add tests/test_registry.py
git commit -m "test: prove concurrent registry writers both persist"
```

---

### Task 6: API recording → row mappers

**Files:**
- Modify: `src/ktalk_mcp/registry.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Produces (module-level functions in `registry.py`):
  - `recording_fields_from_api(rec: dict) -> dict` — maps a KTalk `/api/recordings` entity to `{recording_id, name, date, duration_min, raw_json}`. `recording_id = rec["id"]` (fallback `rec["key"]`); `name = rec.get("title", "Без названия")`; `date` = `createdDate` truncated to `YYYY-MM-DD` (first 10 chars after normalizing); `duration_min = round(rec.get("duration", 0) / 60)`; `raw_json = json.dumps(rec, ensure_ascii=False)`.
  - `participants_from_api(rec: dict) -> list[dict]` — for each entry in `rec.get("participants", [])`, extract `ktalk_id` = `userInfo.key` (fallback `userInfo.login`), `name` via surname+firstname (fallback login → anonymousName → "Неизвестный"). Skips participants with no resolvable `ktalk_id`. Dedupes by `ktalk_id`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_registry.py`:

```python
def test_recording_fields_from_api():
    from ktalk_mcp.registry import recording_fields_from_api

    rec = {
        "id": "OowNhGRNjLOG3MshMC6i",
        "title": "Алексей 🤝 Максим",
        "createdDate": "2026-06-25T09:30:00Z",
        "duration": 3660,
    }
    fields = recording_fields_from_api(rec)
    assert fields["recording_id"] == "OowNhGRNjLOG3MshMC6i"
    assert fields["name"] == "Алексей 🤝 Максим"
    assert fields["date"] == "2026-06-25"
    assert fields["duration_min"] == 61
    assert '"id": "OowNhGRNjLOG3MshMC6i"' in fields["raw_json"]


def test_participants_from_api():
    from ktalk_mcp.registry import participants_from_api

    rec = {
        "participants": [
            {"userInfo": {"key": "668", "surname": "Демьянов", "firstname": "Максим"}},
            {"userInfo": {"key": "412", "surname": "Муратов", "firstname": "Алексей"}},
            {"userInfo": {"key": "668", "surname": "Демьянов", "firstname": "Максим"}},
            {"isAnonymous": True, "anonymousName": "Гость"},  # no ktalk_id -> skipped
        ]
    }
    parts = participants_from_api(rec)
    ids = sorted(p["ktalk_id"] for p in parts)
    assert ids == ["412", "668"]
    by_id = {p["ktalk_id"]: p["name"] for p in parts}
    assert by_id["668"] == "Демьянов Максим"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_registry.py -k "from_api" -v`
Expected: FAIL — functions not defined.

- [ ] **Step 3: Write minimal implementation**

Add `import json` to the imports of `registry.py`, then append:

```python
def _api_user_name(user_info: dict) -> str:
    surname = user_info.get("surname")
    firstname = user_info.get("firstname")
    if surname and firstname:
        return f"{surname} {firstname}"
    if surname:
        return surname
    if firstname:
        return firstname
    return user_info.get("login") or "Неизвестный"


def recording_fields_from_api(rec: dict) -> dict:
    rid = rec.get("id") or rec.get("key") or ""
    created = (rec.get("createdDate") or "")[:10]
    duration = rec.get("duration", 0) or 0
    return {
        "recording_id": rid,
        "name": rec.get("title", "Без названия"),
        "date": created,
        "duration_min": round(duration / 60),
        "raw_json": json.dumps(rec, ensure_ascii=False),
    }


def participants_from_api(rec: dict) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for p in rec.get("participants", []) or []:
        info = p.get("userInfo")
        if not info:
            continue
        ktalk_id = info.get("key") or info.get("login")
        if not ktalk_id or ktalk_id in seen:
            continue
        seen.add(ktalk_id)
        out.append({"ktalk_id": str(ktalk_id), "name": _api_user_name(info)})
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_registry.py -v && uv run ruff check src/ktalk_mcp/registry.py`
Expected: PASS, no ruff errors.

- [ ] **Step 5: Commit**

```bash
git add src/ktalk_mcp/registry.py tests/test_registry.py
git commit -m "feat: map KTalk API recordings to registry rows"
```

---

### Task 7: Migration parsers

**Files:**
- Modify: `src/ktalk_mcp/registry.py`
- Create: `tests/fixtures/registry.md`, `tests/fixtures/registry-archive-2026-04.md`
- Test: `tests/test_migration.py`

**Interfaces:**
- Produces (module-level functions in `registry.py`):
  - `parse_participants_field(raw: str) -> list[dict]` — parses `"Демьянов Максим (ktalk:668), Муратов Алексей (ktalk:412)"` → `[{"ktalk_id": "668", "name": "Демьянов Максим"}, ...]`. Tolerates extra whitespace; ignores fragments without a `(ktalk:ID)` marker.
  - `parse_duration_field(raw: str) -> int | None` — `"61 мин"` → 61; `"1 ч 5 мин"` → 65; `"—"`/empty → None.
  - `parse_unprocessed_table(text: str) -> list[dict]` — parses the 6-column "Необработанные записи" table → rows `{recording_id, name, participants: list[dict], date, duration_min, status}`.
  - `parse_archive_table(text: str) -> list[dict]` — parses the 7-column archive table → rows `{recording_id, name, date, status, processed_at, transcript_path, protocol_path}` where `—` becomes `None` for paths.

- [ ] **Step 1: Create the fixtures**

Create `tests/fixtures/registry.md`:

```markdown
---
type: registry
---

# Реестр записей Kontur Talk

## Необработанные записи

| recording_id | Название | Участники | Дата | Длительность | Статус |
|---|---|---|---|---|---|
| OowNhGRNjLOG3MshMC6i | Алексей 🤝 Максим (1-1 Муратов) | Муратов Алексей (ktalk:412), Демьянов Максим (ktalk:668) | 2026-06-25 | 61 мин | processing |
| bY3xokeFWEfZeKpSHvpn | Yet Another Sync | Шадрин Всеволод (ktalk:706), Демьянов Максим (ktalk:668) | 2026-06-24 | 55 мин | new |
```

Create `tests/fixtures/registry-archive-2026-04.md`:

```markdown
---
type: registry-archive
month: 2026-04
---

# Архив записей Kontur Talk — 2026-04

| recording_id | Название | Дата | Статус | Дата обработки | Путь транскрипта | Путь протокола |
|---|---|---|---|---|---|---|
| RmfKLz7TrOEb8zQRsxka | Согласуем треки развития SMP | 2026-04-02 | done | 2026-04-03 | 95_TRANSCRIPTS/2026/2026-04-02_other_smp.md | 30_PROJECTS/active/smp/meetings/2026-04-02_smp.md |
| FnUoejME8Q94q7inepi4 | Разговор про стратегию | 2026-04-03 | skipped | 2026-04-03 | — | — |
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_migration.py`:

```python
from __future__ import annotations

from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_participants_field():
    from ktalk_mcp.registry import parse_participants_field

    parts = parse_participants_field(
        "Муратов Алексей (ktalk:412), Демьянов Максим (ktalk:668)"
    )
    assert parts == [
        {"ktalk_id": "412", "name": "Муратов Алексей"},
        {"ktalk_id": "668", "name": "Демьянов Максим"},
    ]
    assert parse_participants_field("") == []


def test_parse_duration_field():
    from ktalk_mcp.registry import parse_duration_field

    assert parse_duration_field("61 мин") == 61
    assert parse_duration_field("1 ч 5 мин") == 65
    assert parse_duration_field("—") is None
    assert parse_duration_field("") is None


def test_parse_unprocessed_table():
    from ktalk_mcp.registry import parse_unprocessed_table

    text = (FIXTURES / "registry.md").read_text(encoding="utf-8")
    rows = parse_unprocessed_table(text)
    assert len(rows) == 2
    first = rows[0]
    assert first["recording_id"] == "OowNhGRNjLOG3MshMC6i"
    assert first["status"] == "processing"
    assert first["date"] == "2026-06-25"
    assert first["duration_min"] == 61
    assert {p["ktalk_id"] for p in first["participants"]} == {"412", "668"}


def test_parse_archive_table():
    from ktalk_mcp.registry import parse_archive_table

    text = (FIXTURES / "registry-archive-2026-04.md").read_text(encoding="utf-8")
    rows = parse_archive_table(text)
    assert len(rows) == 2
    done, skipped = rows
    assert done["status"] == "done"
    assert done["processed_at"] == "2026-04-03"
    assert done["transcript_path"].endswith("_smp.md")
    assert skipped["status"] == "skipped"
    assert skipped["transcript_path"] is None
    assert skipped["protocol_path"] is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_migration.py -v`
Expected: FAIL — parser functions not defined.

- [ ] **Step 4: Write minimal implementation**

Add `import re` to `registry.py` imports, then append:

```python
_KTALK_RE = re.compile(r"\(ktalk:([^)]+)\)")


def parse_participants_field(raw: str) -> list[dict]:
    out: list[dict] = []
    for part in raw.split(","):
        part = part.strip()
        m = _KTALK_RE.search(part)
        if not m:
            continue
        name = _KTALK_RE.sub("", part).strip()
        out.append({"ktalk_id": m.group(1).strip(), "name": name})
    return out


def parse_duration_field(raw: str) -> int | None:
    raw = raw.strip()
    if not raw or raw == "—":
        return None
    hours = re.search(r"(\d+)\s*ч", raw)
    minutes = re.search(r"(\d+)\s*мин", raw)
    total = 0
    if hours:
        total += int(hours.group(1)) * 60
    if minutes:
        total += int(minutes.group(1))
    return total or None


def _table_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells or cells[0] in ("recording_id",):
            continue
        if all(set(c) <= {"-", ":"} for c in cells):  # separator row
            continue
        rows.append(cells)
    return rows


def _nullable_path(value: str) -> str | None:
    value = value.strip()
    return None if value in ("", "—") else value


def parse_unprocessed_table(text: str) -> list[dict]:
    out: list[dict] = []
    for cells in _table_rows(text):
        if len(cells) < 6:
            continue
        out.append(
            {
                "recording_id": cells[0],
                "name": cells[1],
                "participants": parse_participants_field(cells[2]),
                "date": cells[3],
                "duration_min": parse_duration_field(cells[4]),
                "status": cells[5],
            }
        )
    return out


def parse_archive_table(text: str) -> list[dict]:
    out: list[dict] = []
    for cells in _table_rows(text):
        if len(cells) < 7:
            continue
        out.append(
            {
                "recording_id": cells[0],
                "name": cells[1],
                "date": cells[2],
                "status": cells[3],
                "processed_at": _nullable_path(cells[4]),
                "transcript_path": _nullable_path(cells[5]),
                "protocol_path": _nullable_path(cells[6]),
            }
        )
    return out
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_migration.py -v && uv run ruff check src/ktalk_mcp/registry.py`
Expected: PASS, no ruff errors.

- [ ] **Step 6: Commit**

```bash
git add src/ktalk_mcp/registry.py tests/test_migration.py tests/fixtures/
git commit -m "feat: add markdown registry parsers for migration"
```

---

### Task 8: Migration runner

**Files:**
- Modify: `src/ktalk_mcp/registry.py`
- Test: `tests/test_migration.py`

**Interfaces:**
- Consumes: parsers from Task 7, `Registry.upsert_recording`/`set_status`, `participants_from_api` shape.
- Produces (module-level function in `registry.py`):
  - `migrate_from_vault(registry: Registry, vault_path: str | Path, *, dry_run: bool = False, now: str | None = None) -> dict` — reads `{vault}/95_TRANSCRIPTS/registry.md` (unprocessed → status from row, default `new`) and every `{vault}/95_TRANSCRIPTS/registry-archive-*.md` (status/paths/processed_at from row). Upserts idempotently with participants. When `dry_run`, performs no writes. Returns summary `{"recordings": int, "participants": int, "by_status": {status: count}}`. Archive rows have no participant column → empty participant list (do not wipe existing participants when archive is processed after unprocessed for the same id: pass `participants=None` for archive rows so existing rows are preserved).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_migration.py`:

```python
def test_migrate_imports_rows_and_participants(tmp_path: Path):
    from ktalk_mcp.registry import Registry, migrate_from_vault

    vault = tmp_path / "vault"
    tdir = vault / "95_TRANSCRIPTS"
    tdir.mkdir(parents=True)
    (tdir / "registry.md").write_text(
        (FIXTURES / "registry.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (tdir / "registry-archive-2026-04.md").write_text(
        (FIXTURES / "registry-archive-2026-04.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    with Registry(tmp_path / "r.db") as reg:
        summary = migrate_from_vault(reg, vault, now="2026-06-25")
        assert summary["recordings"] == 4
        assert summary["by_status"] == {
            "processing": 1,
            "new": 1,
            "done": 1,
            "skipped": 1,
        }
        assert summary["participants"] == 4  # 2 + 2 from the two unprocessed rows
        done = reg.get_recording("RmfKLz7TrOEb8zQRsxka")
        assert done["status"] == "done"
        assert done["transcript_path"].endswith("_smp.md")
        assert done["processed_at"] == "2026-04-03"


def test_migrate_is_idempotent(tmp_path: Path):
    from ktalk_mcp.registry import Registry, migrate_from_vault

    vault = tmp_path / "vault"
    tdir = vault / "95_TRANSCRIPTS"
    tdir.mkdir(parents=True)
    (tdir / "registry.md").write_text(
        (FIXTURES / "registry.md").read_text(encoding="utf-8"), encoding="utf-8"
    )

    with Registry(tmp_path / "r.db") as reg:
        migrate_from_vault(reg, vault, now="2026-06-25")
        migrate_from_vault(reg, vault, now="2026-06-26")
        count = reg._conn.execute("SELECT COUNT(*) FROM recordings").fetchone()[0]
        assert count == 2  # no duplicates


def test_migrate_dry_run_writes_nothing(tmp_path: Path):
    from ktalk_mcp.registry import Registry, migrate_from_vault

    vault = tmp_path / "vault"
    tdir = vault / "95_TRANSCRIPTS"
    tdir.mkdir(parents=True)
    (tdir / "registry.md").write_text(
        (FIXTURES / "registry.md").read_text(encoding="utf-8"), encoding="utf-8"
    )

    with Registry(tmp_path / "r.db") as reg:
        summary = migrate_from_vault(reg, vault, dry_run=True, now="2026-06-25")
        assert summary["recordings"] == 2
        count = reg._conn.execute("SELECT COUNT(*) FROM recordings").fetchone()[0]
        assert count == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_migration.py -k migrate -v`
Expected: FAIL — `migrate_from_vault` not defined.

- [ ] **Step 3: Write minimal implementation**

Append to `src/ktalk_mcp/registry.py`:

```python
def migrate_from_vault(
    registry: Registry,
    vault_path: str | Path,
    *,
    dry_run: bool = False,
    now: str | None = None,
) -> dict:
    now = now or today_str()
    base = Path(vault_path) / "95_TRANSCRIPTS"
    by_status: dict[str, int] = {}
    recordings = 0
    participants = 0

    def _count(status: str) -> None:
        by_status[status] = by_status.get(status, 0) + 1

    reg_md = base / "registry.md"
    if reg_md.exists():
        for row in parse_unprocessed_table(reg_md.read_text(encoding="utf-8")):
            recordings += 1
            participants += len(row["participants"])
            _count(row["status"])
            if not dry_run:
                registry.upsert_recording(
                    {
                        "recording_id": row["recording_id"],
                        "name": row["name"],
                        "date": row["date"],
                        "duration_min": row["duration_min"],
                        "status": row["status"],
                    },
                    participants=row["participants"],
                    now=now,
                )
                if row["status"] != "new":
                    registry.set_status(row["recording_id"], row["status"], now=now)

    for archive in sorted(base.glob("registry-archive-*.md")):
        for row in parse_archive_table(archive.read_text(encoding="utf-8")):
            recordings += 1
            _count(row["status"])
            if not dry_run:
                registry.upsert_recording(
                    {
                        "recording_id": row["recording_id"],
                        "name": row["name"],
                        "date": row["date"],
                        "status": row["status"],
                    },
                    now=now,
                )
                registry.set_status(
                    row["recording_id"],
                    row["status"],
                    now=now,
                    transcript_path=row["transcript_path"],
                    protocol_path=row["protocol_path"],
                    processed_at=row["processed_at"],
                )

    return {
        "recordings": recordings,
        "participants": participants,
        "by_status": by_status,
    }
```

Note: `upsert_recording` ignores `status` on update (idempotency), so the explicit `set_status` call after upsert is what actually lands the archived status/paths on re-runs.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_migration.py -v && uv run ruff check src/ktalk_mcp/registry.py`
Expected: PASS, no ruff errors.

- [ ] **Step 5: Commit**

```bash
git add src/ktalk_mcp/registry.py tests/test_migration.py
git commit -m "feat: add vault markdown migration runner"
```

---

### Task 9: Markdown mirror renderer

**Files:**
- Modify: `src/ktalk_mcp/registry.py`
- Test: `tests/test_registry.py`

**Interfaces:**
- Consumes: `Registry.list_recordings`, `Registry.get_participants`.
- Produces (module-level function in `registry.py`):
  - `render_markdown_mirror(registry: Registry, *, full: bool = False, now: str | None = None) -> str` — returns a read-only markdown document beginning with `<!-- GENERATED by ktalk export — НЕ редактировать вручную -->`. Sections: "## Необработанные записи" (statuses `new`, `processing`, `partial`) as a 6-column table matching the legacy format (`recording_id | Название | Участники | Дата | Длительность | Статус`); "## Обработанные записи" (statuses `done`, `skipped`) — when `full=False` only the current + previous calendar month (by `date`), when `full=True` all of them, as a 7-column table (`recording_id | Название | Дата | Статус | Дата обработки | Путь транскрипта | Путь протокола`). Empty paths render as `—`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_registry.py`:

```python
def test_render_markdown_mirror(tmp_path: Path):
    from ktalk_mcp.registry import Registry, render_markdown_mirror

    with Registry(tmp_path / "r.db") as reg:
        reg.upsert_recording(
            _rec("new1", name="Standup", date="2026-06-24", duration_min=55),
            participants=[{"ktalk_id": "668", "name": "Демьянов Максим"}],
            now="2026-06-24",
        )
        reg.upsert_recording(_rec("done1", name="1-1", date="2026-06-20"), now="2026-06-20")
        reg.mark_done(
            "done1",
            transcript_path="95_TRANSCRIPTS/2026/x.md",
            protocol_path="10_PEOPLE/x.md",
            now="2026-06-21",
        )
        reg.upsert_recording(_rec("old", name="Ancient", date="2026-01-05"), now="2026-01-05")
        reg.mark_skipped("old", now="2026-01-12")

        text = render_markdown_mirror(reg, now="2026-06-25")
        assert text.startswith("<!-- GENERATED by ktalk export")
        assert "## Необработанные записи" in text
        assert "new1" in text
        assert "Демьянов Максим (ktalk:668)" in text
        assert "done1" in text  # done within current/prev month window
        assert "old" not in text  # January skipped, outside 2-month window

        full = render_markdown_mirror(reg, full=True, now="2026-06-25")
        assert "old" in full  # full dump includes everything
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_registry.py -k mirror -v`
Expected: FAIL — `render_markdown_mirror` not defined.

- [ ] **Step 3: Write minimal implementation**

Append to `src/ktalk_mcp/registry.py`:

```python
_MIRROR_HEADER = "<!-- GENERATED by ktalk export — НЕ редактировать вручную -->"


def _recent_months(now: str) -> set[str]:
    d = date.fromisoformat(now)
    cur = f"{d.year:04d}-{d.month:02d}"
    if d.month == 1:
        prev = f"{d.year - 1:04d}-12"
    else:
        prev = f"{d.year:04d}-{d.month - 1:02d}"
    return {cur, prev}


def render_markdown_mirror(
    registry: Registry, *, full: bool = False, now: str | None = None
) -> str:
    now = now or today_str()
    recs = registry.list_recordings()
    unprocessed = [r for r in recs if r["status"] in ("new", "processing", "partial")]
    processed = [r for r in recs if r["status"] in ("done", "skipped")]
    if not full:
        months = _recent_months(now)
        processed = [r for r in processed if r["date"][:7] in months]

    lines = [
        _MIRROR_HEADER,
        "",
        "# Реестр записей Kontur Talk",
        "",
        "## Необработанные записи",
        "",
        "| recording_id | Название | Участники | Дата | Длительность | Статус |",
        "|---|---|---|---|---|---|",
    ]
    for r in unprocessed:
        parts = registry.get_participants(r["recording_id"])
        parts_str = ", ".join(f"{p['name']} (ktalk:{p['ktalk_id']})" for p in parts)
        dur = f"{r['duration_min']} мин" if r["duration_min"] else "—"
        lines.append(
            f"| {r['recording_id']} | {r['name']} | {parts_str} | {r['date']} | "
            f"{dur} | {r['status']} |"
        )

    lines += [
        "",
        "## Обработанные записи",
        "",
        "| recording_id | Название | Дата | Статус | Дата обработки | "
        "Путь транскрипта | Путь протокола |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in processed:
        lines.append(
            f"| {r['recording_id']} | {r['name']} | {r['date']} | {r['status']} | "
            f"{r['processed_at'] or '—'} | {r['transcript_path'] or '—'} | "
            f"{r['protocol_path'] or '—'} |"
        )

    return "\n".join(lines) + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_registry.py -v && uv run ruff check src/ktalk_mcp/registry.py`
Expected: PASS, no ruff errors.

- [ ] **Step 5: Commit**

```bash
git add src/ktalk_mcp/registry.py tests/test_registry.py
git commit -m "feat: add markdown mirror renderer for git export"
```

---

### Task 10: CLI scaffold + list/show

**Files:**
- Create: `src/ktalk_mcp/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `resolve_db_path` (Task 1), `Registry` (Tasks 2-4).
- Produces:
  - `build_parser() -> argparse.ArgumentParser` — top-level parser with a global `--db PATH` and per-subcommand `--json`, subparsers under `dest="command"`.
  - `main(argv: list[str] | None = None) -> int` — parses argv, dispatches; returns `0` on success, non-zero on error (prints error to stderr). On no command, prints help and returns `2`.
  - Subcommands implemented here: `list [--status S] [--json]`, `show <id> [--json]`.
  - JSON output for `list`: `{"recordings": [ {recording_id, name, date, duration_min, status, meeting_type, ...}, ... ]}`. For `show`: `{recording fields..., "participants": [...]}`; missing id → error to stderr, return `1`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli.py`:

```python
from __future__ import annotations

import json
from pathlib import Path


def _seed(db: Path):
    from ktalk_mcp.registry import Registry

    with Registry(db) as reg:
        reg.upsert_recording(
            {"recording_id": "a", "name": "Standup", "date": "2026-06-24",
             "duration_min": 30},
            participants=[{"ktalk_id": "668", "name": "Демьянов Максим"}],
            now="2026-06-24",
        )
        reg.upsert_recording(
            {"recording_id": "b", "name": "1-1", "date": "2026-06-20"},
            now="2026-06-20",
        )
        reg.set_status("b", "done")


def test_list_json(tmp_path, capsys):
    from ktalk_mcp.cli import main

    db = tmp_path / "r.db"
    _seed(db)
    rc = main(["--db", str(db), "list", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    ids = [r["recording_id"] for r in out["recordings"]]
    assert ids == ["a", "b"]  # date DESC


def test_list_status_filter_json(tmp_path, capsys):
    from ktalk_mcp.cli import main

    db = tmp_path / "r.db"
    _seed(db)
    rc = main(["--db", str(db), "list", "--status", "new", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert [r["recording_id"] for r in out["recordings"]] == ["a"]


def test_show_json_includes_participants(tmp_path, capsys):
    from ktalk_mcp.cli import main

    db = tmp_path / "r.db"
    _seed(db)
    rc = main(["--db", str(db), "show", "a", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["recording_id"] == "a"
    assert out["participants"][0]["ktalk_id"] == "668"


def test_show_missing_returns_error(tmp_path, capsys):
    from ktalk_mcp.cli import main

    db = tmp_path / "r.db"
    _seed(db)
    rc = main(["--db", str(db), "show", "nope", "--json"])
    assert rc == 1
    assert capsys.readouterr().err  # non-empty stderr


def test_list_text_output(tmp_path, capsys):
    from ktalk_mcp.cli import main

    db = tmp_path / "r.db"
    _seed(db)
    rc = main(["--db", str(db), "list"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "Standup" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ktalk_mcp.cli'`

- [ ] **Step 3: Write minimal implementation**

Create `src/ktalk_mcp/cli.py`:

```python
"""Command-line interface for the KTalk recordings registry."""

from __future__ import annotations

import argparse
import json
import sys

from ktalk_mcp.config import resolve_db_path
from ktalk_mcp.registry import Registry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ktalk", description="Реестр записей Kontur Talk")
    parser.add_argument("--db", default=None, help="Путь к SQLite-базе реестра")
    sub = parser.add_subparsers(dest="command")

    p_list = sub.add_parser("list", help="Список записей")
    p_list.add_argument("--status", default=None)
    p_list.add_argument("--json", action="store_true")

    p_show = sub.add_parser("show", help="Детали записи")
    p_show.add_argument("id")
    p_show.add_argument("--json", action="store_true")

    return parser


def _print_json(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _cmd_list(reg: Registry, args) -> int:
    recs = reg.list_recordings(status=args.status)
    if args.json:
        _print_json({"recordings": recs})
        return 0
    if not recs:
        print("Записей не найдено.")
        return 0
    for r in recs:
        dur = f"{r['duration_min']} мин" if r["duration_min"] else "—"
        print(f"{r['recording_id']}  [{r['status']}]  {r['date']}  {dur}  {r['name']}")
    return 0


def _cmd_show(reg: Registry, args) -> int:
    rec = reg.get_recording(args.id)
    if rec is None:
        print(f"Запись не найдена: {args.id}", file=sys.stderr)
        return 1
    rec = dict(rec)
    rec["participants"] = reg.get_participants(args.id)
    if args.json:
        _print_json(rec)
        return 0
    print(f"# {rec['name']}")
    print(f"- ID: {rec['recording_id']}")
    print(f"- Статус: {rec['status']}")
    print(f"- Дата: {rec['date']}")
    print(f"- Длительность: {rec['duration_min']} мин")
    print(f"- Транскрипт: {rec['transcript_path'] or '—'}")
    print(f"- Протокол: {rec['protocol_path'] or '—'}")
    print("- Участники:")
    for p in rec["participants"]:
        vault = f" -> {p['vault_id']}" if p["vault_id"] else ""
        print(f"  - {p['name']} (ktalk:{p['ktalk_id']}){vault}")
    return 0


_HANDLERS = {
    "list": _cmd_list,
    "show": _cmd_show,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 2
    db_path = resolve_db_path(args.db)
    handler = _HANDLERS.get(args.command)
    if handler is None:
        parser.print_help()
        return 2
    try:
        with Registry(db_path) as reg:
            return handler(reg, args)
    except Exception as exc:  # noqa: BLE001 - surface as CLI error
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -v && uv run ruff check src/ktalk_mcp/cli.py`
Expected: PASS, no ruff errors.

- [ ] **Step 5: Commit**

```bash
git add src/ktalk_mcp/cli.py tests/test_cli.py
git commit -m "feat: add ktalk CLI scaffold with list and show"
```

---

### Task 11: CLI mark-* and set-vault-id

**Files:**
- Modify: `src/ktalk_mcp/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `Registry.mark_processing/mark_done/mark_partial/mark_skipped/set_vault_id`.
- Produces subcommands:
  - `mark-processing <id>`
  - `mark-done <id> --transcript PATH --protocol PATH [--type TYPE]`
  - `mark-partial <id> [--transcript PATH] [--protocol PATH]`
  - `mark-skipped <id>`
  - `set-vault-id <id> <ktalk_id> <vault_id>`
  - Each prints a short confirmation to stdout and returns `0`; unknown id / participant → error to stderr, return `1`. (`mark-done` requires `--transcript` and `--protocol`.)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
def test_mark_done_updates_db(tmp_path):
    from ktalk_mcp.cli import main
    from ktalk_mcp.registry import Registry

    db = tmp_path / "r.db"
    _seed(db)
    rc = main([
        "--db", str(db), "mark-done", "a",
        "--transcript", "t.md", "--protocol", "p.md", "--type", "standup",
    ])
    assert rc == 0
    with Registry(db) as reg:
        row = reg.get_recording("a")
        assert row["status"] == "done"
        assert row["transcript_path"] == "t.md"
        assert row["meeting_type"] == "standup"


def test_mark_processing_then_partial(tmp_path):
    from ktalk_mcp.cli import main
    from ktalk_mcp.registry import Registry

    db = tmp_path / "r.db"
    _seed(db)
    assert main(["--db", str(db), "mark-processing", "a"]) == 0
    assert main(["--db", str(db), "mark-partial", "a", "--transcript", "t.md"]) == 0
    with Registry(db) as reg:
        assert reg.get_recording("a")["status"] == "partial"


def test_mark_done_missing_id_errors(tmp_path, capsys):
    from ktalk_mcp.cli import main

    db = tmp_path / "r.db"
    _seed(db)
    rc = main(["--db", str(db), "mark-done", "nope", "--transcript", "t", "--protocol", "p"])
    assert rc == 1
    assert capsys.readouterr().err


def test_set_vault_id(tmp_path):
    from ktalk_mcp.cli import main
    from ktalk_mcp.registry import Registry

    db = tmp_path / "r.db"
    _seed(db)
    rc = main(["--db", str(db), "set-vault-id", "a", "668", "mdemyanov"])
    assert rc == 0
    with Registry(db) as reg:
        assert reg.get_participants("a")[0]["vault_id"] == "mdemyanov"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -k "mark or vault" -v`
Expected: FAIL — subcommands not registered (`argparse` exits / unknown command).

- [ ] **Step 3: Write minimal implementation**

In `build_parser()`, register the new subparsers (after `show`):

```python
    p_mp = sub.add_parser("mark-processing", help="В обработку")
    p_mp.add_argument("id")

    p_md = sub.add_parser("mark-done", help="Завершить обработку")
    p_md.add_argument("id")
    p_md.add_argument("--transcript", required=True)
    p_md.add_argument("--protocol", required=True)
    p_md.add_argument("--type", dest="meeting_type", default=None)

    p_pp = sub.add_parser("mark-partial", help="Частичная обработка")
    p_pp.add_argument("id")
    p_pp.add_argument("--transcript", default=None)
    p_pp.add_argument("--protocol", default=None)

    p_sk = sub.add_parser("mark-skipped", help="Пропустить")
    p_sk.add_argument("id")

    p_vi = sub.add_parser("set-vault-id", help="Привязать профиль к участнику")
    p_vi.add_argument("id")
    p_vi.add_argument("ktalk_id")
    p_vi.add_argument("vault_id")
```

Add handlers:

```python
def _cmd_mark_processing(reg: Registry, args) -> int:
    reg.mark_processing(args.id)
    print(f"{args.id}: processing")
    return 0


def _cmd_mark_done(reg: Registry, args) -> int:
    reg.mark_done(
        args.id,
        transcript_path=args.transcript,
        protocol_path=args.protocol,
        meeting_type=args.meeting_type,
    )
    print(f"{args.id}: done")
    return 0


def _cmd_mark_partial(reg: Registry, args) -> int:
    reg.mark_partial(args.id, transcript_path=args.transcript, protocol_path=args.protocol)
    print(f"{args.id}: partial")
    return 0


def _cmd_mark_skipped(reg: Registry, args) -> int:
    reg.mark_skipped(args.id)
    print(f"{args.id}: skipped")
    return 0


def _cmd_set_vault_id(reg: Registry, args) -> int:
    reg.set_vault_id(args.id, args.ktalk_id, args.vault_id)
    print(f"{args.id}/{args.ktalk_id} -> {args.vault_id}")
    return 0
```

Extend `_HANDLERS`:

```python
_HANDLERS = {
    "list": _cmd_list,
    "show": _cmd_show,
    "mark-processing": _cmd_mark_processing,
    "mark-done": _cmd_mark_done,
    "mark-partial": _cmd_mark_partial,
    "mark-skipped": _cmd_mark_skipped,
    "set-vault-id": _cmd_set_vault_id,
}
```

Note: `mark_*` raise `KeyError` for unknown ids; the `main()` try/except converts that to a stderr message + exit 1 already.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -v && uv run ruff check src/ktalk_mcp/cli.py`
Expected: PASS, no ruff errors.

- [ ] **Step 5: Commit**

```bash
git add src/ktalk_mcp/cli.py tests/test_cli.py
git commit -m "feat: add CLI mark-* and set-vault-id commands"
```

---

### Task 12: CLI dashboard + export + migrate

**Files:**
- Modify: `src/ktalk_mcp/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `Registry.list_recordings`, `render_markdown_mirror`, `migrate_from_vault`.
- Produces subcommands:
  - `dashboard [--json]` — JSON: `{"new": [...], "stats": {"new": n, "processing": n, "done": n, "skipped": n, "partial": n}}`; text: numbered list of `new` recordings plus a stats line.
  - `export [--out PATH] [--full]` — writes the mirror via `render_markdown_mirror`; default out = `<db parent>/registry.md`. Prints the written path. `--json` → `{"written": path}`.
  - `migrate <vault_path> [--dry-run] [--json]` — runs `migrate_from_vault`; prints the summary. `--json` → the summary dict.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
def test_dashboard_json(tmp_path, capsys):
    from ktalk_mcp.cli import main

    db = tmp_path / "r.db"
    _seed(db)
    rc = main(["--db", str(db), "dashboard", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert [r["recording_id"] for r in out["new"]] == ["a"]
    assert out["stats"]["new"] == 1
    assert out["stats"]["done"] == 1


def test_export_writes_mirror(tmp_path, capsys):
    from ktalk_mcp.cli import main

    db = tmp_path / "r.db"
    _seed(db)
    out_path = tmp_path / "registry.md"
    rc = main(["--db", str(db), "export", "--out", str(out_path)])
    assert rc == 0
    text = out_path.read_text(encoding="utf-8")
    assert text.startswith("<!-- GENERATED by ktalk export")
    assert "a" in text


def test_migrate_dry_run_json(tmp_path, capsys):
    from ktalk_mcp.cli import main

    vault = tmp_path / "vault"
    tdir = vault / "95_TRANSCRIPTS"
    tdir.mkdir(parents=True)
    fixtures = Path(__file__).parent / "fixtures"
    (tdir / "registry.md").write_text(
        (fixtures / "registry.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    db = tmp_path / "r.db"
    rc = main(["--db", str(db), "migrate", str(vault), "--dry-run", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["recordings"] == 2
    from ktalk_mcp.registry import Registry

    with Registry(db) as reg:
        assert reg.list_recordings() == []  # dry-run wrote nothing
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -k "dashboard or export or migrate" -v`
Expected: FAIL — subcommands not registered.

- [ ] **Step 3: Write minimal implementation**

Add imports at the top of `cli.py`:

```python
from pathlib import Path

from ktalk_mcp.registry import Registry, migrate_from_vault, render_markdown_mirror
```

(Merge with the existing `from ktalk_mcp.registry import Registry` line.)

Register subparsers in `build_parser()`:

```python
    p_dash = sub.add_parser("dashboard", help="Дашборд")
    p_dash.add_argument("--json", action="store_true")

    p_exp = sub.add_parser("export", help="Сгенерировать markdown-зеркало")
    p_exp.add_argument("--out", default=None)
    p_exp.add_argument("--full", action="store_true")
    p_exp.add_argument("--json", action="store_true")

    p_mig = sub.add_parser("migrate", help="Импорт из markdown-реестров")
    p_mig.add_argument("vault_path")
    p_mig.add_argument("--dry-run", action="store_true")
    p_mig.add_argument("--json", action="store_true")
```

Add handlers:

```python
_STATUSES = ("new", "processing", "done", "skipped", "partial")


def _cmd_dashboard(reg: Registry, args) -> int:
    recs = reg.list_recordings()
    new = [r for r in recs if r["status"] == "new"]
    stats = {s: sum(1 for r in recs if r["status"] == s) for s in _STATUSES}
    if args.json:
        _print_json({"new": new, "stats": stats})
        return 0
    print("# Дашборд KTalk\n")
    print("## Новые записи")
    if not new:
        print("(нет)")
    for i, r in enumerate(new, 1):
        print(f"{i}. {r['recording_id']}  {r['date']}  {r['name']}")
    print(
        f"\nСтатистика: новых {stats['new']}, в обработке {stats['processing']}, "
        f"обработано {stats['done']}, пропущено {stats['skipped']}, "
        f"частично {stats['partial']}"
    )
    return 0


def _cmd_export(reg: Registry, args) -> int:
    text = render_markdown_mirror(reg, full=args.full)
    if args.out:
        out_path = Path(args.out)
    else:
        out_path = Path(resolve_db_path(args.db)).parent / "registry.md"
    out_path.write_text(text, encoding="utf-8")
    if args.json:
        _print_json({"written": str(out_path)})
    else:
        print(f"Зеркало записано: {out_path}")
    return 0


def _cmd_migrate(reg: Registry, args) -> int:
    summary = migrate_from_vault(reg, args.vault_path, dry_run=args.dry_run)
    if args.json:
        _print_json(summary)
    else:
        print(f"Импортировано записей: {summary['recordings']}")
        print(f"Участников: {summary['participants']}")
        print(f"По статусам: {summary['by_status']}")
        if args.dry_run:
            print("(dry-run: ничего не записано)")
    return 0
```

Extend `_HANDLERS` with `"dashboard"`, `"export"`, `"migrate"`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -v && uv run ruff check src/ktalk_mcp/cli.py`
Expected: PASS, no ruff errors.

- [ ] **Step 5: Commit**

```bash
git add src/ktalk_mcp/cli.py tests/test_cli.py
git commit -m "feat: add CLI dashboard, export, and migrate commands"
```

---

### Task 13: CLI sync (against mocked KTalk API)

**Files:**
- Modify: `src/ktalk_mcp/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `Settings` (token + base_url), `KTalkClient.list_recordings`, `recording_fields_from_api`, `participants_from_api`, `Registry.upsert_recording`, `Registry.expire_new`, `Registry.set_meta`.
- Produces:
  - `sync [--days 7] [--json]` subcommand. Fetches recordings from KTalk for the last `--days` days (`start_from` = today − days, ISO), upserts each (new ones → status `new`), runs `expire_new(days=days)`, increments meta `sync_count`, sets meta `last_synced`. Default output: the dashboard (reuse `_cmd_dashboard`). `--json` → `{"synced": int, "inserted": int, "updated": int, "expired": [ids], "stats": {...}}`.
  - Internal async helper `_fetch_recordings(days: int) -> list[dict]` that builds `Settings()`, opens `KTalkClient`, calls `list_recordings(start_from=..., top=1000)`, returns `data.get("recordings", [])`. Paginates while `nextPageToken` present (cap a reasonable number of pages, e.g. 20).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`:

```python
def test_sync_inserts_dedups_and_expires(tmp_path, capsys, monkeypatch, httpx_mock):
    monkeypatch.setenv("KTALK_BASE_URL", "https://test.ktalk.ru")
    monkeypatch.setenv("KTALK_SESSION_TOKEN", "tok")
    monkeypatch.delenv("KTALK_REGISTRY_DB", raising=False)

    db = tmp_path / "r.db"
    # Pre-seed an old 'new' recording that must expire, plus one that will be re-synced.
    from ktalk_mcp.registry import Registry

    with Registry(db) as reg:
        reg.upsert_recording(
            {"recording_id": "old", "name": "Old", "date": "2026-01-01"},
            now="2026-01-01",
        )
        reg.upsert_recording(
            {"recording_id": "dup", "name": "Existing", "date": "2026-06-24"},
            now="2026-06-24",
        )
        reg.set_status("dup", "done")

    # API returns a brand-new recording plus the already-known 'dup'.
    httpx_mock.add_response(
        json={
            "recordings": [
                {"id": "fresh", "title": "Fresh", "createdDate": "2026-06-25T10:00:00Z",
                 "duration": 1800,
                 "participants": [{"userInfo": {"key": "668", "surname": "Демьянов",
                                                "firstname": "Максим"}}]},
                {"id": "dup", "title": "Existing renamed",
                 "createdDate": "2026-06-24T10:00:00Z", "duration": 600},
            ]
        }
    )

    from ktalk_mcp.cli import main

    rc = main(["--db", str(db), "sync", "--days", "7", "--json"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "fresh" in [r for r in out.get("expired", [])] or out["expired"] == ["old"]
    assert out["expired"] == ["old"]

    with Registry(db) as reg:
        assert reg.get_recording("fresh")["status"] == "new"
        assert reg.get_recording("dup")["status"] == "done"  # status preserved
        assert reg.get_recording("dup")["name"] == "Existing renamed"  # content updated
        assert reg.get_recording("old")["status"] == "skipped"
        assert reg.get_meta("sync_count") == "1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -k sync -v`
Expected: FAIL — `sync` subcommand not registered.

- [ ] **Step 3: Write minimal implementation**

Add imports to `cli.py`:

```python
import asyncio
from datetime import date, timedelta

from ktalk_mcp.client import KTalkClient, KTalkError
from ktalk_mcp.config import Settings, resolve_db_path
from ktalk_mcp.registry import (
    Registry,
    migrate_from_vault,
    participants_from_api,
    recording_fields_from_api,
    render_markdown_mirror,
)
```

(Merge with existing import lines; keep a single `from ktalk_mcp.config import ...` and a single `from ktalk_mcp.registry import ...`.)

Register the subparser:

```python
    p_sync = sub.add_parser("sync", help="Синхронизация с KTalk")
    p_sync.add_argument("--days", type=int, default=7)
    p_sync.add_argument("--json", action="store_true")
```

Add the fetch helper and handler:

```python
async def _fetch_recordings(days: int) -> list[dict]:
    settings = Settings()
    start_from = (date.today() - timedelta(days=days)).isoformat()
    out: list[dict] = []
    async with KTalkClient(
        base_url=settings.ktalk_base_url, session_token=settings.ktalk_session_token
    ) as client:
        page_token: str | None = None
        for _ in range(20):  # page cap
            data = await client.list_recordings(
                start_from=start_from, top=1000, page_token=page_token
            )
            out.extend(data.get("recordings") or [])
            page_token = data.get("nextPageToken")
            if not page_token:
                break
    return out


def _cmd_sync(reg: Registry, args) -> int:
    try:
        recordings = asyncio.run(_fetch_recordings(args.days))
    except KTalkError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    inserted = updated = 0
    for rec in recordings:
        fields = recording_fields_from_api(rec)
        if not fields["recording_id"]:
            continue
        parts = participants_from_api(rec)
        result = reg.upsert_recording(fields, participants=parts)
        if result == "inserted":
            inserted += 1
        else:
            updated += 1
    expired = reg.expire_new(days=args.days)
    count = int(reg.get_meta("sync_count") or "0") + 1
    reg.set_meta("sync_count", str(count))
    reg.set_meta("last_synced", date.today().isoformat())

    if args.json:
        recs = reg.list_recordings()
        stats = {s: sum(1 for r in recs if r["status"] == s) for s in _STATUSES}
        _print_json(
            {
                "synced": len(recordings),
                "inserted": inserted,
                "updated": updated,
                "expired": expired,
                "stats": stats,
            }
        )
        return 0
    return _cmd_dashboard(reg, args)
```

Extend `_HANDLERS` with `"sync": _cmd_sync`.

Note: re-syncing `dup` calls `upsert_recording`, which updates `name` but preserves `status=done` (Task 2.5 guarantee). Pre-seeded `dup` participants are replaced by the (empty) API participant list — acceptable; for `done` records, the mirror does not show participants.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -v && uv run ruff check src/ktalk_mcp/cli.py`
Expected: PASS, no ruff errors.

- [ ] **Step 5: Commit**

```bash
git add src/ktalk_mcp/cli.py tests/test_cli.py
git commit -m "feat: add CLI sync against KTalk API"
```

---

### Task 14: Register the `ktalk` entry point + version bump

**Files:**
- Modify: `pyproject.toml`
- Modify: `src/ktalk_mcp/__init__.py`

**Interfaces:**
- Produces: console script `ktalk = "ktalk_mcp.cli:main"`; package version `0.4.0`.

- [ ] **Step 1: Add the entry point**

Edit `pyproject.toml` `[project.scripts]`:

```toml
[project.scripts]
ktalk-mcp = "ktalk_mcp.server:main"
ktalk     = "ktalk_mcp.cli:main"
```

- [ ] **Step 2: Bump version**

Edit `pyproject.toml` `version = "0.4.0"` and `src/ktalk_mcp/__init__.py` `__version__ = "0.4.0"`.

- [ ] **Step 3: Reinstall and verify both commands resolve**

Run:
```bash
uv sync
uv run ktalk --help
uv run ktalk-mcp --help 2>/dev/null || echo "ktalk-mcp entry present"
```
Expected: `ktalk --help` prints the subcommand list (list/show/mark-*/sync/export/migrate/set-vault-id).

- [ ] **Step 4: Full test + lint gate**

Run: `uv run pytest && uv run ruff check .`
Expected: all tests PASS, no ruff errors.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/ktalk_mcp/__init__.py
git commit -m "feat: register ktalk CLI entry point, bump to 0.4.0"
```

---

### Task 15: Migration dress rehearsal on the real vault (manual gate)

**Files:** none (operational verification).

- [ ] **Step 1: Dry-run against the real vault**

Run:
```bash
uv run ktalk --db /Users/mdemyanov/Documents/naumen-cto/95_TRANSCRIPTS/.registry.db \
  migrate /Users/mdemyanov/Documents/naumen-cto --dry-run --json
```
Expected: `recordings` ≈ 8 (unprocessed) + ~245 (archives 52+74+60+59) ≈ 253 total; sane `by_status` split. Eyeball the counts against `grep -c '^| ' 95_TRANSCRIPTS/registry*.md` minus one header per file.

- [ ] **Step 2: Real migration**

Run the same command without `--dry-run`. Then verify:
```bash
uv run ktalk --db /Users/mdemyanov/Documents/naumen-cto/95_TRANSCRIPTS/.registry.db list --json | python -c "import sys,json; print(len(json.load(sys.stdin)['recordings']))"
```
Expected: count matches the dry-run total. **Do not delete** the source markdown files — they remain as backup.

- [ ] **Step 3: Generate the mirror and diff**

Run:
```bash
uv run ktalk --db /Users/mdemyanov/Documents/naumen-cto/95_TRANSCRIPTS/.registry.db export
cd /Users/mdemyanov/Documents/naumen-cto && git diff --stat 95_TRANSCRIPTS/registry.md
```
Expected: a regenerated, readable `registry.md` with the GENERATED header. Review visually.

---

### Task 16: Vault — gitignore the DB

**Files:**
- Modify: `/Users/mdemyanov/Documents/naumen-cto/.gitignore`

- [ ] **Step 1: Add ignore patterns**

Append to the vault `.gitignore`:

```gitignore
95_TRANSCRIPTS/.registry.db
95_TRANSCRIPTS/.registry.db-wal
95_TRANSCRIPTS/.registry.db-shm
```

- [ ] **Step 2: Verify the DB is ignored**

Run:
```bash
cd /Users/mdemyanov/Documents/naumen-cto && git check-ignore 95_TRANSCRIPTS/.registry.db
```
Expected: prints the path (ignored). `git status` shows the DB untracked-but-ignored.

- [ ] **Step 3: Commit (in vault repo)**

```bash
cd /Users/mdemyanov/Documents/naumen-cto
git add .gitignore && git commit -m "chore: gitignore ktalk registry SQLite db"
```

---

### Task 17: Vault — rewrite the ktalk-registry skill

**Files:**
- Modify: `/Users/mdemyanov/Documents/naumen-cto/.claude/skills/ktalk-registry/SKILL.md`

**Interfaces:** The skill orchestrates the CLI; it must not parse or rewrite tables.

- [ ] **Step 1: Read the current skill and references**

Read `.claude/skills/ktalk-registry/SKILL.md` and `.claude/skills/ktalk-registry/references/registry-format.md` to learn the existing step numbering, the meeting-type auto-detection prose, and the save-location suggestion logic to preserve.

- [ ] **Step 2: Rewrite the workflow section**

Replace the manual mechanics with this workflow (keep the model-judgment parts — meeting-type detection, save-location suggestions — verbatim from the old skill):

```markdown
## Workflow

1. **Sync** — run `ktalk sync --json`. This fetches new recordings, dedupes, expires
   stale `new` entries, and returns the dashboard data. Never edit registry tables by hand.
2. **Show dashboard** — present the `new` list (numbered) and the stats from the CLI output.
3. **Get selection** — ask the user which to process (`1,3` / `все` / `нет`).
4. **Gather context per selected recording** — interactively determine meeting type
   (auto-detect as before) and protocol save location (auto-suggest as before), plus any
   extra context. *(This judgment stays with the model.)*
5. **Launch processors** — start one `ktalk-processor` background agent per selected
   recording (`run_in_background=true`), passing recording_id, meeting type, and save path.
6. **Refresh the mirror** — after launching, run `ktalk export` to regenerate the
   git-visible `registry.md`.
```

- [ ] **Step 3: Delete obsolete prose**

Remove any sections describing manual dedup, expiration (>7 days → skipped), markdown
migration, table editing, or status bookkeeping — these are now the CLI's job. Keep the
command reference pointing at `ktalk sync/dashboard/export`.

- [ ] **Step 4: Commit (vault repo)**

```bash
cd /Users/mdemyanov/Documents/naumen-cto
git add .claude/skills/ktalk-registry/SKILL.md
git commit -m "refactor: ktalk-registry skill orchestrates CLI instead of parsing markdown"
```

---

### Task 18: Vault — update the ktalk-processor agent

**Files:**
- Modify: `/Users/mdemyanov/Documents/naumen-cto/.claude/agents/ktalk-processor.md`

- [ ] **Step 1: Read the current agent**

Read `.claude/agents/ktalk-processor.md` to find where it currently edits `registry.md`/archives.

- [ ] **Step 2: Replace status bookkeeping with CLI calls**

- At processing start: `ktalk mark-processing <id>`.
- On success: `ktalk mark-done <id> --transcript PATH --protocol PATH --type TYPE`.
- On partial: `ktalk mark-partial <id> [--transcript PATH] [--protocol PATH]`.
- Remove all instructions about editing `registry.md` or `registry-archive-*.md`.
- Leave the content analysis, profile/project updates, and transcript/protocol formatting
  instructions unchanged.

- [ ] **Step 3: Commit (vault repo)**

```bash
cd /Users/mdemyanov/Documents/naumen-cto
git add .claude/agents/ktalk-processor.md
git commit -m "refactor: ktalk-processor writes status via ktalk CLI"
```

---

### Task 19: Vault — update registry-format reference docs

**Files:**
- Modify: `/Users/mdemyanov/Documents/naumen-cto/.claude/skills/ktalk-registry/references/registry-format.md`

- [ ] **Step 1: Document the new model**

Rewrite the reference to describe:
- The SQLite schema (recordings/participants/meta) as the operational source of truth.
- The full `ktalk` CLI surface (table of commands + flags, matching Task-level interfaces).
- That `registry.md` is now a **generated, read-only mirror** (note the GENERATED header),
  not a source of truth or a hand-editable table.

- [ ] **Step 2: Reframe (don't delete) the table-format spec**

Keep the 6-column / 7-column table descriptions, but relabel them as "the format `ktalk
export` emits" rather than "the format you must maintain by hand."

- [ ] **Step 3: Commit (vault repo)**

```bash
cd /Users/mdemyanov/Documents/naumen-cto
git add .claude/skills/ktalk-registry/references/registry-format.md
git commit -m "docs: document SQLite + CLI registry model"
```

---

### Task 20: Package docs — update CLAUDE.md and README

**Files:**
- Modify: `/Users/mdemyanov/Devel/ktalk-mcp/CLAUDE.md`
- Modify: `/Users/mdemyanov/Devel/ktalk-mcp/README.md`

- [ ] **Step 1: Update CLAUDE.md**

- Add `registry.py` and `cli.py` to the Architecture module list.
- Add the `ktalk` CLI to Commands (e.g. `uv run ktalk sync`, `uv run ktalk export`).
- Add `KTALK_REGISTRY_DB` to the config/env list.
- Note the two entry points (`ktalk-mcp`, `ktalk`).

- [ ] **Step 2: Update README**

Add a "CLI (registry)" section documenting the subcommands, the DB path resolution rules,
and that `registry.md` is a generated mirror.

- [ ] **Step 3: Final gate**

Run: `uv run pytest && uv run ruff check .`
Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs: document ktalk CLI and SQLite registry"
```

---

### Task 21: End-to-end cycle verification (manual gate)

**Files:** none (operational verification).

- [ ] **Step 1: Run the full loop**

```bash
DB=/Users/mdemyanov/Documents/naumen-cto/95_TRANSCRIPTS/.registry.db
uv run ktalk --db "$DB" sync --json
uv run ktalk --db "$DB" list --status new --json
# pick an id, simulate a processor:
uv run ktalk --db "$DB" mark-processing <id>
uv run ktalk --db "$DB" mark-done <id> --transcript 95_TRANSCRIPTS/2026/test.md \
  --protocol 10_PEOPLE/test.md --type 1-1
uv run ktalk --db "$DB" export
cd /Users/mdemyanov/Documents/naumen-cto && git diff 95_TRANSCRIPTS/registry.md
```

- [ ] **Step 2: Confirm Definition of Done**

Verify each DoD checkbox: both commands install from one package; WAL concurrency test
present and green; all 4 markdown registries imported (count matches); skill no longer
parses tables; mirror is readable; tests green + ruff clean; old archives still on disk.

---

## Self-Review

**Spec coverage:**
- 1.1 SQLite layer (schema, WAL, busy_timeout, txn-per-op) → Tasks 2–4. ✓
- 1.2 CLI surface (all 11 subcommands, `--json` contract) → Tasks 10–13. ✓
- 1.3 Migration (registry.md + 4 archives, participants, idempotent, dry-run, summary) → Tasks 7–8, real run Task 15. ✓
- 1.4 Markdown mirror (GENERATED header, unprocessed + recent processed, `--full`) → Tasks 9, 12. ✓
- 1.5 Concurrency (WAL + busy_timeout + two-writer test) → Tasks 2, 5. ✓
- 1.6 Tests (schema, upsert/dedup, expiration boundary, transitions, participants, migration, CLI json, concurrency, sync via pytest-httpx) → Tasks 2–13. ✓
- Config (`KTALK_REGISTRY_DB` env + `--db` flag precedence, default path) → Task 1. ✓
- Two entry points, shared client/config → Task 14. ✓
- Part 2 vault (skill, agent, reference, gitignore) → Tasks 16–19. ✓

**Type consistency:** `Registry` method names (`upsert_recording`, `set_status`, `mark_*`, `expire_new`, `set_vault_id`, `list_recordings`, `get_recording`, `get_participants`, `get_meta`/`set_meta`) are used identically across registry, cli, and migration tasks. Module functions (`recording_fields_from_api`, `participants_from_api`, `parse_*`, `migrate_from_vault`, `render_markdown_mirror`, `today_str`, `resolve_db_path`, `DEFAULT_DB_PATH`) match between definition and call sites. ✓

**Placeholder scan:** every code step contains complete code; no TBD/"add error handling"/"similar to". ✓

**Note for the implementer:** Task 2.5's `test_upsert_is_idempotent_and_preserves_status` depends on `set_status` (Task 3). If executing strictly task-by-task, implement Task 3's `set_status` before running that specific assertion, or run the upsert tests with `-k "upsert and not idempotent"` first. The plan calls this out in Task 2.5 Step 2.
```
