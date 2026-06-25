"""SQLite operational store for the KTalk recordings registry."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
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
    """Map a KTalk /api/recordings entity to registry row fields."""
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
    """Extract deduped participants with resolvable ktalk_id from an API entity."""
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
