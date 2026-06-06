"""TUI history — sqlite-backed log of recent queries/results.

Persists to ~/.local/share/deepsearch/history.sqlite3 (XDG-compliant).
Schema is intentionally minimal: a single `events` table.
"""

from __future__ import annotations

import os
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

DATA_DIR = Path(
    os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")
) / "deepsearch"
DB_PATH = DATA_DIR / "history.sqlite3"


@dataclass
class HistoryEvent:
    id: int
    tab: str
    query: str
    result_summary: str
    elapsed_ms: int
    ts: float
    model: str


class HistoryDB:
    """SQLite-backed history. Thread-safe via a per-instance lock."""

    def __init__(self, path: Path = DB_PATH, limit: int = 200) -> None:
        self.path = path
        self.limit = limit
        path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _init_schema(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tab TEXT NOT NULL,
                    query TEXT NOT NULL,
                    result_summary TEXT NOT NULL DEFAULT '',
                    elapsed_ms INTEGER NOT NULL DEFAULT 0,
                    ts REAL NOT NULL,
                    model TEXT NOT NULL DEFAULT ''
                )
                """
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC)"
            )
            con.commit()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        # check_same_thread=False: textual app is single-threaded but
        # the SDK is async. WAL mode lets reads happen concurrently
        # with writes; we serialize through the GIL anyway.
        con = sqlite3.connect(str(self.path), check_same_thread=False)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        try:
            yield con
        finally:
            con.close()

    def add(
        self,
        tab: str,
        query: str,
        result_summary: str = "",
        elapsed_ms: int = 0,
        model: str = "",
    ) -> int:
        ts = time.time()
        with self._connect() as con:
            cur = con.execute(
                "INSERT INTO events (tab, query, result_summary, elapsed_ms, ts, model) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (tab, query, result_summary[:500], elapsed_ms, ts, model),
            )
            con.commit()
            event_id = cur.lastrowid
            # Trim to limit
            con.execute(
                "DELETE FROM events WHERE id NOT IN "
                "(SELECT id FROM events ORDER BY ts DESC LIMIT ?)",
                (self.limit,),
            )
            con.commit()
        return int(event_id)  # type: ignore[arg-type]

    def list_recent(self, limit: int = 50, tab: Optional[str] = None) -> list[HistoryEvent]:
        with self._connect() as con:
            if tab:
                rows = con.execute(
                    "SELECT id, tab, query, result_summary, elapsed_ms, ts, model "
                    "FROM events WHERE tab = ? ORDER BY ts DESC LIMIT ?",
                    (tab, limit),
                ).fetchall()
            else:
                rows = con.execute(
                    "SELECT id, tab, query, result_summary, elapsed_ms, ts, model "
                    "FROM events ORDER BY ts DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [
            HistoryEvent(
                id=r[0], tab=r[1], query=r[2], result_summary=r[3],
                elapsed_ms=r[4], ts=r[5], model=r[6],
            )
            for r in rows
        ]

    def search(self, term: str, limit: int = 50) -> list[HistoryEvent]:
        with self._connect() as con:
            rows = con.execute(
                "SELECT id, tab, query, result_summary, elapsed_ms, ts, model "
                "FROM events WHERE query LIKE ? OR result_summary LIKE ? "
                "ORDER BY ts DESC LIMIT ?",
                (f"%{term}%", f"%{term}%", limit),
            ).fetchall()
        return [
            HistoryEvent(
                id=r[0], tab=r[1], query=r[2], result_summary=r[3],
                elapsed_ms=r[4], ts=r[5], model=r[6],
            )
            for r in rows
        ]

    def clear(self) -> int:
        with self._connect() as con:
            cur = con.execute("DELETE FROM events")
            con.commit()
            return cur.rowcount

    def stats(self) -> dict:
        with self._connect() as con:
            total = con.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            by_tab = con.execute(
                "SELECT tab, COUNT(*) FROM events GROUP BY tab ORDER BY COUNT(*) DESC"
            ).fetchall()
        return {"total": total, "by_tab": dict(by_tab)}
