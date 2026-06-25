"""SQLite operational store for the KTalk recordings registry."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

SCHEMA_VERSION = "1"

_VALID_STATUSES = {"new", "processing", "done", "skipped", "partial"}

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
