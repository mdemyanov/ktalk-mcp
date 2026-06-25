"""SQLite operational store for the KTalk recordings registry."""

from __future__ import annotations

import json
import re
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


_KTALK_RE = re.compile(r"\(ktalk:([^)]+)\)")


def parse_participants_field(raw: str) -> list[dict]:
    """Parse 'Имя Фамилия (ktalk:ID), ...' into participant dicts."""
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
    """Parse '61 мин' / '1 ч 5 мин' into minutes; '—'/'' -> None."""
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
        if not cells or cells[0] == "recording_id":
            continue
        if all(set(c) <= {"-", ":"} for c in cells):  # separator row
            continue
        rows.append(cells)
    return rows


def _nullable_path(value: str) -> str | None:
    value = value.strip()
    return None if value in ("", "—") else value


def parse_unprocessed_table(text: str) -> list[dict]:
    """Parse the 6-column 'Необработанные записи' table."""
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
    """Parse the 7-column archive table."""
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


def migrate_from_vault(
    registry: Registry,
    vault_path: str | Path,
    *,
    dry_run: bool = False,
    now: str | None = None,
) -> dict:
    """Import existing markdown registries into the SQLite store. Idempotent."""
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
    """Render a read-only markdown mirror of the registry for git visibility."""
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
