"""Token usage and cost tracking with SQLite persistence."""

import json
import sqlite3
import os
from datetime import datetime, timezone
from contextlib import contextmanager
from dataclasses import dataclass, field, asdict


DB_PATH = os.getenv("TRACKER_DB", "/app/data/tracker.db")

# DeepSeek pricing (per 1M tokens), 2025-03
PRICING = {
    "deepseek-chat":     {"input": 0.27, "output": 1.10},
    "deepseek-reasoner": {"input": 0.55, "output": 2.19},
    "deepseek-v4-flash": {"input": 0.27, "output": 1.10},  # same as chat
}


@dataclass
class GenerationRecord:
    id: str
    rid: str
    model: str
    provider: str
    topic: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    duration_ms: int
    status: str
    error: str = ""
    created_at: str = ""


def _get_db() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS generations (
                id TEXT PRIMARY KEY,
                rid TEXT NOT NULL,
                model TEXT NOT NULL,
                provider TEXT NOT NULL,
                topic TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                total_tokens INTEGER NOT NULL DEFAULT 0,
                cost_usd REAL NOT NULL DEFAULT 0.0,
                duration_ms INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                error TEXT DEFAULT '',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_generations_created ON generations(created_at)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_generations_rid ON generations(rid)")
        db.commit()


def record_generation(rec: GenerationRecord):
    with _get_db() as db:
        db.execute(
            """INSERT INTO generations
               (id, rid, model, provider, topic, prompt_tokens, completion_tokens,
                total_tokens, cost_usd, duration_ms, status, error, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (rec.id, rec.rid, rec.model, rec.provider, rec.topic,
             rec.prompt_tokens, rec.completion_tokens, rec.total_tokens,
             rec.cost_usd, rec.duration_ms, rec.status, rec.error,
             rec.created_at or datetime.now(timezone.utc).isoformat()),
        )
        db.commit()


def calc_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Calculate cost in USD based on DeepSeek pricing."""
    p = PRICING.get(model, {"input": 0.27, "output": 1.10})
    return (prompt_tokens / 1_000_000) * p["input"] + (completion_tokens / 1_000_000) * p["output"]


def get_stats() -> dict:
    with _get_db() as db:
        row = db.execute("""
            SELECT
                COUNT(*) as total_generations,
                COALESCE(SUM(prompt_tokens), 0) as total_prompt_tokens,
                COALESCE(SUM(completion_tokens), 0) as total_completion_tokens,
                COALESCE(SUM(total_tokens), 0) as total_tokens,
                COALESCE(SUM(cost_usd), 0.0) as total_cost_usd,
                COALESCE(AVG(duration_ms), 0) as avg_duration_ms
            FROM generations WHERE status = 'success'
        """).fetchone()
        return dict(row)


def get_history(limit: int = 20, offset: int = 0) -> list[dict]:
    with _get_db() as db:
        rows = db.execute(
            "SELECT * FROM generations ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [dict(r) for r in rows]
