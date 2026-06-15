"""Knowledge Warehouse — persistent content repository for crawled pages.

Receives content from the crawler service, stores in SQLite with full-text search.
Provides query API for agents to retrieve stored knowledge.

Sync layer (v2.1): on every successful body-class ingest the row is also
embedded into the vector-store with id `wh-{row_id}`. That keeps the FTS5 +
dense index in lock-step so hybrid retrieval (BM25 ⊕ vectors with RRF) always
has both halves to work with.
"""

import asyncio
import hashlib
import httpx
import json
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from libs.common.yaml_config import load_service_config

# ─── Config ───────────────────────────────────────────────
DATA_DIR = Path(os.environ.get("WAREHOUSE_DATA_DIR", "/app/data"))
DB_PATH = DATA_DIR / "warehouse.db"
MAX_CONTENT_LENGTH = int(os.environ.get("WAREHOUSE_MAX_CONTENT", "100000"))

VECTOR_STORE_URL = os.environ.get("VECTOR_STORE_URL", "http://vector-store:8004")
# Bodies under this word count don't get vector-indexed (snippets, withdrawn
# papers, etc.) — they'd just pollute the dense index without semantic value.
MIN_EMBED_WORDS = int(os.environ.get("MIN_EMBED_WORDS", "150"))
# Cap the embedding input — most embedding models truncate around 512 tokens
# anyway, and we want to send the most signal-rich first chunk.
EMBED_TEXT_CAP = int(os.environ.get("EMBED_TEXT_CAP", "4000"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [warehouse] %(message)s",
)
log = logging.getLogger("warehouse")

# ─── YAML config (quality gate, etc.) ──────────────────────
# Loaded once at import; values are immutable for the process lifetime.
# Restart the warehouse to pick up edits to
# infra/config/services/knowledge-warehouse.yaml.
_CONFIG_DEFAULTS: dict = {
    "quality_gate": {
        "enabled": True,
        "min_word_count": 150,
        "min_extraction_confidence": 0.30,
        "reject_nav_dumps": True,
        "per_category": {},
    },
}
CONFIG = load_service_config("knowledge-warehouse", defaults=_CONFIG_DEFAULTS)
QUALITY_GATE = CONFIG.get("quality_gate", _CONFIG_DEFAULTS["quality_gate"])

# In-process counters for /stats. SQLite stays the source of truth for the
# *current* state; these are just "how many rejections has this process
# seen since boot", reset on restart. Good enough for ops visibility.
_quality_rejected_total = 0
_quality_rejected_by_reason: dict[str, int] = {}


def _nav_dump_score(markdown: str) -> bool:
    """Cheap is-this-page-just-navigation check.

    Two signals: (1) a sea of short lines (likely menu items), and
    (2) low sentence density relative to line count. Either trips it.
    Same heuristic the crawler uses on OCR output — applied here so HTML
    nav dumps that survive `strip_boilerplate` also get caught.
    """
    if not markdown:
        return True
    lines = [l for l in markdown.split("\n") if l.strip()]
    if not lines:
        return True
    short = sum(1 for l in lines if len(l.strip()) < 40)
    short_frac = short / len(lines)
    # Sentence-ish: capitalized word followed by 20+ chars and a terminator.
    import re as _re
    sentences = len(_re.findall(r"[A-Z][^\.!?\n]{20,}[\.!?]", markdown))
    return short_frac > 0.70 and sentences < 3


def _quality_gate_decide(
    *, word_count: int, extraction_confidence: Optional[float],
    category: Optional[str], markdown: str,
) -> Optional[str]:
    """Return None to allow ingest, or a short rejection reason string."""
    gate = QUALITY_GATE
    if not gate.get("enabled", True):
        return None

    # Per-category overrides (e.g. code:30 words instead of 150).
    overrides = (gate.get("per_category") or {}).get(category) or {}

    min_wc = overrides.get("min_word_count", gate.get("min_word_count", 150))
    if word_count < min_wc:
        return f"word_count:{word_count}<{min_wc}"

    min_conf = overrides.get("min_extraction_confidence",
                             gate.get("min_extraction_confidence", 0.30))
    if extraction_confidence is not None and extraction_confidence < min_conf:
        return f"confidence:{extraction_confidence:.2f}<{min_conf}"

    if gate.get("reject_nav_dumps", True) and _nav_dump_score(markdown):
        return "nav_dump"

    return None


def _record_rejection(reason: str) -> None:
    global _quality_rejected_total
    _quality_rejected_total += 1
    _quality_rejected_by_reason[reason] = _quality_rejected_by_reason.get(reason, 0) + 1


app = FastAPI(title="Knowledge Warehouse", version="2.0.0")


# ─── Database — single-writer pattern for concurrent safety ──
_write_lock = threading.Lock()
_write_conn: sqlite3.Connection | None = None


def _get_write_conn() -> sqlite3.Connection:
    """Get the single write connection (thread-safe, auto-reconnect)."""
    global _write_conn
    _write_lock.acquire()
    try:
        if _write_conn is None:
            _write_conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
            _write_conn.execute("PRAGMA journal_mode=WAL")
            _write_conn.execute("PRAGMA synchronous=NORMAL")
            _write_conn.execute("PRAGMA busy_timeout=10000")
            _write_conn.execute("PRAGMA cache_size=-8000")  # 8MB cache
            log.info("write_connection_opened")
        return _write_conn
    except Exception:
        _write_lock.release()
        raise


@contextmanager
def write_txn():
    """Context manager for write transactions. Auto-commits on success, rolls back on error."""
    conn = _get_write_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        _write_lock.release()


def _read_conn() -> sqlite3.Connection:
    """Get a read-only connection (safe without lock in WAL mode)."""
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA query_only=ON")
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    """Initialize the warehouse schema. v2 introduces versioning + dedup + lineage.

    Schema v2 model:
      • content       — one row per (url_hash, revision). Latest revision has is_current=1.
      • content_alias — URLs that resolved to the SAME content_sha256 (mirrors, share links).
      • content_fts   — full-text index over current revisions only (rebuilt on migration).

    Migration is idempotent: detects v1 by missing `content_sha256` column, rebuilds in place.
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with write_txn() as conn:
        conn.execute("PRAGMA journal_mode=WAL")

        # v2 content table (no UNIQUE on url_hash — multiple revisions allowed)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url_hash TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT,
                markdown TEXT NOT NULL,
                content TEXT,
                author TEXT,
                published TEXT,
                language TEXT,
                word_count INTEGER DEFAULT 0,
                source_domain TEXT,
                ingested_at REAL NOT NULL,
                last_seen_at REAL,
                tags TEXT DEFAULT '[]',
                content_sha256 TEXT,
                revision INTEGER DEFAULT 1,
                is_current INTEGER DEFAULT 1,
                supersedes INTEGER,
                seen_in_session TEXT,
                found_via_query TEXT,
                extractor TEXT,
                extraction_confidence REAL,
                source_provider TEXT,
                status TEXT DEFAULT 'active'
            )
        """)

        # Detect + migrate from v1 (no content_sha256 column).
        cols = {r[1] for r in conn.execute("PRAGMA table_info(content)").fetchall()}
        if "content_sha256" not in cols:
            log.info("migrating_schema v1 → v2 (versioning + dedup + lineage)")
            for col_def in [
                "last_seen_at REAL",
                "content_sha256 TEXT",
                "revision INTEGER DEFAULT 1",
                "is_current INTEGER DEFAULT 1",
                "supersedes INTEGER",
                "seen_in_session TEXT",
                "found_via_query TEXT",
                "extractor TEXT",
                "extraction_confidence REAL",
                "source_provider TEXT",
                "status TEXT DEFAULT 'active'",
            ]:
                col_name = col_def.split()[0]
                if col_name not in cols:
                    conn.execute(f"ALTER TABLE content ADD COLUMN {col_def}")
            # Backfill content_sha256 for existing rows from their markdown.
            import hashlib
            backfilled = 0
            for row in conn.execute("SELECT id, markdown FROM content WHERE content_sha256 IS NULL").fetchall():
                rid, md = row[0], row[1] or ""
                sha = hashlib.sha256(md.encode("utf-8", errors="replace")).hexdigest()
                conn.execute("UPDATE content SET content_sha256=?, is_current=1, revision=1 WHERE id=?", (sha, rid))
                backfilled += 1
            log.info("schema_v2_migrated rows_backfilled=%d", backfilled)

        # Drop the legacy UNIQUE(url_hash) constraint if it's still there —
        # revisions need multiple rows per url_hash. SQLite needs a table rebuild.
        # We detect by checking the table SQL for UNIQUE on url_hash.
        sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='content'").fetchone()
        if sql and "url_hash TEXT UNIQUE" in sql[0]:
            log.info("rebuilding_content_table to drop legacy UNIQUE(url_hash) constraint")
            conn.execute("DROP TRIGGER IF EXISTS content_ai")
            conn.execute("DROP TRIGGER IF EXISTS content_ad")
            # Create the v2 table under a temp name
            conn.execute("""
                CREATE TABLE content_v2 (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url_hash TEXT NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT,
                    markdown TEXT NOT NULL,
                    content TEXT,
                    author TEXT,
                    published TEXT,
                    language TEXT,
                    word_count INTEGER DEFAULT 0,
                    source_domain TEXT,
                    ingested_at REAL NOT NULL,
                    last_seen_at REAL,
                    tags TEXT DEFAULT '[]',
                    content_sha256 TEXT,
                    revision INTEGER DEFAULT 1,
                    is_current INTEGER DEFAULT 1,
                    supersedes INTEGER,
                    seen_in_session TEXT,
                    found_via_query TEXT,
                    extractor TEXT,
                    extraction_confidence REAL,
                    source_provider TEXT,
                    status TEXT DEFAULT 'active'
                )
            """)
            conn.execute("""
                INSERT INTO content_v2
                SELECT id, url_hash, url, title, markdown, content, author, published, language,
                       word_count, source_domain, ingested_at, last_seen_at, tags,
                       content_sha256, revision, is_current, supersedes,
                       seen_in_session, found_via_query, extractor, extraction_confidence,
                       source_provider, status
                FROM content
            """)
            conn.execute("DROP TABLE IF EXISTS content_fts")
            conn.execute("DROP TABLE content")
            conn.execute("ALTER TABLE content_v2 RENAME TO content")
            # Indexes + FTS will be recreated below (idempotent CREATE IF NOT EXISTS).
            moved = conn.execute("SELECT COUNT(*) FROM content").fetchone()[0]
            log.info("content_table_rebuilt rows=%d (UNIQUE constraint dropped)", moved)

        # Aliases — same content_sha256 reachable from multiple URLs (mirrors)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS content_alias (
                content_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                first_seen REAL NOT NULL,
                PRIMARY KEY (content_id, url),
                FOREIGN KEY (content_id) REFERENCES content(id) ON DELETE CASCADE
            )
        """)

        for stmt in [
            "CREATE INDEX IF NOT EXISTS idx_warehouse_domain ON content(source_domain)",
            "CREATE INDEX IF NOT EXISTS idx_warehouse_ingested ON content(ingested_at)",
            "CREATE INDEX IF NOT EXISTS idx_warehouse_url_hash ON content(url_hash)",
            "CREATE INDEX IF NOT EXISTS idx_warehouse_sha ON content(content_sha256)",
            "CREATE INDEX IF NOT EXISTS idx_warehouse_current ON content(url_hash, is_current)",
            "CREATE INDEX IF NOT EXISTS idx_warehouse_session ON content(seen_in_session)",
            "CREATE INDEX IF NOT EXISTS idx_warehouse_lastseen ON content(last_seen_at)",
        ]:
            conn.execute(stmt)

        # Re-crawl scheduler bookkeeping (v2.2).
        # Tracks the last time we asked the crawler to re-fetch this URL so we
        # can back off on URLs that consistently fail (last_seen_at only moves
        # forward on a SUCCESSFUL re-ingest).
        cols2 = {r[1] for r in conn.execute("PRAGMA table_info(content)").fetchall()}
        if "last_recrawl_attempt_at" not in cols2:
            conn.execute("ALTER TABLE content ADD COLUMN last_recrawl_attempt_at REAL")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_warehouse_recrawl_attempt ON content(last_recrawl_attempt_at)")
            log.info("recrawl_attempt_column_added")

        # Category column (v2.3) — auto-classify each row into a high-level
        # bucket so the TUI/CLI can filter. Cheap rule-based pass — no LLM.
        if "category" not in cols2:
            conn.execute("ALTER TABLE content ADD COLUMN category TEXT")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_warehouse_category ON content(category)")
            log.info("category_column_added")

        # Legacy rows inserted before last_seen_at was wired into the INSERT
        # paths have NULL — backfill from ingested_at so the re-crawl picker
        # has something to chew on. One-shot, idempotent.
        backfilled = conn.execute(
            "UPDATE content SET last_seen_at = ingested_at WHERE last_seen_at IS NULL"
        ).rowcount
        if backfilled:
            log.info("last_seen_at_backfilled rows=%d", backfilled)

        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS content_fts USING fts5(
                title, markdown, content, url, author,
                content='content', content_rowid='id'
            )
        """)
        # Integrity check + auto-rebuild. The table rebuild above leaves
        # content_fts_docsize empty even though the external content-table
        # row count looks fine. Detect by comparing docsize vs content count.
        try:
            doc_n = conn.execute("SELECT COUNT(*) FROM content_fts_docsize").fetchone()[0]
            row_n = conn.execute("SELECT COUNT(*) FROM content").fetchone()[0]
            if doc_n < row_n:
                log.warning("fts5_stale doc_n=%d row_n=%d — rebuilding", doc_n, row_n)
                conn.execute("INSERT INTO content_fts(content_fts) VALUES('rebuild')")
                log.info("fts5_rebuilt")
        except Exception as e:
            log.warning("fts5_check_failed: %s — forcing rebuild", e)
            try:
                conn.execute("INSERT INTO content_fts(content_fts) VALUES('rebuild')")
                log.info("fts5_rebuilt")
            except Exception as e2:
                log.error("fts5_rebuild_failed: %s", e2)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS content_ai AFTER INSERT ON content BEGIN
                INSERT INTO content_fts(rowid, title, markdown, content, url, author)
                VALUES (new.id, new.title, new.markdown, new.content, new.url, new.author);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS content_ad AFTER DELETE ON content BEGIN
                INSERT INTO content_fts(content_fts, rowid, title, markdown, content, url, author)
                VALUES ('delete', old.id, old.title, old.markdown, old.content, old.url, old.author);
            END
        """)
        conn.commit()


_init_db()


# ─── WAL checkpoint background task ───────────────────────────
import asyncio as _asyncio

WAL_CHECKPOINT_INTERVAL_SEC = int(os.environ.get("WAL_CHECKPOINT_INTERVAL_SEC", "300"))

async def _wal_checkpoint_loop():
    while True:
        await _asyncio.sleep(WAL_CHECKPOINT_INTERVAL_SEC)
        try:
            with write_txn() as conn:
                r = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                log.info("wal_checkpoint result=%s", tuple(r) if r else None)
        except Exception as e:
            log.warning("wal_checkpoint_failed: %s", e)

@app.on_event("startup")
async def _start_wal_checkpoint():
    _asyncio.create_task(_wal_checkpoint_loop())
    log.info("wal_checkpoint_loop scheduled interval=%ds", WAL_CHECKPOINT_INTERVAL_SEC)


# ─── Re-crawl scheduler ───────────────────────────────────────────────
# Walks the current-revision rows and asks the crawler to re-fetch any URL
# whose last_seen_at is older than the per-domain TTL. The crawler routes
# the result back into /ingest, so unchanged content just bumps last_seen_at
# while changed content lands as a new revision via the dedup logic.

RECRAWL_ENABLED = os.environ.get("RECRAWL_ENABLED", "false").lower() in {"1", "true", "yes"}
RECRAWL_INTERVAL_SEC = int(os.environ.get("RECRAWL_INTERVAL_SEC", "1800"))
RECRAWL_BATCH = int(os.environ.get("RECRAWL_BATCH", "20"))
RECRAWL_CONCURRENCY = int(os.environ.get("RECRAWL_CONCURRENCY", "3"))
RECRAWL_DEFAULT_TTL_SEC = int(os.environ.get("RECRAWL_DEFAULT_TTL_SEC", str(14 * 86400)))
RECRAWL_MIN_GAP_SEC = int(os.environ.get("RECRAWL_MIN_GAP_SEC", str(3600)))
CRAWLER_URL = os.environ.get("CRAWLER_URL", "http://crawler:8000")

# Per-domain TTL overrides (JSON). Defaults reflect content cadence:
# news/socials change often, docs/papers rarely.
_DEFAULT_DOMAIN_TTLS = {
    # daily-ish
    "news.ycombinator.com": 6 * 3600,
    "reddit.com": 6 * 3600,
    "twitter.com": 6 * 3600,
    "x.com": 6 * 3600,
    "nytimes.com": 86400,
    "bbc.com": 86400,
    "theverge.com": 86400,
    # weekly
    "github.com": 7 * 86400,
    # rarely change
    "wikipedia.org": 30 * 86400,
    "arxiv.org": 90 * 86400,
    "rust-lang.org": 30 * 86400,
}
try:
    _override = json.loads(os.environ.get("RECRAWL_DOMAIN_TTLS_JSON", "{}"))
    if isinstance(_override, dict):
        for k, v in _override.items():
            _DEFAULT_DOMAIN_TTLS[str(k)] = int(v)
except Exception as _e:
    log.warning("recrawl_domain_ttls_parse_failed: %s", _e)

_recrawl_state = {
    "started_at": None,
    "ticks": 0,
    "last_tick_at": None,
    "last_picked": 0,
    "last_kicked": 0,
    "last_errors": 0,
    "total_kicked": 0,
    "total_errors": 0,
    "in_flight": 0,
}


def _ttl_for_domain(domain: Optional[str]) -> int:
    if not domain:
        return RECRAWL_DEFAULT_TTL_SEC
    d = domain.lower().lstrip(".")
    # walk up subdomain tree: news.foo.com → foo.com
    parts = d.split(".")
    for i in range(len(parts) - 1):
        candidate = ".".join(parts[i:])
        if candidate in _DEFAULT_DOMAIN_TTLS:
            return _DEFAULT_DOMAIN_TTLS[candidate]
    return RECRAWL_DEFAULT_TTL_SEC


def _pick_stale(limit: int = 20) -> list[dict]:
    """Pick up to `limit` current-revision rows whose last_seen_at is past TTL
    and which we haven't tried to re-crawl in the last RECRAWL_MIN_GAP_SEC.
    Returns a small dict per row with just what the scheduler needs."""
    now = time.time()
    # Use a read-only connection (the warehouse's writes are single-threaded
    # behind _write_lock; reads are safe in WAL mode).
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        # Pull a larger window and filter per-domain TTL in Python — SQLite
        # can't express per-domain TTL cleanly. Worst case: a couple hundred
        # rows examined per tick.
        rows = conn.execute(
            """
            SELECT id, url, source_domain, last_seen_at, last_recrawl_attempt_at
            FROM content
            WHERE is_current = 1
              AND status = 'active'
              AND last_seen_at IS NOT NULL
              AND (last_recrawl_attempt_at IS NULL OR last_recrawl_attempt_at < ?)
            ORDER BY last_seen_at ASC
            LIMIT ?
            """,
            (now - RECRAWL_MIN_GAP_SEC, limit * 10),
        ).fetchall()
    finally:
        conn.close()

    picks: list[dict] = []
    for r in rows:
        ttl = _ttl_for_domain(r["source_domain"])
        if (now - r["last_seen_at"]) >= ttl:
            picks.append({
                "id": r["id"],
                "url": r["url"],
                "domain": r["source_domain"],
                "age_sec": int(now - r["last_seen_at"]),
                "ttl_sec": ttl,
            })
        if len(picks) >= limit:
            break
    return picks


def _mark_attempt(row_id: int) -> None:
    now = time.time()
    try:
        with write_txn() as conn:
            conn.execute(
                "UPDATE content SET last_recrawl_attempt_at = ? WHERE id = ?",
                (now, row_id),
            )
    except Exception as e:
        log.warning("recrawl_mark_attempt_failed id=%d err=%s", row_id, e)


async def _recrawl_one(client: httpx.AsyncClient, pick: dict) -> bool:
    """POST one URL to the crawler. Returns True on 2xx, False otherwise."""
    _recrawl_state["in_flight"] += 1
    _mark_attempt(pick["id"])
    try:
        payload = {
            "url": pick["url"],
            "bypass_cache": True,
            "source_provider": "recrawl",
            "found_via_query": "recrawl-scheduler",
        }
        r = await client.post(f"{CRAWLER_URL}/crawl", json=payload, timeout=120.0)
        ok = r.status_code == 200
        if not ok:
            log.warning(
                "recrawl_kick_fail id=%d url=%s status=%d body=%s",
                pick["id"], pick["url"][:120], r.status_code, r.text[:200],
            )
        else:
            log.info(
                "recrawl_kick_ok id=%d url=%s age=%ds ttl=%ds",
                pick["id"], pick["url"][:120], pick["age_sec"], pick["ttl_sec"],
            )
        return ok
    except Exception as e:
        log.warning("recrawl_kick_err id=%d url=%s err=%s",
                    pick["id"], pick["url"][:120], e)
        return False
    finally:
        _recrawl_state["in_flight"] -= 1


async def _recrawl_tick(limit: int) -> dict:
    """One scheduler tick: pick stale URLs and kick them, bounded concurrency."""
    picks = _pick_stale(limit=limit)
    _recrawl_state["last_picked"] = len(picks)
    if not picks:
        return {"picked": 0, "kicked": 0, "errors": 0}

    sem = _asyncio.Semaphore(RECRAWL_CONCURRENCY)
    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        async def _bounded(pick: dict) -> bool:
            async with sem:
                return await _recrawl_one(client, pick)
        results = await _asyncio.gather(*(_bounded(p) for p in picks),
                                        return_exceptions=True)
    kicked = sum(1 for r in results if r is True)
    errors = sum(1 for r in results if r is not True)
    _recrawl_state["last_kicked"] = kicked
    _recrawl_state["last_errors"] = errors
    _recrawl_state["total_kicked"] += kicked
    _recrawl_state["total_errors"] += errors
    _recrawl_state["last_tick_at"] = time.time()
    _recrawl_state["ticks"] += 1
    return {"picked": len(picks), "kicked": kicked, "errors": errors}


async def _recrawl_loop():
    log.info(
        "recrawl_loop_starting interval=%ds batch=%d concurrency=%d default_ttl=%ds",
        RECRAWL_INTERVAL_SEC, RECRAWL_BATCH, RECRAWL_CONCURRENCY, RECRAWL_DEFAULT_TTL_SEC,
    )
    _recrawl_state["started_at"] = time.time()
    # Small initial delay so we don't fire during startup.
    await _asyncio.sleep(60)
    while True:
        try:
            result = await _recrawl_tick(RECRAWL_BATCH)
            log.info("recrawl_tick %s", result)
        except Exception as e:
            log.warning("recrawl_tick_failed: %s", e)
        await _asyncio.sleep(RECRAWL_INTERVAL_SEC)


@app.on_event("startup")
async def _start_recrawl_loop():
    if RECRAWL_ENABLED:
        _asyncio.create_task(_recrawl_loop())
    else:
        log.info("recrawl_loop_disabled (set RECRAWL_ENABLED=true to enable)")


@app.get("/admin/recrawl-status")
async def recrawl_status():
    """Return the scheduler's current state + a peek at the next pick batch."""
    next_batch = _pick_stale(limit=RECRAWL_BATCH) if RECRAWL_ENABLED else []
    return {
        "enabled": RECRAWL_ENABLED,
        "interval_sec": RECRAWL_INTERVAL_SEC,
        "batch": RECRAWL_BATCH,
        "concurrency": RECRAWL_CONCURRENCY,
        "default_ttl_sec": RECRAWL_DEFAULT_TTL_SEC,
        "min_gap_sec": RECRAWL_MIN_GAP_SEC,
        "domain_ttls": _DEFAULT_DOMAIN_TTLS,
        "state": _recrawl_state,
        "next_batch_preview": next_batch,
    }


@app.post("/admin/recrawl-now")
async def recrawl_now(limit: int = Query(20, ge=1, le=200)):
    """Force a single re-crawl tick now (does not require RECRAWL_ENABLED)."""
    result = await _recrawl_tick(limit=limit)
    return {"ok": True, **result}


# ─── Feed watcher (v2.3) ────────────────────────────────────────────────
# Register RSS/Atom feeds and poll them periodically. New entries get queued
# through the crawler's async-ingest endpoint so they accumulate in the
# warehouse without operator intervention.
#
# Storage: SQLite table `watched_feeds` next to the recrawl + content dbs.
# Worker: a single asyncio task that picks feeds where next_poll_at < now.

WATCH_ENABLED = os.environ.get("WATCH_ENABLED", "true").lower() in {"1", "true", "yes"}
WATCH_TICK_INTERVAL_SEC = int(os.environ.get("WATCH_TICK_INTERVAL_SEC", "120"))
WATCH_DEFAULT_INTERVAL_SEC = int(os.environ.get("WATCH_DEFAULT_INTERVAL_SEC", "3600"))

_WATCH_DB = DATA_DIR / "watched_feeds.db"


def _init_watched_feeds() -> None:
    conn = sqlite3.connect(str(_WATCH_DB))
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS watched_feeds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                feed_url TEXT NOT NULL,
                name TEXT,
                interval_sec INTEGER NOT NULL,
                last_polled_at REAL,
                last_etag TEXT,
                last_modified TEXT,
                last_status TEXT,
                last_entry_ids TEXT,
                total_polls INTEGER DEFAULT 0,
                total_new_entries INTEGER DEFAULT 0,
                total_ingested INTEGER DEFAULT 0,
                created_at REAL NOT NULL,
                disabled INTEGER DEFAULT 0
            )
        """)
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_watch_feed_url ON watched_feeds(feed_url)"
        )
        conn.commit()
    finally:
        conn.close()


_init_watched_feeds()


def _watch_conn():
    conn = sqlite3.connect(str(_WATCH_DB))
    conn.row_factory = sqlite3.Row
    return conn


async def _poll_one_feed(feed_row: dict) -> dict:
    """Fetch a single feed conditionally (etag/last-modified), parse, queue
    new entry URLs for ingest. Returns a small result dict for telemetry.
    """
    import feedparser

    fid = feed_row["id"]
    feed_url = feed_row["feed_url"]
    headers: dict = {"User-Agent": "deepsearchstack-watcher/2.3"}
    if feed_row.get("last_etag"):
        headers["If-None-Match"] = feed_row["last_etag"]
    if feed_row.get("last_modified"):
        headers["If-Modified-Since"] = feed_row["last_modified"]

    new_entries: list[str] = []
    last_status = "ok"
    etag = feed_row.get("last_etag")
    last_modified = feed_row.get("last_modified")
    queued = 0
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            r = await client.get(feed_url, headers=headers)
        if r.status_code == 304:
            last_status = "not_modified"
        elif r.status_code != 200:
            last_status = f"http_{r.status_code}"
        else:
            etag = r.headers.get("ETag", etag)
            last_modified = r.headers.get("Last-Modified", last_modified)
            parsed = feedparser.parse(r.text)
            prior_ids = set(json.loads(feed_row.get("last_entry_ids") or "[]"))
            entry_ids_seen: list[str] = []
            for entry in (parsed.entries or [])[:200]:
                eid = entry.get("id") or entry.get("link")
                if not eid:
                    continue
                entry_ids_seen.append(eid)
                if eid in prior_ids:
                    continue
                link = entry.get("link")
                if link:
                    new_entries.append(link)
            # Queue any new URLs through the crawler.
            if new_entries:
                try:
                    payload = {
                        "urls": new_entries,
                        "concurrency": 4,
                        "source_provider": f"watch:{fid}",
                    }
                    async with httpx.AsyncClient(timeout=15.0) as client:
                        r2 = await client.post(
                            f"{CRAWLER_URL}/ingest/urls/async",
                            json=payload,
                        )
                    if r2.status_code == 200:
                        queued = len(new_entries)
                    else:
                        log.warning(
                            "watch_queue_fail fid=%d status=%d body=%s",
                            fid, r2.status_code, r2.text[:200],
                        )
                except Exception as e:
                    log.warning("watch_queue_err fid=%d err=%s", fid, e)
            # Trim entry_ids_seen so the cache doesn't grow forever.
            entry_ids_seen = entry_ids_seen[:500]
    except Exception as e:
        last_status = f"err:{type(e).__name__}"
        log.warning("watch_poll_err fid=%d feed=%s err=%s", fid, feed_url, e)

    now = time.time()
    with _watch_conn() as conn:
        conn.execute(
            """UPDATE watched_feeds
            SET last_polled_at = ?, last_etag = ?, last_modified = ?,
                last_status = ?, last_entry_ids = COALESCE(?, last_entry_ids),
                total_polls = total_polls + 1,
                total_new_entries = total_new_entries + ?,
                total_ingested = total_ingested + ?
            WHERE id = ?""",
            (
                now, etag, last_modified, last_status,
                json.dumps(entry_ids_seen) if last_status == "ok" else None,
                len(new_entries), queued, fid,
            ),
        )
        conn.commit()
    return {
        "feed_id": fid,
        "feed_url": feed_url,
        "status": last_status,
        "new_entries": len(new_entries),
        "queued": queued,
    }


async def _watch_loop():
    log.info("watch_loop_starting tick=%ds default_interval=%ds",
             WATCH_TICK_INTERVAL_SEC, WATCH_DEFAULT_INTERVAL_SEC)
    await _asyncio.sleep(30)  # don't fire during boot
    while True:
        try:
            now = time.time()
            with _watch_conn() as conn:
                feeds = [dict(r) for r in conn.execute(
                    "SELECT * FROM watched_feeds WHERE disabled = 0"
                ).fetchall()]
            due = [
                f for f in feeds
                if (not f["last_polled_at"])
                   or (now - f["last_polled_at"] >= f["interval_sec"])
            ]
            for f in due:
                res = await _poll_one_feed(f)
                log.info("watch_tick %s", res)
        except Exception as e:
            log.warning("watch_loop_err: %s", e)
        await _asyncio.sleep(WATCH_TICK_INTERVAL_SEC)


@app.on_event("startup")
async def _start_watch_loop():
    if WATCH_ENABLED:
        _asyncio.create_task(_watch_loop())
    else:
        log.info("watch_loop_disabled (set WATCH_ENABLED=true to enable)")


# ─── Watch endpoints ─────────────────────────────────────────────────────

class AddWatchRequest(BaseModel):
    feed_url: str = Field(..., min_length=1, max_length=2048)
    name: Optional[str] = None
    interval_sec: int = Field(default=WATCH_DEFAULT_INTERVAL_SEC, ge=60, le=86400)


@app.post("/watch/feeds")
async def add_feed(req: AddWatchRequest):
    """Register a new RSS/Atom feed for periodic ingestion."""
    now = time.time()
    try:
        with _watch_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO watched_feeds
                (feed_url, name, interval_sec, created_at)
                VALUES (?, ?, ?, ?)""",
                (req.feed_url, req.name, req.interval_sec, now),
            )
            conn.commit()
            return {"id": cursor.lastrowid, "feed_url": req.feed_url,
                    "interval_sec": req.interval_sec}
    except sqlite3.IntegrityError:
        raise HTTPException(
            status_code=409,
            detail=f"feed already watched: {req.feed_url}",
        )


@app.get("/watch/feeds")
async def list_feeds():
    """List every registered feed with its bookkeeping."""
    with _watch_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM watched_feeds ORDER BY id ASC"
        ).fetchall()
        # Don't return last_entry_ids — large + uninteresting
        out = []
        for r in rows:
            d = dict(r)
            d.pop("last_entry_ids", None)
            out.append(d)
        return {"feeds": out, "count": len(out)}


@app.delete("/watch/feeds/{feed_id}")
async def remove_feed(feed_id: int):
    """Stop watching a feed."""
    with _watch_conn() as conn:
        cursor = conn.execute(
            "DELETE FROM watched_feeds WHERE id = ?", (feed_id,)
        )
        conn.commit()
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="feed not found")
        return {"removed": feed_id}


@app.post("/watch/feeds/{feed_id}/poll-now")
async def poll_feed_now(feed_id: int):
    """Force a poll of one feed without waiting for the next tick."""
    with _watch_conn() as conn:
        row = conn.execute(
            "SELECT * FROM watched_feeds WHERE id = ?", (feed_id,)
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="feed not found")
    res = await _poll_one_feed(dict(row))
    return res


# ─── Vector-store sync ───────────────────────────────────────────────────
# Shared HTTP client (one connection pool, kept warm) so we don't allocate
# on every ingest.
_vec_client: Optional[httpx.AsyncClient] = None


@app.on_event("startup")
async def _start_vec_client():
    global _vec_client
    _vec_client = httpx.AsyncClient(
        timeout=httpx.Timeout(20.0),
        limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
    )
    log.info("vector_client_ready url=%s", VECTOR_STORE_URL)


_embed_retry_task: Optional[asyncio.Task] = None


@app.on_event("startup")
async def _start_embed_retry_loop():
    global _embed_retry_task
    _embed_retry_task = asyncio.create_task(_embed_retry_loop())


@app.on_event("shutdown")
async def _stop_embed_retry_loop():
    global _embed_retry_task
    if _embed_retry_task is not None:
        _embed_retry_task.cancel()
        try:
            await _embed_retry_task
        except (asyncio.CancelledError, Exception):
            pass


@app.on_event("shutdown")
async def _stop_vec_client():
    global _vec_client
    if _vec_client is not None:
        await _vec_client.aclose()


# ─── Embed outbox (BUG-10) ───────────────────────────────────────────
# When vector-store is unreachable or returns non-200, the embed call
# previously fire-and-forget-logged the failure. The warehouse row was
# then permanently absent from the hybrid dense index. We now persist
# failed embeds to a SQLite outbox and drain it from a background
# worker — same shape as the crawler's pending_forwards.db pattern.
_EMBED_OUTBOX_DB = DATA_DIR / "pending_embeds.db"
_EMBED_RETRY_INTERVAL_SEC = int(os.environ.get("EMBED_RETRY_INTERVAL_SEC", "30"))
_EMBED_MAX_ATTEMPTS = int(os.environ.get("EMBED_MAX_ATTEMPTS", "12"))
_EMBED_DRAIN_BATCH = int(os.environ.get("EMBED_DRAIN_BATCH", "25"))


def _init_embed_outbox() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(_EMBED_OUTBOX_DB)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_embeds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                row_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                title TEXT DEFAULT '',
                markdown TEXT NOT NULL,
                word_count INTEGER DEFAULT 0,
                extractor TEXT DEFAULT '',
                attempts INTEGER DEFAULT 0,
                last_attempt REAL DEFAULT 0,
                created_at REAL NOT NULL,
                UNIQUE(row_id)
            )
        """)
        conn.commit()


_init_embed_outbox()


def _store_pending_embed(row_id: int, url: str, title: Optional[str],
                         markdown: str, word_count: int,
                         extractor: Optional[str]) -> None:
    """Persist a failed embed to the outbox. Idempotent on row_id —
    a re-ingest of the same row overwrites the prior payload so we
    always retry the freshest content."""
    try:
        with sqlite3.connect(str(_EMBED_OUTBOX_DB)) as conn:
            conn.execute(
                """
                INSERT INTO pending_embeds (row_id, url, title, markdown, word_count, extractor, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(row_id) DO UPDATE SET
                    url=excluded.url,
                    title=excluded.title,
                    markdown=excluded.markdown,
                    word_count=excluded.word_count,
                    extractor=excluded.extractor,
                    attempts=0,
                    created_at=excluded.created_at
                """,
                (row_id, url, title or "", markdown, word_count, extractor or "", time.time()),
            )
            conn.commit()
    except Exception as e:
        log.warning("embed_outbox_persist_failed row_id=%s err=%s", row_id, e)


def _pending_embeds_count() -> int:
    try:
        with sqlite3.connect(str(_EMBED_OUTBOX_DB)) as conn:
            return conn.execute("SELECT COUNT(*) FROM pending_embeds").fetchone()[0]
    except Exception:
        return -1


async def _try_post_embed(payload: dict) -> bool:
    """Single embed attempt. Returns True on 200, False otherwise.

    Uses _vec_client when available, else builds a one-shot client so
    the retry loop can run before _start_vec_client fires.
    """
    try:
        if _vec_client is not None:
            r = await _vec_client.post(f"{VECTOR_STORE_URL}/embed", json=payload)
        else:
            async with httpx.AsyncClient(timeout=10.0) as c:
                r = await c.post(f"{VECTOR_STORE_URL}/embed", json=payload)
        return r.status_code == 200
    except Exception:
        return False


async def _embed_to_vector_store(row_id: int, url: str, title: Optional[str],
                                  markdown: str, word_count: int,
                                  extractor: Optional[str]) -> None:
    """Fire-and-forget embed of a warehouse row into vector-store.

    Skipped for snippets / non-body rows (word_count < MIN_EMBED_WORDS) and
    for extractors we don't trust as semantic ground truth. On HTTP/network
    failure the payload is persisted to the embed outbox and retried from
    the background worker — see _embed_retry_loop().
    """
    if word_count < MIN_EMBED_WORDS:
        return
    if extractor and extractor not in {"html", "browser", "ocr", "doc", "ingest"}:
        return
    if not markdown:
        return
    payload = {
        "documents": [{
            "id": f"wh-{row_id}",
            "text": markdown[:EMBED_TEXT_CAP],
            "url": url,
            "title": title or "",
            "metadata": {
                "warehouse_id": row_id,
                "extractor": extractor or "unknown",
                "word_count": word_count,
            },
        }],
        "namespace": "warehouse",
    }
    ok = await _try_post_embed(payload)
    if ok:
        log.info("embed_ok id=wh-%d words=%d", row_id, word_count)
        return
    log.warning("embed_failed id=wh-%d — queued for retry", row_id)
    _store_pending_embed(row_id, url, title, markdown[:EMBED_TEXT_CAP],
                        word_count, extractor)


async def _embed_retry_loop() -> None:
    """Background drainer for the embed outbox.

    Wakes every EMBED_RETRY_INTERVAL_SEC, pulls up to EMBED_DRAIN_BATCH
    rows under the attempt ceiling, retries each. Successful → row
    deleted. Failed → attempts++. Rows that hit EMBED_MAX_ATTEMPTS stay
    in the outbox flagged for operator attention (visible via /stats).
    """
    log.info("embed_retry_loop_starting interval=%ds max_attempts=%d batch=%d",
             _EMBED_RETRY_INTERVAL_SEC, _EMBED_MAX_ATTEMPTS, _EMBED_DRAIN_BATCH)
    while True:
        await asyncio.sleep(_EMBED_RETRY_INTERVAL_SEC)
        try:
            with sqlite3.connect(str(_EMBED_OUTBOX_DB)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """SELECT id, row_id, url, title, markdown, word_count, extractor
                       FROM pending_embeds
                       WHERE attempts < ?
                       ORDER BY id LIMIT ?""",
                    (_EMBED_MAX_ATTEMPTS, _EMBED_DRAIN_BATCH),
                ).fetchall()
            if not rows:
                continue
            for r in rows:
                payload = {
                    "documents": [{
                        "id": f"wh-{r['row_id']}",
                        "text": r["markdown"],
                        "url": r["url"],
                        "title": r["title"] or "",
                        "metadata": {
                            "warehouse_id": r["row_id"],
                            "extractor": r["extractor"] or "unknown",
                            "word_count": r["word_count"],
                        },
                    }],
                    "namespace": "warehouse",
                }
                ok = await _try_post_embed(payload)
                with sqlite3.connect(str(_EMBED_OUTBOX_DB)) as conn:
                    if ok:
                        conn.execute("DELETE FROM pending_embeds WHERE id = ?", (r["id"],))
                        log.info("embed_retry_ok outbox_id=%d row_id=%d",
                                 r["id"], r["row_id"])
                    else:
                        conn.execute(
                            "UPDATE pending_embeds SET attempts = attempts + 1, last_attempt = ? WHERE id = ?",
                            (time.time(), r["id"]),
                        )
                    conn.commit()
        except Exception as e:
            log.warning("embed_retry_loop_iter_err err=%s", e)


# ─── Models ───────────────────────────────────────────────
class IngestRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)
    markdown: str = Field(..., min_length=1)
    content: Optional[str] = None
    title: Optional[str] = None
    author: Optional[str] = None
    published: Optional[str] = None
    language: Optional[str] = None
    word_count: int = 0
    source_domain: Optional[str] = None
    tags: list[str] = []
    # Lineage (v2): propagated by crawler/web-api so we know how this row
    # got here. All optional for back-compat.
    seen_in_session: Optional[str] = None
    found_via_query: Optional[str] = None
    extractor: Optional[str] = None  # "html" | "browser" | "ocr" | "ingest" | "doc"
    extraction_confidence: Optional[float] = None
    source_provider: Optional[str] = None  # which search provider surfaced this URL


class IngestResponse(BaseModel):
    id: int
    url: str
    ingested: bool
    cached: bool = False
    # v2 fields — let the caller know what happened.
    action: str = "inserted"  # "inserted" | "alias" | "revision" | "unchanged" | "rejected"
    revision: int = 1
    content_sha256: Optional[str] = None
    superseded_id: Optional[int] = None
    # Populated when action == "rejected" so callers (crawler logs, CLI)
    # can see WHY the warehouse refused to store the row.
    rejected_reason: Optional[str] = None


class ContentItem(BaseModel):
    id: int
    url: str
    title: Optional[str]
    markdown: str
    author: Optional[str]
    published: Optional[str]
    language: Optional[str]
    word_count: int
    source_domain: Optional[str]
    ingested_at: str
    tags: list


class SearchResult(BaseModel):
    id: int
    url: str
    title: Optional[str]
    snippet: str
    source_domain: Optional[str]
    ingested_at: str
    word_count: int = 0


class ListResult(BaseModel):
    id: int
    url: str
    title: Optional[str]
    snippet: str
    source_domain: Optional[str]
    ingested_at: str
    word_count: int = 0
    author: Optional[str] = None
    tags: list[str] = []
    category: Optional[str] = None


class StatsResponse(BaseModel):
    total_entries: int
    total_words: int
    domains: list[dict]
    db_size_mb: float
    # v2 lineage stats
    current_revisions: int = 0
    superseded_revisions: int = 0
    aliases: int = 0
    extractors: dict = {}
    by_provider: dict = {}
    categories: dict = {}
    # Quality gate (process-lifetime counters; reset on restart).
    quality_rejected_total: int = 0
    quality_rejected_by_reason: dict = {}
    # Embed outbox depth: rows that couldn't reach vector-store on their
    # first try and are awaiting the background retry loop. >0 = transient
    # vector outage. Sustained high values mean the retry isn't winning —
    # check vector-store health.
    pending_embeds: int = 0


# ─── Content classification (v2.3) ───────────────────────────────────────
# Cheap rule-based bucket assignment. Inputs: URL, extractor name, source
# domain, content length. Outputs: one of the CATEGORIES below.
#
# Categories are tuned for the polymath archive use case — filters that
# the human-operator actually wants ("show me docs only", "newsfeeds I
# subscribed to", "papers I've ingested").

CATEGORIES = (
    "paper",      # academic — arxiv, doi, pubmed, .edu (with /paper or pdf)
    "manual",     # man pages, RFC, docs/man
    "doc",        # framework/library/lang docs
    "reference",  # encyclopedic (wikipedia, mdn, cppreference, wikibooks)
    "code",       # github/gitlab repos and READMEs
    "qa",         # stackoverflow, stackexchange variants
    "news",       # mainstream news outlets
    "blog",       # personal/small blogs (heuristic)
    "social",     # reddit, twitter/x, hackernews, mastodon, lobsters
    "video",      # youtube, vimeo (via youtube-transcript extractor)
    "feed",       # RSS/Atom feeds we ingested directly
    "other",      # unknown
)

# Stable domain → category map (exact match or suffix).
_NEWS_DOMAINS = {
    "nytimes.com", "wsj.com", "ft.com", "bbc.com", "bbc.co.uk",
    "theguardian.com", "reuters.com", "apnews.com", "bloomberg.com",
    "cnn.com", "washingtonpost.com", "theatlantic.com", "newyorker.com",
    "vox.com", "axios.com", "politico.com", "economist.com",
    "techcrunch.com", "arstechnica.com", "theverge.com", "engadget.com",
    "wired.com", "venturebeat.com", "zdnet.com", "cnet.com",
}
_REFERENCE_HOSTS = (
    "wikipedia.org", "wikibooks.org", "wiktionary.org",
    "mdn.io", "developer.mozilla.org",
    "cppreference.com", "rust-lang.org", "doc.rust-lang.org",
    "wiki.archlinux.org", "wiki.debian.org",
)
_DOC_HOSTS = (
    "docs.python.org", "go.dev", "pkg.go.dev", "nodejs.org",
    "docs.djangoproject.com", "react.dev", "flask.palletsprojects.com",
    "fastapi.tiangolo.com", "docs.sqlalchemy.org", "expressjs.com",
    "docs.docker.com", "kubernetes.io", "docs.nginx.com",
    "postgresql.org", "redis.io",
    "stripe.com", "platform.openai.com",
    "requests.readthedocs.io", "pip.pypa.io",
    "docs.aws.amazon.com", "cloud.google.com",
)
_MANUAL_HOSTS = ("man7.org", "manpages.debian.org", "manpages.ubuntu.com",
                 "manpages.org", "freebsd.org/cgi/man.cgi", "rfc-editor.org")
_QA_HOSTS = ("stackoverflow.com", "stackexchange.com", "askubuntu.com",
             "serverfault.com", "superuser.com")
_SOCIAL_HOSTS = ("reddit.com", "twitter.com", "x.com", "lobste.rs",
                 "news.ycombinator.com", "mastodon.social", "bsky.app")
_VIDEO_HOSTS = ("youtube.com", "youtu.be", "vimeo.com")
_CODE_HOSTS = ("github.com", "gitlab.com", "bitbucket.org", "codeberg.org",
               "sourceforge.net")


def _host_endswith_any(host: str, suffixes: tuple) -> bool:
    h = (host or "").lower().lstrip(".")
    return any(h == s or h.endswith("." + s) or h.endswith(s) for s in suffixes)


def _host_in_set(host: str, names: set) -> bool:
    h = (host or "").lower().lstrip(".")
    if h in names:
        return True
    # strip leading www. / m. for matching
    if h.startswith(("www.", "m.")):
        h2 = h.split(".", 1)[1]
        if h2 in names:
            return True
    return False


def classify(url: str, domain: Optional[str], extractor: Optional[str],
             markdown: str) -> str:
    """Return a category bucket — cheap rule-based, deterministic."""
    host = (domain or "").lower()
    u = (url or "").lower()
    ext = (extractor or "").lower()

    # 1. Extractor signal first (most authoritative)
    if ext == "youtube-transcript" or ext == "youtube-metadata":
        return "video"
    if ext == "arxiv-api" or ext == "pdf" and "arxiv.org" in u:
        return "paper"
    if ext == "hn-algolia":
        return "social"
    if ext == "twitter-syndication":
        return "social"
    if ext == "github-api":
        return "code"
    if ext == "reddit-json":
        return "social"

    # 2. Host-based: most specific to least.
    if _host_endswith_any(host, _MANUAL_HOSTS) or "/man-pages/" in u:
        return "manual"
    if _host_endswith_any(host, _REFERENCE_HOSTS):
        return "reference"
    if _host_endswith_any(host, _DOC_HOSTS) or "/docs/" in u or "/documentation/" in u:
        return "doc"
    if _host_endswith_any(host, _QA_HOSTS):
        return "qa"
    if _host_endswith_any(host, _SOCIAL_HOSTS):
        return "social"
    if _host_endswith_any(host, _VIDEO_HOSTS):
        return "video"
    if _host_endswith_any(host, _CODE_HOSTS):
        return "code"
    if _host_in_set(host, _NEWS_DOMAINS):
        return "news"

    # 3. URL-shape signals.
    if "/blog/" in u or host.startswith("blog."):
        return "blog"
    if host.endswith(".edu") or "/paper" in u or "/pubs/" in u or "/papers/" in u:
        return "paper"

    # 4. RSS/Atom feeds.
    if ext == "feed" or u.endswith(("/rss", "/feed", "/atom.xml", ".rss")):
        return "feed"

    # 5. Light heuristic: small personal-blog-shaped hostnames.
    parts = host.split(".") if host else []
    if 2 <= len(parts) <= 3 and len(parts[0]) <= 15 and parts[-1] in {
        "com", "io", "net", "blog", "me", "dev", "ai", "co"
    }:
        # If markdown looks article-length (not a marketing page), call it a blog.
        wc = len((markdown or "").split())
        if 200 < wc < 30000:
            return "blog"

    return "other"


# ─── Endpoints ────────────────────────────────────────────


@app.post("/ingest", response_model=IngestResponse)
async def ingest(req: IngestRequest):
    """Ingest crawled content with versioning + dedup + lineage.

    Decision tree (in order):
      1. content_sha256 already exists somewhere:
           - same URL too → unchanged (bump last_seen_at), action="unchanged"
           - different URL → record alias, action="alias"
      2. url_hash exists but content_sha256 differs → new revision:
           mark old as is_current=0; INSERT new row with revision++; action="revision"
      3. brand-new URL + content → straight INSERT, revision=1, action="inserted"
    """
    url_hash = hashlib.sha256(req.url.encode()).hexdigest()
    domain = req.source_domain or _extract_domain(req.url)
    md = req.markdown[:MAX_CONTENT_LENGTH]
    content = (req.content or "")[:MAX_CONTENT_LENGTH]
    body_for_hash = (content or md).encode("utf-8", errors="replace")
    content_sha = hashlib.sha256(body_for_hash).hexdigest()
    now = time.time()

    with write_txn() as conn:
        # Step 1: content already known under SOME URL?
        existing_by_content = conn.execute(
            "SELECT id, url, url_hash FROM content WHERE content_sha256 = ? AND is_current = 1 LIMIT 1",
            (content_sha,),
        ).fetchone()
        if existing_by_content:
            eid, existing_url, existing_url_hash = existing_by_content
            conn.execute("UPDATE content SET last_seen_at = ? WHERE id = ?", (now, eid))
            if existing_url_hash == url_hash:
                log.info("ingest_unchanged url=%s id=%s sha=%s", req.url[:100], eid, content_sha[:12])
                return IngestResponse(
                    id=eid, url=req.url, ingested=True, cached=True,
                    action="unchanged", content_sha256=content_sha,
                )
            # Same content, different URL → alias.
            # Store the decoded form so it matches what FastAPI hands back
            # to /content/by-url (which auto-decodes query params).
            from urllib.parse import unquote as _unquote
            alias_url = _unquote(req.url)
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO content_alias (content_id, url, first_seen) VALUES (?, ?, ?)",
                    (eid, alias_url, now),
                )
                # Also preserve the as-presented form so lookups using the
                # raw %-encoded URL still resolve.
                if alias_url != req.url:
                    conn.execute(
                        "INSERT OR IGNORE INTO content_alias (content_id, url, first_seen) VALUES (?, ?, ?)",
                        (eid, req.url, now),
                    )
            except Exception:
                pass
            log.info("ingest_alias url=%s id=%s sha=%s canonical=%s",
                     req.url[:100], eid, content_sha[:12], existing_url[:100])
            return IngestResponse(
                id=eid, url=req.url, ingested=True, cached=True,
                action="alias", content_sha256=content_sha,
            )

        # Step 2: same URL, different content → new revision
        prior = conn.execute(
            "SELECT id, revision FROM content WHERE url_hash = ? AND is_current = 1 LIMIT 1",
            (url_hash,),
        ).fetchone()

        # Classify once per ingest so revisions get the same bucket as the
        # original (and we don't re-run the classifier on every revision read).
        category = classify(req.url, domain, req.extractor, md)

        # Quality gate. Applied for brand-new rows AND new revisions (we
        # don't want the warehouse to *replace* a good row with a degraded
        # re-crawl). "alias"/"unchanged" paths already returned above —
        # those reuse existing rows, no new storage cost.
        reject_reason = _quality_gate_decide(
            word_count=req.word_count or len(md.split()),
            extraction_confidence=req.extraction_confidence,
            category=category,
            markdown=md,
        )
        if reject_reason:
            _record_rejection(reject_reason)
            log.info("ingest_rejected url=%s reason=%s words=%d conf=%s cat=%s",
                     req.url[:100], reject_reason, req.word_count,
                     req.extraction_confidence, category)
            return IngestResponse(
                id=0, url=req.url, ingested=False, cached=False,
                action="rejected", rejected_reason=reject_reason,
                content_sha256=content_sha,
            )

        if prior:
            prior_id, prior_rev = prior
            conn.execute("UPDATE content SET is_current = 0, status = 'superseded' WHERE id = ?", (prior_id,))
            cursor = conn.execute(
                """
                INSERT INTO content (
                    url_hash, url, title, markdown, content, author, published, language,
                    word_count, source_domain, ingested_at, last_seen_at, tags,
                    content_sha256, revision, is_current, supersedes,
                    seen_in_session, found_via_query, extractor, extraction_confidence,
                    source_provider, status, category
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, 'active', ?)
                """,
                (
                    url_hash, req.url, req.title, md, content, req.author, req.published, req.language,
                    req.word_count, domain, now, now, json.dumps(req.tags),
                    content_sha, prior_rev + 1, prior_id,
                    req.seen_in_session, req.found_via_query, req.extractor,
                    req.extraction_confidence, req.source_provider, category,
                ),
            )
            new_id = cursor.lastrowid
            log.info("ingest_revision url=%s id=%s rev=%d supersedes=%d sha=%s",
                     req.url[:100], new_id, prior_rev + 1, prior_id, content_sha[:12])
            # Fire-and-forget embed of the new revision.
            asyncio.create_task(_embed_to_vector_store(
                new_id, req.url, req.title, md, req.word_count, req.extractor
            ))
            return IngestResponse(
                id=new_id, url=req.url, ingested=True, cached=False,
                action="revision", revision=prior_rev + 1,
                content_sha256=content_sha, superseded_id=prior_id,
            )

        # Step 3: brand new
        cursor = conn.execute(
            """
            INSERT INTO content (
                url_hash, url, title, markdown, content, author, published, language,
                word_count, source_domain, ingested_at, last_seen_at, tags,
                content_sha256, revision, is_current, supersedes,
                seen_in_session, found_via_query, extractor, extraction_confidence,
                source_provider, status, category
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, 1, NULL, ?, ?, ?, ?, ?, 'active', ?)
            """,
            (
                url_hash, req.url, req.title, md, content, req.author, req.published, req.language,
                req.word_count, domain, now, now, json.dumps(req.tags),
                content_sha,
                req.seen_in_session, req.found_via_query, req.extractor,
                req.extraction_confidence, req.source_provider, category,
            ),
        )
        row_id = cursor.lastrowid
        log.info("ingest_new url=%s id=%s words=%d sha=%s",
                 req.url[:100], row_id, req.word_count, content_sha[:12])
        asyncio.create_task(_embed_to_vector_store(
            row_id, req.url, req.title, md, req.word_count, req.extractor
        ))
        return IngestResponse(
            id=row_id, url=req.url, ingested=True, action="inserted",
            revision=1, content_sha256=content_sha,
        )


# NOTE: route order matters with FastAPI/Starlette — the literal-path route
# /content/by-url MUST be declared before the parameterized /content/{item_id}
# route, otherwise "by-url" gets parsed as a (failing) int.
@app.get("/content/by-url", response_model=ContentItem)
async def get_content_by_url(url: str = Query(..., min_length=1)):
    """Look up the current revision of a row by exact URL (cheap, indexed via
    url_hash). Tries url_hash first; on miss, looks for a content_alias that
    maps to a stored row; finally falls back to a LIKE prefix scan.

    Used by clients that have a URL in hand (e.g., Agent tab's `v` shortcut)
    and want the warehouse body without a brittle FTS5 search.
    """
    url_hash = hashlib.sha256(url.encode()).hexdigest()
    conn = _read_conn()
    try:
        row = conn.execute(
            "SELECT * FROM content WHERE url_hash = ? AND is_current = 1 LIMIT 1",
            (url_hash,),
        ).fetchone()

        # Alias lookup: maybe this exact URL is an alias for another row's
        # canonical URL (mirror/share-link). Try both the decoded form (what
        # FastAPI handed us) and a re-encoded form, since older alias rows
        # may have been stored URL-encoded.
        if not row:
            from urllib.parse import quote as _quote, unquote as _unquote
            candidates = [url, _unquote(url), _quote(url, safe=":/?&=+#")]
            alias_row = None
            for cand in candidates:
                alias_row = conn.execute(
                    "SELECT content_id FROM content_alias WHERE url = ? LIMIT 1",
                    (cand,),
                ).fetchone()
                if alias_row:
                    break
            if alias_row:
                row = conn.execute(
                    "SELECT * FROM content WHERE id = ?",
                    (alias_row["content_id"],),
                ).fetchone()

        # Last-resort: exact-URL scan (handles URLs with trailing-slash
        # variations or normalized vs raw, since url_hash compares bytes).
        if not row:
            row = conn.execute(
                "SELECT * FROM content WHERE url = ? AND is_current = 1 LIMIT 1",
                (url,),
            ).fetchone()

        if not row:
            raise HTTPException(status_code=404,
                                detail=f"No warehouse row for URL: {url}")
        return ContentItem(
            id=row["id"],
            url=row["url"],
            title=row["title"],
            markdown=row["markdown"],
            author=row["author"],
            published=row["published"],
            language=row["language"],
            word_count=row["word_count"],
            source_domain=row["source_domain"],
            ingested_at=datetime.fromtimestamp(
                row["ingested_at"], tz=timezone.utc
            ).isoformat(),
            tags=json.loads(row["tags"] or "[]"),
        )
    finally:
        conn.close()


@app.get("/content/{item_id}", response_model=ContentItem)
async def get_content(item_id: int):
    """Retrieve a single content item by ID."""
    conn = _read_conn()
    try:
        row = conn.execute("SELECT * FROM content WHERE id = ?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Content not found")
        return ContentItem(
            id=row["id"],
            url=row["url"],
            title=row["title"],
            markdown=row["markdown"],
            author=row["author"],
            published=row["published"],
            language=row["language"],
            word_count=row["word_count"],
            source_domain=row["source_domain"],
            ingested_at=datetime.fromtimestamp(
                row["ingested_at"], tz=timezone.utc
            ).isoformat(),
            tags=json.loads(row["tags"]),
        )
    finally:
        conn.close()


@app.get("/content/{item_id}/revisions")
async def get_revisions(item_id: int):
    """Return all revisions sharing this row's url_hash, newest first.
    Each revision row carries its full lineage so the caller can build a timeline."""
    conn = _read_conn()
    try:
        seed = conn.execute("SELECT url_hash, url FROM content WHERE id = ?", (item_id,)).fetchone()
        if not seed:
            raise HTTPException(status_code=404, detail="Content not found")
        rows = conn.execute(
            """
            SELECT id, revision, is_current, supersedes, content_sha256, word_count,
                   ingested_at, last_seen_at, extractor, extraction_confidence,
                   source_provider, seen_in_session, found_via_query, status
            FROM content
            WHERE url_hash = ?
            ORDER BY revision DESC
            """,
            (seed["url_hash"],),
        ).fetchall()
        return {
            "url": seed["url"],
            "url_hash": seed["url_hash"],
            "revisions": [
                {
                    "id": r["id"],
                    "revision": r["revision"],
                    "is_current": bool(r["is_current"]),
                    "supersedes": r["supersedes"],
                    "content_sha256": r["content_sha256"],
                    "word_count": r["word_count"],
                    "ingested_at": datetime.fromtimestamp(r["ingested_at"], tz=timezone.utc).isoformat() if r["ingested_at"] else None,
                    "last_seen_at": datetime.fromtimestamp(r["last_seen_at"], tz=timezone.utc).isoformat() if r["last_seen_at"] else None,
                    "extractor": r["extractor"],
                    "extraction_confidence": r["extraction_confidence"],
                    "source_provider": r["source_provider"],
                    "seen_in_session": r["seen_in_session"],
                    "found_via_query": r["found_via_query"],
                    "status": r["status"],
                }
                for r in rows
            ],
        }
    finally:
        conn.close()


@app.get("/content/{item_id}/aliases")
async def get_aliases(item_id: int):
    """Return all URLs that resolved to this row's content (mirrors, share links)."""
    conn = _read_conn()
    try:
        seed = conn.execute("SELECT id, url FROM content WHERE id = ?", (item_id,)).fetchone()
        if not seed:
            raise HTTPException(status_code=404, detail="Content not found")
        rows = conn.execute(
            "SELECT url, first_seen FROM content_alias WHERE content_id = ? ORDER BY first_seen ASC",
            (item_id,),
        ).fetchall()
        return {
            "canonical_url": seed["url"],
            "aliases": [
                {
                    "url": r["url"],
                    "first_seen": datetime.fromtimestamp(r["first_seen"], tz=timezone.utc).isoformat(),
                }
                for r in rows
            ],
        }
    finally:
        conn.close()


@app.get("/search", response_model=list[SearchResult])
async def search(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    domain: Optional[str] = Query(None, description="Filter by domain"),
    include_history: bool = Query(False, description="Include superseded revisions"),
):
    """Full-text search across stored content. Defaults to current revisions only.

    The query is tokenized to alphanumeric chunks and joined with the implicit
    AND operator. That gives sane multi-word behavior (`raft consensus log` =
    docs containing all 3 tokens anywhere) without exposing FTS5 phrase quoting
    or reserved characters to callers.
    """
    conn = _read_conn()
    try:
        # FTS5 sanitization: strip everything but alphanumerics, lowercase,
        # join with spaces. FTS5's default operator is AND so multi-word
        # queries become an implicit conjunction.
        import re as _re
        tokens = _re.findall(r"[a-zA-Z0-9]+", q.lower())
        if not tokens:
            return []
        query = " ".join(tokens)

        sql_params: list = [query]
        where_clauses: list[str] = []
        if domain:
            where_clauses.append("c.source_domain = ?")
            sql_params.append(domain)
        if not include_history:
            where_clauses.append("c.is_current = 1")
        # Never surface deleted rows
        where_clauses.append("c.status != 'deleted'")

        where = ("AND " + " AND ".join(where_clauses)) if where_clauses else ""
        sql_params.append(limit)

        rows = conn.execute(
            f"""
            SELECT c.id, c.url, c.title, c.source_domain, c.ingested_at, c.word_count,
                   snippet(content_fts, 1, '<b>', '</b>', '...', 40) as snippet
            FROM content_fts
            JOIN content c ON content_fts.rowid = c.id
            WHERE content_fts MATCH ? {where}
            ORDER BY rank
            LIMIT ?
        """,
            sql_params,
        ).fetchall()

        return [
            SearchResult(
                id=row["id"],
                url=row["url"],
                title=row["title"],
                snippet=row["snippet"],
                source_domain=row["source_domain"],
                word_count=row["word_count"],
                ingested_at=datetime.fromtimestamp(
                    row["ingested_at"], tz=timezone.utc
                ).isoformat(),
            )
            for row in rows
        ]
    finally:
        conn.close()


@app.get("/list", response_model=list[ListResult])
async def list_entries(
    sort: str = Query("ingested_at", description="Sort field: ingested_at, word_count, title, domain, last_seen_at"),
    order: str = Query("desc", description="Sort order: asc or desc"),
    domain: Optional[str] = Query(None, description="Filter by domain"),
    category: Optional[str] = Query(None, description="Filter by category (paper|manual|doc|reference|code|qa|news|blog|social|video|feed|other)"),
    min_words: Optional[int] = Query(None, description="Minimum word count"),
    max_words: Optional[int] = Query(None, description="Maximum word count"),
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
    include_history: bool = Query(False, description="Include superseded revisions"),
):
    """Paginated list with sort and filter — newest first by default.

    Defaults to current revisions only (is_current=1). Pass include_history=1
    to include superseded revisions.
    """
    allowed_sorts = {"ingested_at", "word_count", "title", "source_domain", "last_seen_at"}
    if sort not in allowed_sorts:
        sort = "ingested_at"
    direction = "DESC" if order == "desc" else "ASC"

    conn = _read_conn()
    try:
        where = []
        params = []
        if domain:
            where.append("source_domain = ?")
            params.append(domain)
        if category:
            where.append("category = ?")
            params.append(category)
        if min_words is not None:
            where.append("word_count >= ?")
            params.append(min_words)
        if max_words is not None:
            where.append("word_count <= ?")
            params.append(max_words)
        # v2: current revisions, non-deleted only (unless caller opts in)
        if not include_history:
            where.append("is_current = 1")
        where.append("status != 'deleted'")

        where_clause = f"WHERE {' AND '.join(where)}" if where else ""
        query = f"""
            SELECT id, url, title, source_domain, word_count, author, tags, category,
                   ingested_at, substr(markdown, 1, 240) AS lead
            FROM content
            {where_clause}
            ORDER BY {sort} {direction}
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()

        # Snippet is the lead 200 chars of the actual stored markdown so
        # operators can audit data-quality at a glance (nav-junk vs clean
        # article body). Falls back to the title only if the body is empty.
        return [
            {
                "id": row["id"],
                "url": row["url"],
                "title": row["title"],
                "snippet": ((row["lead"] or "").strip() or (row["title"] or ""))[:240],
                "source_domain": row["source_domain"],
                "ingested_at": datetime.fromtimestamp(
                    row["ingested_at"], tz=timezone.utc
                ).isoformat(),
                "word_count": row["word_count"],
                "author": row["author"],
                "tags": json.loads(row["tags"]) if row["tags"] else [],
                "category": row["category"] if "category" in row.keys() else None,
            }
            for row in rows
        ]
    finally:
        conn.close()


@app.post("/admin/backfill-categories")
async def backfill_categories(limit: int = Query(2000, ge=1, le=20000)):
    """Walk rows whose category is NULL and assign one. Idempotent — already-
    classified rows are skipped. Returns the per-bucket counts after the pass.
    """
    classified = 0
    by_cat: dict[str, int] = {}
    with write_txn() as conn:
        # write_txn returns the single shared write connection; rows come
        # back as tuples (no row_factory). Index positionally.
        rows = conn.execute(
            "SELECT id, url, source_domain, extractor, markdown FROM content "
            "WHERE category IS NULL LIMIT ?",
            (limit,),
        ).fetchall()
        for rid, url, src_domain, extractor, markdown in rows:
            cat = classify(url, src_domain, extractor, markdown or "")
            conn.execute(
                "UPDATE content SET category = ? WHERE id = ?",
                (cat, rid),
            )
            classified += 1
            by_cat[cat] = by_cat.get(cat, 0) + 1
    log.info("backfill_categories classified=%d buckets=%s", classified, by_cat)
    return {"classified": classified, "buckets": by_cat}


@app.get("/stats", response_model=StatsResponse)
async def stats():
    """Warehouse statistics — v2 includes lineage breakdown."""
    conn = _read_conn()
    try:
        total = conn.execute("SELECT COUNT(*), COALESCE(SUM(word_count), 0) FROM content").fetchone()
        domains = conn.execute(
            "SELECT source_domain, COUNT(*) as cnt FROM content WHERE is_current=1 GROUP BY source_domain ORDER BY cnt DESC LIMIT 20"
        ).fetchall()
        current = conn.execute("SELECT COUNT(*) FROM content WHERE is_current = 1").fetchone()[0]
        superseded = conn.execute("SELECT COUNT(*) FROM content WHERE is_current = 0").fetchone()[0]
        aliases = conn.execute("SELECT COUNT(*) FROM content_alias").fetchone()[0]
        extractors = {
            r[0] or "unknown": r[1]
            for r in conn.execute("SELECT COALESCE(extractor, 'unknown'), COUNT(*) FROM content WHERE is_current=1 GROUP BY extractor").fetchall()
        }
        by_provider = {
            r[0] or "unknown": r[1]
            for r in conn.execute("SELECT COALESCE(source_provider, 'unknown'), COUNT(*) FROM content WHERE is_current=1 GROUP BY source_provider ORDER BY COUNT(*) DESC LIMIT 15").fetchall()
        }
        categories = {
            r[0] or "unknown": r[1]
            for r in conn.execute("SELECT COALESCE(category, 'unknown'), COUNT(*) FROM content WHERE is_current=1 GROUP BY category ORDER BY COUNT(*) DESC").fetchall()
        }
        db_size = DB_PATH.stat().st_size / (1024 * 1024) if DB_PATH.exists() else 0
    finally:
        conn.close()

    return StatsResponse(
        total_entries=total[0],
        total_words=total[1],
        domains=[{"domain": d, "count": c} for d, c in domains],
        db_size_mb=round(db_size, 2),
        current_revisions=current,
        superseded_revisions=superseded,
        aliases=aliases,
        extractors=extractors,
        by_provider=by_provider,
        categories=categories,
        quality_rejected_total=_quality_rejected_total,
        quality_rejected_by_reason=dict(_quality_rejected_by_reason),
        pending_embeds=_pending_embeds_count(),
    )


async def _vector_delete(row_id: int) -> None:
    """Best-effort vector-store delete for warehouse row {row_id}.

    Embeddings are keyed `warehouse:wh-{row_id}` — the warehouse posts
    `id="wh-{row_id}"` but with `namespace="warehouse"`, and vector-store
    rewrites the stored id to `{namespace}:{id}`. The delete has to use
    the rewritten form or it silently no-ops.

    If the vector-store is down we log and move on — the SQLite delete
    already committed.
    """
    full_id = f"warehouse:wh-{row_id}"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.request(
                "DELETE",
                f"{VECTOR_STORE_URL}/documents",
                json={"ids": [full_id]},
            )
            if r.status_code not in (200, 204):
                log.warning("vector_delete_unexpected id=%s status=%s body=%s",
                            full_id, r.status_code, r.text[:120])
            else:
                log.info("vector_delete_ok id=%s", full_id)
    except Exception as e:
        log.warning("vector_delete_failed id=%s err=%s", full_id, e)


@app.delete("/content/{item_id}")
async def delete_content(item_id: int):
    """Delete a content item from both SQLite AND the vector store.

    Without the vector-store delete the embedding would dangle and the
    deleted row keeps surfacing in /api/search/hybrid via vec_rank.
    """
    with write_txn() as conn:
        conn.execute("DELETE FROM content WHERE id = ?", (item_id,))
    # Fire-and-forget — keeps the HTTP response snappy. The vector-store
    # delete is best-effort; if it fails the next vector_audit job will
    # catch dangling embeddings (or operators can call /admin/backfill-
    # embeddings to reconcile).
    asyncio.create_task(_vector_delete(item_id))
    return {"deleted": item_id}


@app.post("/admin/backfill-extractors")
async def backfill_extractors(
    dry_run: bool = Query(False),
    embed: bool = Query(True, description="Also fire embed for body-class rows"),
):
    """Repair legacy rows that have extractor=NULL.

    Inference rules (in order):
      1. tags include "body" → extractor inferred from URL extension
         (pdf/docx/epub/md/txt) or defaults to "html"
      2. tags include "snippet" → extractor="snippet" (don't embed)
      3. tags include "search_seed" → extractor="snippet"
      4. word_count >= MIN_EMBED_WORDS → likely a crawled body → "html-legacy"
      5. else → "snippet"

    Embeds eligible rows so hybrid retrieval covers them too.
    """
    conn = _read_conn()
    try:
        rows = conn.execute("""
            SELECT id, url, title, markdown, word_count, tags
            FROM content
            WHERE (extractor IS NULL OR extractor = '' OR extractor = 'unknown')
              AND is_current = 1 AND status != 'deleted'
            ORDER BY id ASC
        """).fetchall()
    finally:
        conn.close()

    plan = []
    for r in rows:
        tags = []
        try:
            tags = json.loads(r["tags"] or "[]")
        except Exception:
            pass
        ext = None
        is_body = "body" in tags
        is_snippet = "snippet" in tags or "search_seed" in tags
        url_lower = (r["url"] or "").lower().split("?")[0]

        if is_body:
            for sfx, name in [(".pdf", "pdf"), (".docx", "docx"), (".doc", "docx"),
                              (".epub", "epub"), (".md", "markdown"),
                              (".markdown", "markdown"), (".txt", "text")]:
                if url_lower.endswith(sfx):
                    ext = name
                    break
            if not ext:
                ext = "html-legacy"
        elif is_snippet:
            ext = "snippet"
        elif r["word_count"] >= MIN_EMBED_WORDS:
            ext = "html-legacy"
        else:
            ext = "snippet"

        will_embed = embed and ext in {"html-legacy", "html", "browser", "ocr",
                                        "pdf", "docx", "epub", "markdown", "text"} \
                      and r["word_count"] >= MIN_EMBED_WORDS and r["markdown"]
        plan.append((r["id"], r["url"], r["title"], r["markdown"], r["word_count"], ext, will_embed))

    if dry_run:
        by_ext: dict[str, int] = {}
        will_embed_count = 0
        for _, _, _, _, _, ext, we in plan:
            by_ext[ext] = by_ext.get(ext, 0) + 1
            if we:
                will_embed_count += 1
        return {"dry_run": True, "total": len(plan), "by_extractor": by_ext, "will_embed": will_embed_count}

    updated = 0
    embedded = 0
    failed_embed = 0
    with write_txn() as conn:
        for rid, url, title, md, wc, ext, will_embed in plan:
            conn.execute("UPDATE content SET extractor = ? WHERE id = ?", (ext, rid))
            updated += 1

    # Fire embeds OUTSIDE the write transaction (they go to a different service).
    if embed:
        for rid, url, title, md, wc, ext, will_embed in plan:
            if not will_embed:
                continue
            try:
                if _vec_client is None:
                    failed_embed += 1
                    continue
                payload = {
                    "documents": [{
                        "id": f"wh-{rid}",
                        "text": (md or "")[:EMBED_TEXT_CAP],
                        "url": url,
                        "title": title or "",
                        "metadata": {
                            "warehouse_id": rid,
                            "extractor": ext,
                            "word_count": wc,
                            "backfilled": True,
                        },
                    }],
                    "namespace": "warehouse",
                }
                r = await _vec_client.post(f"{VECTOR_STORE_URL}/embed", json=payload)
                if r.status_code == 200:
                    embedded += 1
                else:
                    failed_embed += 1
                    log.warning("backfill_embed_fail id=%d status=%d", rid, r.status_code)
            except Exception as e:
                failed_embed += 1
                log.warning("backfill_embed_err id=%d err=%s", rid, e)

    log.info("backfill_extractors updated=%d embedded=%d failed_embed=%d", updated, embedded, failed_embed)
    return {"updated": updated, "embedded": embedded, "failed_embed": failed_embed, "total_eligible": len(plan)}


@app.post("/admin/backfill-embeddings")
async def backfill_embeddings(
    limit: int = Query(0, ge=0, description="0 = all"),
    batch_size: int = Query(20, ge=1, le=100),
    dry_run: bool = Query(False),
):
    """Walk current revisions and push every body-class row to vector-store.

    Idempotent: vector-store upserts by id (`wh-{row_id}`), so re-running just
    refreshes the embeddings. Use `dry_run=1` to count without sending.
    """
    conn = _read_conn()
    try:
        sql = """
            SELECT id, url, title, markdown, word_count, extractor
            FROM content
            WHERE is_current = 1 AND status != 'deleted'
              AND markdown IS NOT NULL AND length(markdown) > 200
              AND word_count >= ?
            ORDER BY id ASC
        """
        params = [MIN_EMBED_WORDS]
        if limit > 0:
            sql += " LIMIT ?"
            params.append(limit)
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    if dry_run:
        return {"would_embed": len(rows), "dry_run": True}

    # Batch documents to vector-store /embed.
    sent = 0
    failed = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        docs = []
        for r in batch:
            if not r["markdown"]:
                continue
            docs.append({
                "id": f"wh-{r['id']}",
                "text": r["markdown"][:EMBED_TEXT_CAP],
                "url": r["url"],
                "title": r["title"] or "",
                "metadata": {
                    "warehouse_id": r["id"],
                    "extractor": r["extractor"] or "unknown",
                    "word_count": r["word_count"],
                },
            })
        if not docs:
            continue
        try:
            r = await _vec_client.post(
                f"{VECTOR_STORE_URL}/embed",
                json={"documents": docs, "namespace": "warehouse"},
            )
            if r.status_code == 200:
                sent += len(docs)
            else:
                failed += len(docs)
                log.warning("backfill_batch_fail status=%d body=%s", r.status_code, r.text[:200])
        except Exception as e:
            failed += len(docs)
            log.warning("backfill_batch_err: %s", e)
    return {"embedded": sent, "failed": failed, "total_eligible": len(rows)}


@app.get("/health")
async def health():
    conn = _read_conn()
    try:
        total = conn.execute("SELECT COUNT(*) FROM content").fetchone()[0]
    finally:
        conn.close()
    return {"status": "healthy", "total_entries": total, "version": "2.0.0"}


@app.get("/")
async def root():
    return {
        "service": "knowledge-warehouse",
        "version": "1.0.0",
        "endpoints": {
            "POST /ingest": "Ingest crawled content",
            "GET /search?q=...": "Full-text search",
            "GET /content/{id}": "Get by ID",
            "DELETE /content/{id}": "Delete by ID",
            "GET /stats": "Warehouse statistics",
            "GET /health": "Health check",
        },
    }


def _extract_domain(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).netloc or "unknown"


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8009)
