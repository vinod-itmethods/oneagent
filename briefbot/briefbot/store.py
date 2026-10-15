"""SQLite storage for messages waiting on your reply and threads you take part in."""

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS pending (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    channel      TEXT NOT NULL,
    ts           TEXT NOT NULL,
    thread_ts    TEXT,
    user         TEXT,
    text         TEXT,
    kind         TEXT NOT NULL,          -- dm | group_dm | mention | thread_reply
    created_at   REAL NOT NULL,
    resolved_at  REAL,
    resolved_how TEXT,                   -- reply | reaction | button | deleted
    UNIQUE (channel, ts)
);
CREATE INDEX IF NOT EXISTS pending_open ON pending (resolved_at, channel);

CREATE TABLE IF NOT EXISTS my_threads (
    channel   TEXT NOT NULL,
    thread_ts TEXT NOT NULL,
    seen_at   REAL NOT NULL,
    PRIMARY KEY (channel, thread_ts)
);

CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@dataclass
class Pending:
    id: int
    channel: str
    ts: str
    thread_ts: Optional[str]
    user: Optional[str]
    text: str
    kind: str
    created_at: float

    @property
    def age_hours(self) -> float:
        return (time.time() - float(self.ts)) / 3600


class Store:
    def __init__(self, path: str):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(SCHEMA)

    def _exec(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._db.execute(sql, params)
            self._db.commit()
            return cur

    # --- pending -----------------------------------------------------------

    def add_pending(self, channel, ts, thread_ts, user, text, kind) -> None:
        self._exec(
            "INSERT OR IGNORE INTO pending (channel, ts, thread_ts, user, text, kind, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (channel, ts, thread_ts, user, text, kind, time.time()),
        )

    def resolve_one(self, channel: str, ts: str, how: str) -> int:
        return self._exec(
            "UPDATE pending SET resolved_at = ?, resolved_how = ? "
            "WHERE channel = ? AND ts = ? AND resolved_at IS NULL",
            (time.time(), how, channel, ts),
        ).rowcount

    def resolve_by_id(self, item_id: int, how: str) -> int:
        return self._exec(
            "UPDATE pending SET resolved_at = ?, resolved_how = ? WHERE id = ? AND resolved_at IS NULL",
            (time.time(), how, item_id),
        ).rowcount

    def resolve_thread(self, channel: str, thread_ts: str, before_ts: str) -> int:
        """Resolve everything in a thread (including its parent) posted before `before_ts`."""
        return self._exec(
            "UPDATE pending SET resolved_at = ?, resolved_how = 'reply' "
            "WHERE channel = ? AND (thread_ts = ? OR ts = ?) AND CAST(ts AS REAL) < ? "
            "AND resolved_at IS NULL",
            (time.time(), channel, thread_ts, thread_ts, float(before_ts)),
        ).rowcount

    def resolve_top_level(self, channel: str, before_ts: str, from_users: Optional[list[str]] = None) -> int:
        """Resolve top-level (non-thread) items in a channel posted before `before_ts`."""
        sql = (
            "UPDATE pending SET resolved_at = ?, resolved_how = 'reply' "
            "WHERE channel = ? AND (thread_ts IS NULL OR thread_ts = ts) "
            "AND CAST(ts AS REAL) < ? AND resolved_at IS NULL"
        )
        params: tuple = (time.time(), channel, float(before_ts))
        if from_users is not None:
            if not from_users:
                return 0
            sql += f" AND user IN ({','.join('?' * len(from_users))})"
            params += tuple(from_users)
        return self._exec(sql, params).rowcount

    def open_items(self, max_age_days: int) -> list[Pending]:
        cutoff = time.time() - max_age_days * 86400
        rows = self._exec(
            "SELECT id, channel, ts, thread_ts, user, text, kind, created_at FROM pending "
            "WHERE resolved_at IS NULL AND CAST(ts AS REAL) >= ? ORDER BY CAST(ts AS REAL)",
            (cutoff,),
        ).fetchall()
        return [Pending(**dict(r)) for r in rows]

    # --- threads I'm in ------------------------------------------------------

    def remember_thread(self, channel: str, thread_ts: str) -> None:
        self._exec(
            "INSERT OR REPLACE INTO my_threads (channel, thread_ts, seen_at) VALUES (?, ?, ?)",
            (channel, thread_ts, time.time()),
        )

    def is_my_thread(self, channel: str, thread_ts: str) -> bool:
        row = self._exec(
            "SELECT 1 FROM my_threads WHERE channel = ? AND thread_ts = ?", (channel, thread_ts)
        ).fetchone()
        return row is not None

    # --- key/value -----------------------------------------------------------

    def get(self, key: str, default=None):
        row = self._exec("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def put(self, key: str, value) -> None:
        self._exec("INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)", (key, json.dumps(value)))
