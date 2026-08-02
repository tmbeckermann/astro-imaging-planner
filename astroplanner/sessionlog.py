"""SQLite-backed imaging session log."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path.home() / ".astroplanner" / "sessions.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    target TEXT NOT NULL,
    filter TEXT,
    sub_s REAL,
    subs INTEGER,
    notes TEXT,
    created_at TEXT NOT NULL
);
"""


@dataclass
class SessionEntry:
    id: int
    date: str
    target: str
    filter: str | None
    sub_s: float | None
    subs: int | None
    notes: str | None

    @property
    def total_minutes(self) -> float | None:
        if self.sub_s and self.subs:
            return self.sub_s * self.subs / 60.0
        return None


class SessionLog:
    def __init__(self, db_path: str | Path = DEFAULT_DB):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.execute(_SCHEMA)
        self.conn.commit()

    def add(
        self,
        date: str,
        target: str,
        filter_name: str | None = None,
        sub_s: float | None = None,
        subs: int | None = None,
        notes: str | None = None,
    ) -> int:
        cur = self.conn.execute(
            "INSERT INTO sessions (date, target, filter, sub_s, subs, notes, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (date, target, filter_name, sub_s, subs, notes,
             datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list(self, target: str | None = None) -> list[SessionEntry]:
        q = "SELECT id, date, target, filter, sub_s, subs, notes FROM sessions"
        args: tuple = ()
        if target:
            q += " WHERE target LIKE ?"
            args = (f"%{target}%",)
        q += " ORDER BY date DESC, id DESC"
        return [SessionEntry(*row) for row in self.conn.execute(q, args)]

    def close(self):
        self.conn.close()
