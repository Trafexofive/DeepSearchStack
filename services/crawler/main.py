"""Crawler Service v2 — cached web scraping with content persistence.

Pipeline: URL → cache check → crawl → extract → strip boilerplate → store → return
Cache: SQLite, TTL-based per domain.
Storage: optional knowledge-warehouse forwarding.
"""
import asyncio
import hashlib
import json
import logging
import os
import sqlite3
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, Any, List

from crawl4ai import AsyncWebCrawler, CacheMode
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

# ── Boilerplate stripping (DRY: single source of truth in libs/common/text.py) ─────────

from libs.common.text import strip_boilerplate as _strip_boilerplate_unwrapped
from libs.common.text import clean_markdown as _clean_markdown
from libs.common.text import extract_article as _extract_article
import re as _re

def _strip_boilerplate(markdown: str) -> str:
    """Crawler wrapper around the shared strip_boilerplate + clean_markdown.
    Boilerplate-strip first (nav chrome / sections), then universal cleanup
    (image stubs, empty links, paragraph dedup). Falls back to the input if
    everything got stripped.
    """
    if not markdown:
        return markdown
    result = _strip_boilerplate_unwrapped(markdown)
    result = _clean_markdown(result, dedupe_paragraphs=True)
    return result if result.strip() else markdown


# ─── Config ───────────────────────────────────────────────
CACHE_DIR = Path(os.environ.get("CRAWLER_CACHE_DIR", "/app/cache"))
CACHE_DB = CACHE_DIR / "cache.db"
DEFAULT_TTL_SECONDS = int(os.environ.get("CRAWLER_CACHE_TTL", "86400"))  # 24h
CRAWL_CONCURRENCY = int(os.environ.get("CRAWLER_CONCURRENCY", "10"))  # concurrent crawls
WAREHOUSE_URL = os.environ.get("KNOWLEDGE_WAREHOUSE_URL", "http://knowledge-warehouse:8009")
FORWARD_TO_WAREHOUSE = os.environ.get("FORWARD_TO_WAREHOUSE", "false").lower() == "true"
DOMAIN_STRATEGY_ENABLED = os.environ.get("DOMAIN_STRATEGY_ENABLED", "true").lower() == "true"
# How many consecutive failures of a method before we skip it for that domain
DOMAIN_STRATEGY_FAIL_THRESHOLD = int(os.environ.get("DOMAIN_STRATEGY_FAIL_THRESHOLD", "3"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [crawler] %(message)s",
)
log = logging.getLogger("crawler")

app = FastAPI(title="DeepSearch Crawler v2", version="2.0.0")

# ─── Cache ────────────────────────────────────────────────
def _connect_db(path: Path):
    """Open a SQLite connection with WAL + safe defaults. Used for both cache.db and pending_forwards.db."""
    conn = sqlite3.connect(str(path), timeout=5, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def _init_cache():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with _connect_db(CACHE_DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS cache (
                url_hash TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                content TEXT,
                markdown TEXT,
                title TEXT,
                author TEXT,
                published TEXT,
                language TEXT,
                word_count INTEGER DEFAULT 0,
                success INTEGER DEFAULT 1,
                error_type TEXT,
                error_message TEXT,
                crawled_at REAL NOT NULL,
                headers_json TEXT,
                source_domain TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_domain ON cache(source_domain)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cache_crawled ON cache(crawled_at)")
        conn.commit()

_init_cache()

_cache_sem = asyncio.Semaphore(1)  # SQLite concurrency guard

def _cache_key(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()

# Cache table column order. Static — define once.
# MUST match the schema in _init_cache().
_CACHE_COLUMNS = [
    "url_hash", "url", "content", "markdown", "title", "author", "published",
    "language", "word_count", "success", "error_type", "error_message",
    "crawled_at", "headers_json", "source_domain",
]


def _cache_get(url: str, ttl: int = DEFAULT_TTL_SECONDS) -> Optional[dict]:
    key = _cache_key(url)
    with _connect_db(CACHE_DB) as conn:
        row = conn.execute(
            "SELECT * FROM cache WHERE url_hash = ? AND crawled_at > ?",
            (key, time.time() - ttl),
        ).fetchone()
    # BUGFIX (was): cols query was outside the `with` block AND used `d[0]`
    # (the column cid / integer index) instead of `d[1]` (the column name).
    # Result: the dict had integer keys, so `cached.get("markdown")` always
    # returned None, the "markdown non-empty" check failed, and every
    # re-crawl was treated as a miss. Now we use the static _CACHE_COLUMNS.
    if row:
        return dict(zip(_CACHE_COLUMNS, row))
    return None

def _cache_put(url: str, data: dict):
    key = _cache_key(url)
    domain = data.get("source_domain", "")
    with _connect_db(CACHE_DB) as conn:
        conn.execute("""
            INSERT OR REPLACE INTO cache
            (url_hash, url, content, markdown, title, author, published,
             language, word_count, success, error_type, error_message,
             crawled_at, headers_json, source_domain)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            key, url,
            data.get("content"), data.get("markdown"), data.get("title"),
            data.get("author"), data.get("published"), data.get("language"),
            data.get("word_count", 0), data.get("success", 1),
            data.get("error_type"), data.get("error_message"),
            data.get("crawled_at", time.time()),
            json.dumps(data.get("headers", {})),
            domain,
        ))
        conn.commit()

def _cache_stats() -> dict:
    with _connect_db(CACHE_DB) as conn:
        total = conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
        fresh = conn.execute(
            "SELECT COUNT(*) FROM cache WHERE crawled_at > ?",
            (time.time() - DEFAULT_TTL_SECONDS,),
        ).fetchone()[0]
        domains = conn.execute(
            "SELECT source_domain, COUNT(*) as cnt FROM cache GROUP BY source_domain ORDER BY cnt DESC LIMIT 20"
        ).fetchall()
    return {"total_entries": total, "fresh_entries": fresh, "domains": [{"domain": d, "count": c} for d, c in domains]}


# ─── Warehouse Forwarding (reliable delivery) ──────────────────────────────

_PENDING_FORWARD_DB = CACHE_DIR / "pending_forwards.db"

def _init_pending_forwards():
    with _connect_db(_PENDING_FORWARD_DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS pending_forwards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT NOT NULL,
                markdown TEXT NOT NULL,
                content TEXT DEFAULT '',
                title TEXT DEFAULT '',
                source_domain TEXT DEFAULT '',
                attempts INTEGER DEFAULT 0,
                last_attempt REAL DEFAULT 0,
                created_at REAL NOT NULL
            )
        """)
        conn.commit()

_init_pending_forwards()


# ─── Per-domain strategy memory ────────────────────────────────────────
# Track which extraction method ("fast", "browser", "ocr", or any
# domain-shortcut like "reddit-json") wins for each domain. After
# DOMAIN_STRATEGY_FAIL_THRESHOLD consecutive fails of a method on a domain,
# we skip that method's attempt on the next request and jump to whatever
# previously succeeded. Cuts wasted ladder time on bot-protected domains.

_DOMAIN_STRATEGY_DB = CACHE_DIR / "domain_strategies.db"


def _init_domain_strategies():
    with _connect_db(_DOMAIN_STRATEGY_DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS domain_strategy (
                domain TEXT NOT NULL,
                method TEXT NOT NULL,
                ok_count INTEGER NOT NULL DEFAULT 0,
                fail_count INTEGER NOT NULL DEFAULT 0,
                last_success REAL,
                last_attempt REAL,
                PRIMARY KEY (domain, method)
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_dom_strat_dom ON domain_strategy(domain)"
        )
        conn.commit()


_init_domain_strategies()


def _record_strategy(domain: str, method: str, success: bool) -> None:
    if not DOMAIN_STRATEGY_ENABLED or not domain or not method:
        return
    try:
        with _connect_db(_DOMAIN_STRATEGY_DB) as conn:
            now = time.time()
            row = conn.execute(
                "SELECT ok_count, fail_count FROM domain_strategy "
                "WHERE domain=? AND method=?",
                (domain, method),
            ).fetchone()
            if row:
                ok_c, fail_c = row
                if success:
                    ok_c += 1
                    # success resets the consecutive-fail counter for this method
                    fail_c = 0
                else:
                    fail_c += 1
                conn.execute(
                    "UPDATE domain_strategy SET ok_count=?, fail_count=?, "
                    "last_attempt=?, last_success=? "
                    "WHERE domain=? AND method=?",
                    (ok_c, fail_c, now, now if success else None,
                     domain, method),
                )
            else:
                conn.execute(
                    "INSERT INTO domain_strategy "
                    "(domain, method, ok_count, fail_count, last_attempt, last_success) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (domain, method,
                     1 if success else 0,
                     0 if success else 1,
                     now, now if success else None),
                )
            conn.commit()
    except Exception as e:
        log.warning("strategy_record_failed domain=%s method=%s err=%s",
                    domain, method, e)


def _get_domain_strategy(domain: str) -> dict:
    """Return per-method counts for a domain. Empty dict if unknown."""
    if not DOMAIN_STRATEGY_ENABLED or not domain:
        return {}
    try:
        with _connect_db(_DOMAIN_STRATEGY_DB) as conn:
            rows = conn.execute(
                "SELECT method, ok_count, fail_count FROM domain_strategy "
                "WHERE domain=?",
                (domain,),
            ).fetchall()
        return {r[0]: {"ok": r[1], "fail": r[2]} for r in rows}
    except Exception:
        return {}


def _should_skip_fast(domain: str) -> bool:
    """Return True when the fast/html path has failed FAIL_THRESHOLD times
    in a row on this domain — skip directly to browser escalation."""
    if not domain:
        return False
    strat = _get_domain_strategy(domain)
    html_stats = strat.get("html") or {}
    return html_stats.get("fail", 0) >= DOMAIN_STRATEGY_FAIL_THRESHOLD


_warehouse_http_client = None

def _get_warehouse_client():
    global _warehouse_http_client
    if _warehouse_http_client is None or _warehouse_http_client.is_closed:
        import httpx
        _warehouse_http_client = httpx.AsyncClient(
            timeout=15.0,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
        )
    return _warehouse_http_client

_warehouse_http_client = None

def _get_warehouse_client():
    global _warehouse_http_client
    if _warehouse_http_client is None or _warehouse_http_client.is_closed:
        import httpx
        _warehouse_http_client = httpx.AsyncClient(
            timeout=15.0,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=50),
        )
    return _warehouse_http_client

async def _forward_to_warehouse(**payload) -> bool:
    """Forward content to warehouse with connection pooling and exponential backoff."""
    max_retries = 3
    client = _get_warehouse_client()
    for attempt in range(max_retries):
        try:
            resp = await client.post(f"{WAREHOUSE_URL}/ingest", json=payload)
            if resp.status_code == 200:
                return True
            log.warning("warehouse_forward_fail attempt=%d/%d status=%d url=%s",
                        attempt + 1, max_retries, resp.status_code, payload.get("url", "")[:80])
        except Exception as e:
            log.warning("warehouse_forward_error attempt=%d/%d err=%s url=%s",
                        attempt + 1, max_retries, e, payload.get("url", "")[:80])
        await asyncio.sleep(0.3 * (2 ** attempt))
    return False


async def _retry_pending_forwards():
    """Background task: retry pending warehouse forwards every 60s."""
    while True:
        await asyncio.sleep(60)
        with _connect_db(_PENDING_FORWARD_DB) as conn:
            rows = conn.execute(
                "SELECT * FROM pending_forwards WHERE attempts < 10 ORDER BY id LIMIT 20"
            ).fetchall()
        if not rows:
            continue
        cols = ["id", "url", "markdown", "content", "title", "source_domain", "attempts", "last_attempt", "created_at"]
        for row in rows:
            d = dict(zip(cols, row))
            success = await _forward_to_warehouse(
                url=d["url"], markdown=d["markdown"], content=d["content"],
                title=d["title"], source_domain=d["source_domain"],
                word_count=len(d["markdown"].split()) if d["markdown"] else 0,
                language="en", author="", published="",
            )
            with _connect_db(_PENDING_FORWARD_DB) as conn:
                if success:
                    conn.execute("DELETE FROM pending_forwards WHERE id = ?", (d["id"],))
                    log.info("pending_forward_ok id=%d url=%s", d["id"], d["url"][:120])
                else:
                    conn.execute(
                        "UPDATE pending_forwards SET attempts = attempts + 1, last_attempt = ? WHERE id = ?",
                        (time.time(), d["id"]),
                    )
                conn.commit()


# ─── Models ───────────────────────────────────────────────
class CrawlRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)
    extraction_strategy: str = Field(default="markdown", pattern="^(markdown|text|llm|json_css)$")
    llm_instruction: Optional[str] = None
    css_selector: Optional[str] = None
    timeout: int = Field(default=30, ge=5, le=120)
    bypass_cache: bool = False
    cache_ttl_override: Optional[int] = None
    # ── escalation path (added 2026-06-12) ─────────────────────────
    render_mode: str = Field(
        default="auto",
        pattern="^(auto|fast|browser|ocr)$",
        description="auto = fast→browser→ocr escalation; fast = crawl4ai only; browser = force playwright; ocr = force screenshot+vision",
    )
    enable_ocr_fallback: bool = True
    return_screenshot: bool = False
    # ── lineage propagation (warehouse v2) ─────────────────────────
    # Caller may stamp these so the warehouse knows the provenance of
    # whatever ends up there. Optional and back-compat.
    seen_in_session: Optional[str] = None
    found_via_query: Optional[str] = None
    source_provider: Optional[str] = None  # search provider that surfaced this URL

class CrawlResponse(BaseModel):
    url: str
    content: str
    markdown: str
    title: Optional[str] = None
    author: Optional[str] = None
    published: Optional[str] = None
    language: Optional[str] = None
    word_count: int = 0
    source_domain: Optional[str] = None
    success: bool
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    crawled_at: float
    cache_hit: bool = False
    # ── escalation telemetry ──────────────────────────────────────
    extraction_method: str = "html"  # html | browser | ocr
    blocked: bool = False
    block_reason: Optional[str] = None
    screenshot_b64: Optional[str] = None
    screenshot_path: Optional[str] = None
    escalations: list = []  # ["browser", "ocr"]

class BatchCrawlRequest(BaseModel):
    urls: List[str] = Field(..., min_items=1, max_items=50)
    extraction_strategy: str = "markdown"
    timeout: int = 30
    bypass_cache: bool = False

class BatchCrawlResponse(BaseModel):
    results: List[CrawlResponse]
    success_count: int
    failure_count: int
    cache_hits: int
    total_duration_ms: float


# ─── Escalation config ────────────────────────────────────
BROWSER_RENDERER_URL = os.environ.get("BROWSER_RENDERER_URL", "http://browser-renderer:8015")
THIN_THRESHOLD = int(os.environ.get("CRAWLER_THIN_THRESHOLD", "500"))
ESCALATION_TIMEOUT = float(os.environ.get("CRAWLER_ESCALATION_TIMEOUT", "60"))

import re as _re
_BLOCKED_HTML_PATTERNS = [
    _re.compile(p, _re.I) for p in [
        r"just a moment", r"checking your browser", r"cloudflare",
        r"please enable (javascript|js)", r"access denied",
        r"are you a robot", r"unusual traffic", r"captcha",
        r"cf-challenge", r"ddos protection",
        # Cloudflare/Datadome/Akamai human-verification interstitials.
        # These pages aren't strict paywalls but they ARE blocking the
        # real content — should escalate to wayback like any other block.
        r"confirm.{0,12}(that\s+)?you[' ]?re?\s*human",
        r"verify.{0,12}(that\s+)?you[' ]?re?\s*human",
        r"prove you are (not a robot|human)",
        r"complete the captcha",
        r"press and hold",
        r"slide right to secure your access",
    ]
]


def _should_escalate(markdown: str, error_type: Optional[str] = None) -> tuple[bool, Optional[str]]:
    """Decide whether crawl4ai output is thin/blocked and needs browser fallback.

    Only check anti-bot patterns when output is small enough to be an
    interstitial — full article bodies that incidentally mention 'captcha'
    or 'cloudflare' must not trigger escalation.
    """
    if error_type in {"blocked", "rate_limited", "timeout", "connection"}:
        return True, error_type
    if not markdown:
        return True, "empty_body"
    if len(markdown) < THIN_THRESHOLD:
        return True, "thin_body"
    if len(markdown) < 30_000:
        head = markdown[:4000].lower()
        for pat in _BLOCKED_HTML_PATTERNS:
            m = pat.search(head)
            if m:
                return True, f"pattern:{m.group(0)[:40]}"
    return False, None


# ─── Wayback Machine fallback ──────────────────────────────────────────────
# When a fetch comes back blocked or paywalled (NYT, WSJ, FT, etc.), retry
# via the Internet Archive's most-recent snapshot. The Wayback API returns
# a snapshot URL we can fetch like any other HTML, then run through
# trafilatura. Tag the result extractor='wayback' so the operator knows.

_PAYWALL_HTML_PATTERNS = [
    _re.compile(p, _re.I) for p in [
        r"you have been blocked from",
        r"to continue reading\W*subscribe",
        r"subscribe to (read|continue|access)",
        r"this article is for subscribers",
        r"sign in to (read|continue|view)",
        r"already a subscriber",
        r"subscribe now",
    ]
]

WAYBACK_ENABLED = os.environ.get("WAYBACK_ENABLED", "true").lower() == "true"


def _detect_paywall(markdown: str) -> Optional[str]:
    """Return a reason string if markdown looks like a paywall/bot block."""
    if not markdown or len(markdown) > 50_000:
        return None
    head = markdown[:6000].lower()
    for pat in _PAYWALL_HTML_PATTERNS:
        m = pat.search(head)
        if m:
            return f"paywall:{m.group(0)[:40]}"
    return None


async def _try_wayback(url: str, rid: str = "") -> Optional[dict]:
    """Look up the latest Wayback snapshot for url, fetch it, return parsed result.
    Returns None if no snapshot exists or fetch fails. Caller should treat the
    result as already cleaned text + metadata."""
    if not WAYBACK_ENABLED:
        return None
    try:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=15.0, follow_redirects=True) as c:
            # 1. Ask Wayback if it has a snapshot.
            r = await c.get(
                "https://archive.org/wayback/available",
                params={"url": url},
                headers={"User-Agent": "dss-crawler/1.0 (wayback-fallback)"},
            )
            r.raise_for_status()
            d = r.json() or {}
            snap = (d.get("archived_snapshots") or {}).get("closest") or {}
            if not snap.get("available") or not snap.get("url"):
                log.info("wayback_no_snapshot [%s] url=%s", rid, url[:120])
                return None
            snap_url = snap["url"]
            snap_ts = snap.get("timestamp", "")

            # 2. Fetch the snapshot HTML.
            log.info("wayback_fetch [%s] url=%s snap=%s", rid, url[:120], snap_url[:120])
            r2 = await c.get(snap_url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; dss-crawler/1.0)",
            })
            r2.raise_for_status()
            html = r2.text

            # 3. Extract article body via trafilatura.
            from libs.common.text import extract_article as _extract
            extracted = _extract(html, url=url, output_format="markdown")
            md = extracted.get("content") or ""
            wc = len(md.split())
            if wc < 100:
                # Wayback snapshot was also thin — give up cleanly.
                log.info("wayback_thin [%s] url=%s wc=%d", rid, url[:120], wc)
                return None

            return {
                "ok": True,
                "markdown": md,
                "title": extracted.get("title"),
                "author": extracted.get("author"),
                "published": extracted.get("published"),
                "language": extracted.get("language"),
                "word_count": wc,
                "extractor": "wayback",
                "snapshot_url": snap_url,
                "snapshot_timestamp": snap_ts,
            }
    except Exception as e:
        log.warning("wayback_failed [%s] url=%s err=%s", rid, url[:120], e)
        return None


_SPA_DOMAINS = (
    "reddit.com", "twitter.com", "x.com", "medium.com", "substack.com",
    "linkedin.com", "facebook.com", "instagram.com", "discord.com",
    "youtube.com", "tiktok.com",
)


def _looks_like_spa(url: str) -> bool:
    u = url.lower()
    return any(d in u for d in _SPA_DOMAINS)


async def _render_via_browser(
    url: str,
    save_screenshot: bool = False,
    full_page: bool = False,
    run_ocr: bool = False,
) -> Optional[dict]:
    """Escalate to the browser-renderer service. Returns dict or None on hard failure.

    The renderer does article extraction (trafilatura) + optional OCR (RapidOCR)
    in-process, so the crawler doesn't need a second round-trip to the
    inference-gateway for the OCR fallback.

    For SPAs (reddit/twitter/medium/etc.) we enable auto_scroll so lazy-loaded
    comments / posts / replies materialize into the DOM before extraction.
    """
    try:
        import httpx as _httpx
        # OCR adds non-trivial CPU time on the renderer; bump timeout when requested.
        # Auto-scroll adds up to ~6 * 900ms = ~5s — give it headroom too.
        is_spa = _looks_like_spa(url)
        timeout = ESCALATION_TIMEOUT + (60 if run_ocr else 0) + (15 if is_spa else 0)
        async with _httpx.AsyncClient(timeout=timeout) as client:
            r = await client.post(
                f"{BROWSER_RENDERER_URL}/render",
                json={
                    "url": url,
                    "screenshot": True,
                    "full_page_screenshot": full_page,
                    "save_screenshot": save_screenshot,
                    "wait": "networkidle",
                    "timeout_ms": int((ESCALATION_TIMEOUT + (15 if is_spa else 0)) * 1000),
                    "extract_article": True,
                    "run_ocr": run_ocr,
                    "auto_scroll": is_spa,
                    "scroll_passes": 6 if is_spa else 0,
                    "scroll_pause_ms": 900,
                },
            )
            r.raise_for_status()
            return r.json()
    except Exception as e:
        log.warning("browser_renderer_failed url=%s err=%s", url[:120], e)
        return None


def _html_to_markdown(html: str, url: Optional[str] = None) -> str:
    """Real article extraction via trafilatura (with bs4 fallback)."""
    if not html:
        return ""
    extracted = _extract_article(html, url=url, output_format="markdown")
    return extracted.get("content") or ""


# ─── Rate Limiter ─────────────────────────────────────────
_domain_last_request: Dict[str, float] = {}
_domain_min_interval: float = 1.0  # 1s between requests per domain

def _extract_domain(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url).netloc or "unknown"

async def _rate_limit(domain: str):
    """Ensure minimum interval between requests to the same domain."""
    now = time.monotonic()
    last = _domain_last_request.get(domain, 0)
    wait = _domain_min_interval - (now - last)
    if wait > 0:
        await asyncio.sleep(wait)
    _domain_last_request[domain] = time.monotonic()


# ─── Startup ──────────────────────────────────────────────
_crawler: Optional[AsyncWebCrawler] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _crawler, _ingest_worker_task
    proxy_url = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY", "")
    log.info("Starting crawl4ai AsyncWebCrawler (proxy=%s)...", proxy_url or "direct")
    _crawler = AsyncWebCrawler(verbose=False, proxy=proxy_url if proxy_url else None)
    await _crawler.start()
    # Background workers — warehouse forward retry + async ingest queue.
    # FastAPI ignores @app.on_event hooks when lifespan_context is set, so
    # we kick off the ingest worker here too.
    retry_task = asyncio.create_task(_retry_pending_forwards())
    _ingest_worker_task = asyncio.create_task(_ingest_worker_loop())
    log.info("Crawler v2 ready — cache at %s, forward retry + ingest worker started", CACHE_DB)
    yield
    log.info("Shutting down crawler...")
    retry_task.cancel()
    if _ingest_worker_task:
        _ingest_worker_task.cancel()
    if _crawler:
        await _crawler.close()
    log.info("Crawler stopped")

app.router.lifespan_context = lifespan


# ─── Core Crawl ───────────────────────────────────────────
DOC_MAX_BYTES = int(os.environ.get("CRAWLER_DOC_MAX_BYTES", str(40 * 1024 * 1024)))  # 40 MB cap


# Content-Type prefixes we won't try to extract as text. If the server says
# this URL is a video/audio/image (and not embedded in an HTML page), there's
# no point running crawl4ai+browser+OCR+Wayback on it.
_BINARY_CONTENT_PREFIXES = (
    "video/", "audio/", "image/",
    "application/octet-stream",
    "application/zip", "application/x-gzip", "application/x-tar",
    "application/x-iso", "application/x-rar",
)


async def _check_binary_content(url: str, rid: str) -> Optional["CrawlResponse"]:
    """HEAD the URL — if it's a binary/non-text content type OR a definitive
    4xx not-found, return a fast-fail response instead of running it through
    the escalation ladder (which can spend 60-70s on a 404).

    Returns None when the content is text-shaped (let the normal flow proceed)."""
    try:
        import httpx as _httpx
        async with _httpx.AsyncClient(timeout=8.0, follow_redirects=True) as c:
            r = await c.head(url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; dss-crawler)",
            })
            status = r.status_code
            ct = (r.headers.get("Content-Type") or "").lower().split(";")[0].strip()
            server = (r.headers.get("Server") or "").lower()
            via = (r.headers.get("Via") or "").lower()
            has_cf_ray = "cf-ray" in {k.lower() for k in r.headers.keys()}
    except Exception:
        return None  # HEAD failed; let the normal path try (some servers block HEAD)

    # Hard-fail on definitive 404/410. No amount of escalation will fix a
    # missing page — short-circuit instead of burning ~70s on browser+OCR+wayback.
    # 403/401 we still try (might be UA-gated and unblock under playwright).
    if status in (404, 410):
        # Bot-blocking CDNs (Cloudflare, CloudFront, Heroku-via-CF) often serve
        # 404 to non-browser User-Agents while a real Playwright session sees
        # 200. Don't short-circuit — let the renderer escalation try.
        cdn_bot_blocks = (
            "cloudflare" in server or has_cf_ray
            or "cloudfront" in via or "cloudfront" in server
            or "heroku" in server  # heroku-router fronted by CF/CloudFront in practice
        )
        if cdn_bot_blocks:
            log.info("http_404_cdn_bot_block [%s] url=%s server=%r via=%r — falling through",
                     rid, url[:120], server[:40], via[:40])
            return None
        log.info("http_not_found [%s] url=%s status=%d", rid, url[:120], status)
        return CrawlResponse(
            url=url, content="", markdown="", success=False,
            error_type="not_found",
            error_message=f"HTTP {status} on HEAD — page does not exist",
            source_domain=_extract_domain(url), crawled_at=time.time(),
            extraction_method="head-404",
        )

    if not ct:
        return None
    # PDFs/DOCXs/EPUBs are NOT skipped — those go through _try_doc_extract.
    if ct in {"application/pdf", "application/x-pdf",
              "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
              "application/msword", "application/epub+zip",
              "text/markdown", "text/x-markdown", "text/plain",
              "application/rtf", "text/rtf"}:
        return None

    for prefix in _BINARY_CONTENT_PREFIXES:
        if ct.startswith(prefix):
            log.info("binary_skip [%s] url=%s content_type=%s", rid, url[:120], ct)
            return CrawlResponse(
                url=url, content="", markdown="", success=False,
                error_type="binary", error_message=f"binary content-type: {ct} (not text-shaped)",
                source_domain=_extract_domain(url), crawled_at=time.time(),
                extraction_method="binary",
            )
    return None


async def _try_doc_extract(req: "CrawlRequest", rid: str, url: str, domain: str):
    """If the URL is a known doc format, fetch + parse + cache + warehouse.

    Returns a CrawlResponse on a real doc, None to fall through to HTML.
    Strategy:
      1. HEAD request to learn Content-Type cheaply.
      2. If HEAD blocked (some servers 405 HEAD), try GET with Range: 0-2047.
      3. Classify by Content-Type, falling back to URL extension.
      4. If matched, fetch the full body, extract, cache, forward.
    """
    import formats as _fmt
    import httpx as _httpx

    # Quick extension shortcut: if the URL itself ends with a doc extension we
    # skip the HEAD round-trip.
    low_url = url.lower().split("?")[0]
    ext_matches = any(low_url.endswith(e) for e in
                      (".pdf", ".docx", ".doc", ".epub", ".md", ".markdown", ".txt", ".rtf"))

    content_type: Optional[str] = None
    if not ext_matches:
        try:
            async with _httpx.AsyncClient(timeout=10.0, follow_redirects=True) as c:
                r = await c.head(url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; dss-crawler)",
                })
                content_type = r.headers.get("Content-Type", "")
        except Exception:
            content_type = None

    extractor_name = _fmt.classify(content_type, url)
    if not extractor_name:
        return None  # treat as HTML

    log.info("doc_extract [%s] url=%s ext=%s ct=%s",
             rid, url[:120], extractor_name, (content_type or "?")[:60])

    await _rate_limit(domain)

    # Fetch the bytes with a size cap.
    try:
        async with _httpx.AsyncClient(timeout=60.0, follow_redirects=True) as c:
            async with c.stream("GET", url, headers={
                "User-Agent": "Mozilla/5.0 (compatible; dss-crawler)",
            }) as resp:
                resp.raise_for_status()
                if not content_type:
                    content_type = resp.headers.get("Content-Type", "")
                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.aiter_bytes():
                    total += len(chunk)
                    if total > DOC_MAX_BYTES:
                        return CrawlResponse(
                            url=url, content="", markdown="", success=False,
                            error_type="too_large",
                            error_message=f"Document exceeded {DOC_MAX_BYTES//1024//1024} MB cap",
                            source_domain=domain, crawled_at=time.time(),
                            extraction_method=extractor_name,
                        )
                    chunks.append(chunk)
                data = b"".join(chunks)
    except Exception as e:
        log.warning("doc_fetch_failed [%s] url=%s err=%s", rid, url[:120], e)
        # Fall through to HTML path — maybe crawl4ai can still salvage it.
        return None

    extracted = _fmt.extract(data, content_type, url) or {}
    # For PDFs, ok=False = "no text layer" (scanned). Don't bail — try OCR.
    if extractor_name != "pdf" and not extracted.get("ok"):
        err = extracted.get("error") or "extraction_failed"
        log.warning("doc_extract_failed [%s] url=%s err=%s", rid, url[:120], err)
        return CrawlResponse(
            url=url, content="", markdown="", success=False,
            error_type="doc_extract", error_message=str(err),
            source_domain=domain, crawled_at=time.time(),
            extraction_method=extractor_name,
        )

    md = extracted.get("markdown") or ""
    title = extracted.get("title")
    author = extracted.get("author")
    published = extracted.get("published")
    language = extracted.get("language")
    wc = extracted.get("word_count", 0)

    # ── Scanned-PDF OCR fallback ──────────────────────────────────────
    # PyMuPDF returns near-empty text for image-only/scanned PDFs (most
    # older academic + government scans). If the body is suspiciously
    # thin, render pages to PNGs and OCR them via browser-renderer's
    # RapidOCR endpoint. Cheap when not needed, decisive when needed.
    if extractor_name == "pdf" and wc < int(os.environ.get("OCR_FALLBACK_MIN_WORDS", "200")):
        log.info("pdf_ocr_fallback [%s] url=%s native_words=%d", rid, url[:120], wc)
        try:
            pngs = _fmt.render_pdf_pages_to_pngs(
                data,
                max_pages=int(os.environ.get("OCR_FALLBACK_MAX_PAGES", "25")),
                dpi=int(os.environ.get("OCR_FALLBACK_DPI", "150")),
            )
            if pngs:
                ocr_chunks: list[str] = []
                import httpx as _httpx
                async with _httpx.AsyncClient(timeout=120.0) as c:
                    for idx, png in enumerate(pngs):
                        try:
                            r = await c.post(
                                f"{BROWSER_RENDERER_URL}/ocr-image",
                                content=png,
                                headers={"Content-Type": "image/png"},
                            )
                            r.raise_for_status()
                            t = (r.json() or {}).get("text", "")
                            if t.strip():
                                ocr_chunks.append(t)
                        except Exception as e:
                            log.warning("ocr_page_failed [%s] page=%d err=%s", rid, idx, e)
                ocr_text = "\n\n".join(ocr_chunks).strip()
                ocr_wc = len(ocr_text.split())
                if ocr_wc > wc:
                    log.info("pdf_ocr_won [%s] url=%s native=%d ocr=%d",
                             rid, url[:120], wc, ocr_wc)
                    md = ocr_text
                    wc = ocr_wc
                    extractor_name = "pdf-ocr"
                else:
                    log.info("pdf_ocr_skipped [%s] url=%s ocr_wc=%d not better",
                             rid, url[:120], ocr_wc)
        except Exception as e:
            log.warning("pdf_ocr_fallback_failed [%s] url=%s err=%s", rid, url[:120], e)

    resp = CrawlResponse(
        url=url, content=md, markdown=md,
        title=title, author=author, published=published, language=language,
        word_count=wc, source_domain=domain, success=True,
        crawled_at=time.time(), cache_hit=False,
        extraction_method=extractor_name,
        blocked=False, block_reason=None,
        escalations=[extractor_name],  # mark the chosen path for telemetry
    )

    # Cache.
    if len(md) > 100:
        _cache_put(url, {
            "url": url, "content": md, "markdown": md,
            "title": title, "author": author, "published": published,
            "language": language, "word_count": wc,
            "success": True, "source_domain": domain,
            "crawled_at": time.time(), "headers": {},
            "extraction_method": extractor_name,
        })

    # Forward to warehouse with full lineage. Confidence heuristic: PDFs +
    # DOCX usually have high-quality structured text → 0.9 floor. EPUBs +
    # markdown likewise. Plain RTF gets a discount.
    if FORWARD_TO_WAREHOUSE and len(md) > 100:
        conf_floor = {"pdf": 0.85, "docx": 0.85, "epub": 0.8,
                      "markdown": 0.9, "text": 0.75, "rtf": 0.6}
        conf = min(1.0, conf_floor.get(extractor_name, 0.7) + min(0.15, wc / 5000.0))
        forwarded = await _forward_to_warehouse(
            url=url, markdown=md, content=md,
            title=title or "", author=author or "", published=published or "",
            language=language or "", word_count=wc, source_domain=domain,
            extractor=extractor_name,
            extraction_confidence=round(conf, 3),
            source_provider=req.source_provider,
            seen_in_session=req.seen_in_session,
            found_via_query=req.found_via_query,
        )
        if not forwarded:
            _store_pending_forward(
                url=url, markdown=md, content=md,
                title=title or "", source_domain=domain,
            )

    log.info("doc_ok [%s] url=%s extractor=%s words=%d title=%s",
             rid, url[:120], extractor_name, wc, (title or "")[:60])
    return resp


async def _do_crawl(req: CrawlRequest, rid: str = "") -> CrawlResponse:
    """Core crawl logic: check cache, fetch, extract, store."""
    url = req.url
    domain = _extract_domain(url)
    cache_ttl = req.cache_ttl_override or DEFAULT_TTL_SECONDS

    # Check cache
    if not req.bypass_cache:
        cached = _cache_get(url, ttl=cache_ttl)
        if cached and cached.get("markdown") and int(cached.get("word_count", 0)) > 0:
            log.info("cache_hit [%s] url=%s", rid, url[:120])
            return CrawlResponse(
                url=url,
                content=cached.get("content") or "",
                markdown=cached.get("markdown") or "",
                title=cached.get("title"),
                author=cached.get("author"),
                published=cached.get("published"),
                language=cached.get("language"),
                word_count=cached.get("word_count", 0),
                source_domain=domain,
                success=bool(cached.get("success", True)),
                error_type=cached.get("error_type"),
                error_message=cached.get("error_message"),
                crawled_at=cached.get("crawled_at", time.time()),
                cache_hit=True,
            )

    # ── Binary content fast-skip ──────────────────────────────────────
    # If HEAD says this is a video/audio/image, return a clean "binary" marker
    # without burning the playwright+OCR+Wayback ladder on bytes that aren't text.
    try:
        bin_resp = await _check_binary_content(url, rid)
        if bin_resp is not None:
            return bin_resp
    except Exception as e:
        log.warning("binary_check_failed url=%s err=%s", url[:120], e)

    # ── Domain-specific shortcuts ──────────────────────────────────────
    # Reddit/YouTube/HN/arXiv/Twitter/GitHub etc. expose structured APIs
    # that beat HTML rendering on quality. Try those first; on no-match or
    # failure, fall through to the generic pipeline below.
    try:
        from domain_extractors import try_domain_extract
        dom_res = await try_domain_extract(url)
        if dom_res is not None:
            now = time.time()
            resp = CrawlResponse(
                url=url,
                content=dom_res.get("content", ""),
                markdown=dom_res.get("markdown", ""),
                title=dom_res.get("title"),
                author=dom_res.get("author"),
                published=dom_res.get("published"),
                language="en",
                word_count=int(dom_res.get("word_count", 0)),
                source_domain=domain,
                success=True,
                extraction_method=dom_res.get("extraction_method", "domain-shortcut"),
                crawled_at=now,
            )
            _cache_put(url, resp.model_dump())
            if FORWARD_TO_WAREHOUSE:
                asyncio.create_task(_forward_to_warehouse(
                    url=url, markdown=resp.markdown, content=resp.content,
                    title=resp.title, author=resp.author, published=resp.published,
                    language=resp.language, word_count=resp.word_count,
                    source_domain=resp.source_domain,
                    source_provider=req.source_provider,
                    seen_in_session=req.seen_in_session,
                    found_via_query=req.found_via_query,
                    extractor=resp.extraction_method,
                    extraction_confidence=0.95,
                ))
            log.info("domain_shortcut_ok [%s] url=%s method=%s words=%d",
                     rid, url[:120], resp.extraction_method, resp.word_count)
            _record_strategy(domain, resp.extraction_method, True)
            return resp
    except Exception as e:
        log.warning("domain_extract_failed url=%s err=%s", url[:120], e)

    # ── Document-format detection ──────────────────────────────────────
    # Before sending the URL to crawl4ai (which renders in Chromium), check
    # whether the URL points at a PDF/DOCX/EPUB/MD/TXT. If so, fetch the
    # raw bytes and parse with the format-specific extractor. crawl4ai on
    # a PDF gives you Chrome's PDF-viewer UI, not the paper.
    try:
        import formats as _fmt
        doc_resp = await _try_doc_extract(req, rid, url, domain)
        if doc_resp is not None:
            return doc_resp
    except Exception as e:
        log.warning("doc_extract_check_failed url=%s err=%s", url[:120], e)

    if not _crawler:
        raise HTTPException(status_code=503, detail="Crawler not initialized")

    await _rate_limit(domain)

    try:
        kwargs = {"url": url, "cache_mode": CacheMode.BYPASS}
        if req.extraction_strategy == "llm" and req.llm_instruction:
            from crawl4ai.extraction_strategy import LLMExtractionStrategy
            kwargs["extraction_strategy"] = LLMExtractionStrategy(
                provider="deepseek", instruction=req.llm_instruction,
            )
        elif req.extraction_strategy == "json_css" and req.css_selector:
            from crawl4ai.extraction_strategy import JsonCssExtractionStrategy
            kwargs["extraction_strategy"] = JsonCssExtractionStrategy(schema=req.css_selector)

        started = time.monotonic()
        result = await asyncio.wait_for(_crawler.arun(**kwargs), timeout=req.timeout)
        elapsed = (time.monotonic() - started) * 1000

        if not result or not result.success:
            error_msg = getattr(result, "error_message", "Unknown crawl error") if result else "No result"
            log.warning("crawl_fail [%s] url=%s: %s", rid, url[:120], error_msg)
            _record_strategy(domain, "html", False)
            return CrawlResponse(
                url=url, content="", markdown="", success=False,
                error_type="crawl_error", error_message=str(error_msg),
                source_domain=domain, crawled_at=time.time(),
            )

        markdown = ""
        # Real article extraction: prefer trafilatura on the raw HTML over
        # crawl4ai's markdown (which retains nav/sidebar/footer chrome).
        raw_html = getattr(result, "html", "") or getattr(result, "cleaned_html", "") or ""
        if raw_html:
            extracted = _extract_article(raw_html, url=url, output_format="markdown")
            markdown = extracted.get("content") or ""
            traf_title = extracted.get("title")
            traf_author = extracted.get("author")
            traf_published = extracted.get("published")
            traf_language = extracted.get("language")
        else:
            traf_title = traf_author = traf_published = traf_language = None
            markdown = ""

        # If trafilatura extracted nothing usable, fall back to crawl4ai's markdown
        if len(markdown) < 200:
            if hasattr(result, "markdown") and result.markdown:
                markdown = str(result.markdown)
            elif hasattr(result, "markdown_v2") and result.markdown_v2:
                m2 = result.markdown_v2
                markdown = str(m2.text) if hasattr(m2, "text") else str(m2)

        text = markdown or getattr(result, "cleaned_html", "") or ""

        # Metadata — trafilatura wins, falls back to crawl4ai's metadata dict
        metadata = {}
        if hasattr(result, "metadata") and isinstance(result.metadata, dict):
            metadata = result.metadata

        title = traf_title or metadata.get("title") or getattr(result, "title", None)
        author = traf_author or metadata.get("author") or metadata.get("og:author")
        published = traf_published or metadata.get("published") or metadata.get("article:published_time")
        language = traf_language or metadata.get("language") or metadata.get("og:locale", "en")[:2]

        # ── Escalation ladder: fast → browser → ocr ──────────────────
        extraction_method = "html"
        escalations: list = []
        blocked_now, block_reason = _should_escalate(markdown)
        screenshot_b64: Optional[str] = None
        screenshot_path: Optional[str] = None

        force_browser = req.render_mode in ("browser", "ocr")
        force_ocr = req.render_mode == "ocr"

        # Per-domain memory: skip the fast/html path on domains where it has
        # failed FAIL_THRESHOLD consecutive times. Goes straight to browser.
        if not force_browser and not blocked_now and _should_skip_fast(domain):
            blocked_now, block_reason = True, "domain-strategy:skip-fast"
            log.info("strategy_skip_fast [%s] url=%s domain=%s",
                     rid, url[:120], domain)

        if req.render_mode != "fast" and (force_browser or blocked_now):
            log.info("escalate→browser [%s] url=%s reason=%s", rid, url[:120], block_reason or "forced")
            # Ask the renderer for both the cleanly-extracted article AND OCR
            # in a single round-trip when we're forcing OCR. Otherwise, OCR
            # only fires if the article extraction comes back thin.
            br = await _render_via_browser(url, save_screenshot=False, run_ocr=force_ocr)
            if br:
                escalations.append("browser")
                # Prefer renderer's trafilatura-extracted article over our own
                # fallback markdown (renderer already ran it).
                br_md = br.get("article_text") or _html_to_markdown(br.get("html") or "", url=url)
                screenshot_b64 = br.get("screenshot_b64")
                screenshot_path = br.get("screenshot_path")
                if len(br_md) > len(markdown):
                    markdown = br_md
                    text = br_md
                    extraction_method = "browser"
                # Use renderer's metadata if we didn't have any from crawl4ai
                if not author and br.get("article_author"):
                    author = br.get("article_author")
                if not published and br.get("article_published"):
                    published = br.get("article_published")
                if not title and br.get("article_title"):
                    title = br.get("article_title")
                blocked_now, block_reason = _should_escalate(markdown)
                if br.get("blocked"):
                    blocked_now = True
                    block_reason = block_reason or br.get("block_reason")
                # If we already got OCR text from the renderer, consider adopting it.
                # Re-run _should_escalate on the adopted text — OCR sometimes
                # returns the CAPTCHA/bot-challenge text itself, which still
                # needs a wayback fallback. Don't blindly mark blocked_now=False.
                renderer_ocr = br.get("ocr_text") or ""
                if force_ocr and renderer_ocr:
                    markdown = renderer_ocr
                    text = renderer_ocr
                    extraction_method = "ocr"
                    escalations.append("ocr")
                    blocked_now, block_reason = _should_escalate(markdown)
                elif renderer_ocr and len(renderer_ocr) > len(markdown):
                    markdown = renderer_ocr
                    text = renderer_ocr
                    extraction_method = "ocr"
                    escalations.append("ocr")
                    blocked_now, block_reason = _should_escalate(markdown)

        # OCR-only fallback path: if we hit here without going through browser
        # escalation (render_mode=fast then auto-detected blocked), run OCR now.
        if req.enable_ocr_fallback and blocked_now and "ocr" not in escalations:
            log.info("escalate→ocr [%s] url=%s reason=%s", rid, url[:120], block_reason or "forced")
            br = await _render_via_browser(url, save_screenshot=False, run_ocr=True)
            if br:
                if "browser" not in escalations:
                    escalations.append("browser")
                screenshot_b64 = br.get("screenshot_b64")
                screenshot_path = br.get("screenshot_path")
                ocr_text = br.get("ocr_text") or ""
                if ocr_text and (force_ocr or len(ocr_text) > len(markdown)):
                    markdown = ocr_text
                    text = ocr_text
                    extraction_method = "ocr"
                    escalations.append("ocr")
                    blocked_now, block_reason = _should_escalate(markdown)

        # ── Wayback fallback ──────────────────────────────────────────
        # After browser + OCR, if we're still blocked OR the content
        # looks like a paywall, try the Internet Archive's snapshot.
        # This unlocks NYT, WSJ, FT, and any other site IA has archived.
        paywall_signal = _detect_paywall(markdown) if not blocked_now else None
        needs_wayback = (
            req.render_mode != "fast"
            and "wayback" not in escalations
            and (blocked_now or paywall_signal is not None)
            and WAYBACK_ENABLED
        )
        if needs_wayback:
            log.info("escalate→wayback [%s] url=%s reason=%s",
                     rid, url[:120], block_reason or paywall_signal or "blocked")
            wb = await _try_wayback(url, rid=rid)
            if wb and wb.get("ok"):
                wb_md = wb.get("markdown") or ""
                if len(wb_md) > len(markdown):
                    markdown = wb_md
                    text = wb_md
                    extraction_method = "wayback"
                    escalations.append("wayback")
                    blocked_now, block_reason = False, None
                    # Use Wayback metadata when ours is empty
                    title = title or wb.get("title")
                    author = author or wb.get("author")
                    published = published or wb.get("published")
                    language = language or wb.get("language")

        # Boilerplate strip: applied to ALL outbound surfaces (response, cache,
        # warehouse) so consumers don't have to dedup nav chrome themselves.
        # Wayback content gets stripped too — it's still HTML-flavored markdown.
        clean_md = _strip_boilerplate(markdown)
        clean_text = _strip_boilerplate(text)
        # Fall back to raw if stripping nuked everything (rare on aggressive nav)
        if not clean_md.strip():
            clean_md, clean_text = markdown, text

        # Quality gate — detect "OCR dumped nav" output.
        # If the extraction method is OCR (or wayback) and the result looks
        # like a nav dump (no real sentences, lots of short fragments), demote
        # it: keep the response 200 for the client, but don't pollute the
        # warehouse with the garbage. Signal via low extraction_confidence.
        def _looks_like_nav_dump(t: str) -> bool:
            if not t:
                return True
            # Real article: sentence-like text. Nav dump: lots of short
            # all-caps-ish fragments separated by `|`, `>`, or whitespace.
            sentences = _re.findall(r"[A-Z][^\.!?\n]{30,}[\.!?]", t)
            words = t.split()
            if not words:
                return True
            sep_density = (t.count("|") + t.count(">")) / max(1, len(words))
            short_lines = [l for l in t.split("\n") if l.strip() and len(l.strip()) < 30]
            short_line_frac = len(short_lines) / max(1, len(t.split("\n")))
            # No sentences AND high separator density OR mostly short lines → nav
            return (
                len(sentences) < 2
                and (sep_density > 0.04 or short_line_frac > 0.6)
            )

        low_signal = extraction_method in ("ocr",) and _looks_like_nav_dump(clean_text)

        resp = CrawlResponse(
            url=url, content=clean_text, markdown=clean_md,
            title=title, author=author, published=published,
            language=language, word_count=len(clean_text.split()),
            source_domain=domain, success=True,
            crawled_at=time.time(), cache_hit=False,
            extraction_method=extraction_method,
            blocked=blocked_now,
            block_reason=block_reason,
            screenshot_b64=screenshot_b64 if req.return_screenshot else None,
            screenshot_path=screenshot_path,
            escalations=escalations,
        )

        # Store in cache (only if we got actual content)
        if len(clean_text) > 50:  # don't cache near-empty pages
            cache_data = {
                "url": url, "content": clean_text, "markdown": clean_md,
                "title": title, "author": author, "published": published,
                "language": language, "word_count": len(clean_text.split()),
                "success": True, "source_domain": domain,
                "crawled_at": time.time(), "headers": {},
                "extraction_method": extraction_method,
            }
            _cache_put(url, cache_data)

        # Forward to knowledge warehouse — but NOT if this is a low-signal
        # nav-dump. Polluting the warehouse with "Sign in | Subscribe | Menu"
        # actively makes hybrid retrieval worse.
        if FORWARD_TO_WAREHOUSE and len(clean_text) > 50 and not low_signal:
            wc = len(clean_md.split())
            # Heuristic confidence: word density + signal from escalations + blocked flag.
            # 1.0 = clean HTML extraction with many words; 0.0 = blocked/thin.
            conf = min(1.0, wc / 500.0)
            if blocked_now:
                conf *= 0.3
            if extraction_method == "ocr":
                conf *= 0.7  # OCR is real but lower-fidelity than HTML extraction
            elif extraction_method == "browser":
                conf *= 0.9
            forwarded = await _forward_to_warehouse(
                url=url, markdown=clean_md, content=clean_text,
                title=title or "", author=author or "", published=published or "",
                language=language or "en", word_count=wc,
                source_domain=domain,
                # ── lineage (v2) ──────────────────────────────────────────
                extractor=extraction_method,
                extraction_confidence=round(conf, 3),
                source_provider=req.source_provider,
                seen_in_session=req.seen_in_session,
                found_via_query=req.found_via_query,
            )
            if not forwarded:
                _store_pending_forward(
                    url=url, markdown=clean_md, content=clean_text,
                    title=title or "", source_domain=domain,
                )
                log.warning("warehouse_forward_queued url=%s — will retry", url[:120])

        if low_signal:
            log.info("low_signal_drop [%s] url=%s method=%s — kept in cache but NOT ingested",
                     rid, url[:120], extraction_method)
        log.info("crawl_ok [%s] url=%s title=%s len=%d %.0fms", rid, url[:120], title, len(markdown), elapsed)
        # Record per-domain memory: any method that produced >50 words of real
        # content is a "win". Nav dumps count as fails so we learn to skip.
        _record_strategy(domain, extraction_method,
                         len(clean_text.split()) > 50 and not low_signal)
        return resp

    except asyncio.TimeoutError:
        log.error("timeout [%s] url=%s after %ds", rid, url[:120], req.timeout)
        return CrawlResponse(
            url=url, content="", markdown="", success=False,
            error_type="timeout", error_message=f"Timeout after {req.timeout}s",
            source_domain=domain, crawled_at=time.time(),
        )
    except Exception as e:
        error_type = "unknown"
        msg = str(e)
        if "403" in msg or "forbidden" in msg.lower():
            error_type = "blocked"
        elif "429" in msg or "rate" in msg.lower():
            error_type = "rate_limited"
        elif "dns" in msg.lower() or "resolve" in msg.lower():
            error_type = "dns_error"
        elif "connect" in msg.lower() or "refused" in msg.lower():
            error_type = "connection"
        log.error("error [%s] url=%s type=%s: %s", rid, url[:120], error_type, msg)
        return CrawlResponse(
            url=url, content="", markdown="", success=False,
            error_type=error_type, error_message=msg,
            source_domain=domain, crawled_at=time.time(),
        )


# ─── Endpoints ────────────────────────────────────────────

class IngestFileResponse(BaseModel):
    filename: str
    extraction_method: str
    success: bool
    word_count: int = 0
    title: Optional[str] = None
    author: Optional[str] = None
    warehouse_id: Optional[int] = None
    error: Optional[str] = None


@app.post("/ingest-file", response_model=IngestFileResponse)
async def ingest_file(request: Request):
    """Ingest a local file (PDF/DOCX/EPUB/MD/TXT/RTF) directly into the warehouse.

    Accepts raw bytes in the request body. Filename via X-Filename header (or
    `?filename=` query param). Optional metadata via headers:
      X-Source-Url       — canonical URL if known (else local://filename)
      X-Title            — override extracted title
      X-Session-Id       — pipe into warehouse lineage
      X-Found-Via-Query  — pipe into warehouse lineage

    Same extractor + warehouse + auto-embed pipeline as URL crawls; the only
    difference is no fetch step. PDFs that are scanned will hit the OCR
    fallback just like crawled PDFs.
    """
    import formats as _fmt
    body = await request.body()
    if not body:
        raise HTTPException(400, "empty body")
    filename = request.headers.get("X-Filename") or request.query_params.get("filename") or "upload.bin"
    url = request.headers.get("X-Source-Url") or f"local://{filename}"
    rid = request.headers.get("X-Request-ID", "")
    session_id = request.headers.get("X-Session-Id")
    found_via_query = request.headers.get("X-Found-Via-Query")

    extractor_name = _fmt.classify(None, filename) or _fmt.classify(None, "x." + (filename.rsplit(".", 1)[-1] if "." in filename else ""))
    if not extractor_name:
        return IngestFileResponse(
            filename=filename, extraction_method="unknown", success=False,
            error="no extractor for file type — supported: pdf, docx, epub, md, txt, rtf",
        )

    log.info("ingest_file [%s] filename=%s extractor=%s bytes=%d", rid, filename, extractor_name, len(body))
    extracted = _fmt.extract(body, None, filename) or {}
    # For PDFs, ok=False often means "no embedded text layer" (scanned) — keep
    # going to the OCR fallback. For other formats, ok=False is terminal.
    if extractor_name != "pdf" and not extracted.get("ok"):
        return IngestFileResponse(
            filename=filename, extraction_method=extractor_name, success=False,
            error=extracted.get("error") or "extraction_failed",
        )

    md = extracted.get("markdown") or ""
    title = request.headers.get("X-Title") or extracted.get("title") or filename
    author = extracted.get("author")
    published = extracted.get("published")
    language = extracted.get("language")
    wc = extracted.get("word_count", 0)

    # Scanned-PDF OCR fallback also applies here.
    if extractor_name == "pdf" and wc < int(os.environ.get("OCR_FALLBACK_MIN_WORDS", "200")):
        log.info("ingest_file_pdf_ocr [%s] filename=%s native_words=%d", rid, filename, wc)
        try:
            pngs = _fmt.render_pdf_pages_to_pngs(body)
            if pngs:
                ocr_chunks: list[str] = []
                import httpx as _httpx
                async with _httpx.AsyncClient(timeout=120.0) as c:
                    for png in pngs:
                        try:
                            r = await c.post(
                                f"{BROWSER_RENDERER_URL}/ocr-image",
                                content=png,
                                headers={"Content-Type": "image/png"},
                            )
                            r.raise_for_status()
                            t = (r.json() or {}).get("text", "")
                            if t.strip():
                                ocr_chunks.append(t)
                        except Exception:
                            pass
                ocr_text = "\n\n".join(ocr_chunks).strip()
                ocr_wc = len(ocr_text.split())
                if ocr_wc > wc:
                    md = ocr_text
                    wc = ocr_wc
                    extractor_name = "pdf-ocr"
        except Exception as e:
            log.warning("ingest_file_pdf_ocr_failed [%s] err=%s", rid, e)

    domain = _extract_domain(url) if url.startswith("http") else "local"
    warehouse_id: Optional[int] = None

    if FORWARD_TO_WAREHOUSE and len(md) > 50:
        try:
            import httpx as _httpx
            async with _httpx.AsyncClient(timeout=30.0) as c:
                resp = await c.post(
                    f"{WAREHOUSE_URL}/ingest",
                    json={
                        "url": url,
                        "markdown": md,
                        "content": md,
                        "title": title,
                        "author": author or "",
                        "published": published or "",
                        "language": language or "",
                        "word_count": wc,
                        "source_domain": domain,
                        "tags": ["body", "local-ingest", extractor_name],
                        "extractor": extractor_name,
                        "extraction_confidence": 0.95 if extractor_name != "pdf-ocr" else 0.8,
                        "source_provider": "local-ingest",
                        "seen_in_session": session_id,
                        "found_via_query": found_via_query,
                    },
                )
                if resp.status_code == 200:
                    warehouse_id = (resp.json() or {}).get("id")
        except Exception as e:
            log.warning("ingest_file_warehouse_fail [%s] err=%s", rid, e)

    log.info("ingest_file_done [%s] filename=%s extractor=%s wc=%d warehouse_id=%s",
             rid, filename, extractor_name, wc, warehouse_id)
    return IngestFileResponse(
        filename=filename, extraction_method=extractor_name, success=True,
        word_count=wc, title=title, author=author, warehouse_id=warehouse_id,
    )


@app.post("/crawl", response_model=CrawlResponse)
async def crawl_url(req: CrawlRequest, request: Request):
    rid = request.headers.get("X-Request-ID", "")
    return await _do_crawl(req, rid)

@app.post("/crawl/batch", response_model=BatchCrawlResponse)
async def crawl_batch(req: BatchCrawlRequest, request: Request):
    rid = request.headers.get("X-Request-ID", "")
    started = time.monotonic()
    sem = asyncio.Semaphore(CRAWL_CONCURRENCY)

    async def crawl_one(url: str) -> CrawlResponse:
        async with sem:
            inner = CrawlRequest(
                url=url, extraction_strategy=req.extraction_strategy,
                timeout=req.timeout, bypass_cache=req.bypass_cache,
            )
            return await _do_crawl(inner, rid)

    results = await asyncio.gather(*[crawl_one(u) for u in req.urls])
    ok = sum(1 for r in results if r.success)
    cached = sum(1 for r in results if r.cache_hit)
    elapsed = (time.monotonic() - started) * 1000
    log.info("batch_done [%s]: %d/%d ok, %d cached, %.0fms", rid, ok, len(results), cached, elapsed)

    return BatchCrawlResponse(
        results=list(results), success_count=ok,
        failure_count=len(results) - ok, cache_hits=cached,
        total_duration_ms=elapsed,
    )

@app.get("/cache/stats")
async def cache_stats():
    return _cache_stats()

@app.post("/cache/clear")
async def cache_clear():
    with _connect_db(CACHE_DB) as conn:
        conn.execute("DELETE FROM cache")
        conn.commit()
    return {"cleared": True}

@app.get("/health")
async def health():
    # Count pending forwards
    with _connect_db(_PENDING_FORWARD_DB) as conn:
        pending = conn.execute("SELECT COUNT(*) FROM pending_forwards").fetchone()[0]
    return {
        "status": "healthy" if _crawler else "degraded",
        "cache_entries": _cache_stats()["total_entries"],
        "pending_forwards": pending,
        "version": "2.1.0",
    }

@app.get("/")
async def root():
    return {
        "service": "crawler",
        "version": "2.1.0",
        "endpoints": {
            "POST /crawl": "Single URL → markdown with caching",
            "POST /crawl/batch": "Batch crawl with concurrency control",
            "GET /cache/stats": "Cache statistics",
            "POST /cache/clear": "Clear all cached content",
            "GET /crawl/pending": "Pending warehouse forwards",
            "POST /crawl/retry-pending": "Force retry pending forwards",
            "GET /health": "Health check",
        },
    }


@app.get("/crawl/pending")
async def pending_forwards():
    """List pending warehouse forwards."""
    with _connect_db(_PENDING_FORWARD_DB) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT id, url, title, attempts, last_attempt, created_at FROM pending_forwards ORDER BY id LIMIT 100"
        ).fetchall()
        return {
            "total": len(rows),
            "pending": [
                {
                    "id": r["id"], "url": r["url"], "title": r["title"],
                    "attempts": r["attempts"],
                    "last_attempt": r["last_attempt"] or 0,
                    "created_at": r["created_at"],
                }
                for r in rows
            ],
        }


@app.post("/crawl/retry-pending")
async def retry_pending():
    """Force immediate retry of pending warehouse forwards."""
    await _retry_pending_forwards()
    return {"retried": True}


# ─── Site discovery & bulk ingest ───────────────────────────────────────
# Paste one URL → suck in everything: sitemap.xml, sitemap_index.xml,
# RSS/Atom feeds, then queue every discovered URL through /crawl with
# bounded concurrency. The polymath move.

class SiteIngestRequest(BaseModel):
    url: str = Field(..., min_length=1)
    max_urls: int = Field(default=200, ge=1, le=5000)
    concurrency: int = Field(default=4, ge=1, le=16)
    # Filter: only crawl URLs on the same host as the entry URL.
    same_host_only: bool = True
    # When False, only DISCOVER urls and return them; don't crawl.
    crawl: bool = True


class SiteIngestResponse(BaseModel):
    entry_url: str
    discovered: int
    crawled: int
    ok: int
    failed: int
    urls: list[str]
    sources: dict  # {"sitemap": N, "rss": N, "homepage_links": N}
    duration_ms: int


_SITEMAP_LOC_RE = _re.compile(r"<loc>\s*([^<]+?)\s*</loc>", _re.I)


async def _fetch_text(client, u: str, timeout: float = 12.0) -> Optional[str]:
    try:
        r = await client.get(u, timeout=timeout, follow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0 (compatible; dss-crawler/2.0)"})
        if r.status_code == 200 and r.text:
            return r.text
    except Exception:
        return None
    return None


async def _discover_site_urls(entry_url: str, *, max_urls: int,
                              same_host_only: bool) -> tuple[list[str], dict]:
    """Find URLs to crawl from a single entry URL.
    Strategy: sitemap → robots.txt sitemap hints → RSS/Atom → homepage <a>."""
    from urllib.parse import urljoin, urlparse
    import httpx as _httpx

    parsed = urlparse(entry_url)
    host = parsed.netloc
    base = f"{parsed.scheme}://{host}"
    counts = {"sitemap": 0, "rss": 0, "homepage_links": 0}
    found: list[str] = []
    seen: set[str] = set()

    def _add(u: str, bucket: str) -> bool:
        if not u or u in seen:
            return False
        if same_host_only:
            try:
                if urlparse(u).netloc and urlparse(u).netloc != host:
                    return False
            except Exception:
                return False
        seen.add(u)
        found.append(u)
        counts[bucket] += 1
        return True

    async with _httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        # Resolve entry_url to its canonical host. Two cases to handle:
        #   1. `www.foo.com` 30x's to `foo.com` (or vice versa) — we follow
        #      the redirect chain and reset host/base.
        #   2. `www.foo.com` doesn't resolve at all (some sites serve only
        #      the apex). HEAD throws DNS error. We retry the apex
        #      automatically — most operators who type the www form
        #      expect it to "just work".
        async def _probe_canonical(url: str) -> Optional[str]:
            try:
                r = await client.head(url, timeout=8.0)
                if r.status_code < 400:
                    return str(r.url)
            except Exception:
                pass
            return None

        candidates: list[str] = [entry_url]
        if host.startswith("www."):
            candidates.append(entry_url.replace("://www.", "://", 1))
        else:
            candidates.append(entry_url.replace("://", "://www.", 1))

        resolved: Optional[str] = None
        for cand in candidates:
            resolved = await _probe_canonical(cand)
            if resolved:
                break

        if resolved:
            final_parsed = urlparse(resolved)
            if final_parsed.netloc and final_parsed.netloc != host:
                log.info("site_discover_host_redirect from=%s to=%s",
                         host, final_parsed.netloc)
                host = final_parsed.netloc
                base = f"{final_parsed.scheme}://{host}"
                entry_url = resolved
        else:
            log.info("site_discover_head_failed url=%s — sitemap probe will "
                     "still try", entry_url[:100])
        # 1. If entry_url IS a sitemap or feed, parse it directly.
        # Otherwise probe sitemap candidates.
        sitemap_candidates: list[str] = []
        feed_candidates: list[str] = []

        if entry_url.lower().endswith((".xml", ".rss", ".atom")) or \
           "sitemap" in entry_url.lower() or "rss" in entry_url.lower() or \
           "feed" in entry_url.lower() or "atom" in entry_url.lower():
            # User pointed us directly at an index; try both parsers on it
            sitemap_candidates.append(entry_url)
            feed_candidates.append(entry_url)
        else:
            # Probe robots.txt for sitemap hints
            robots = await _fetch_text(client, f"{base}/robots.txt")
            if robots:
                for line in robots.splitlines():
                    if line.lower().startswith("sitemap:"):
                        sm = line.split(":", 1)[1].strip()
                        if sm:
                            sitemap_candidates.append(sm)
            # Default sitemap locations
            sitemap_candidates += [
                f"{base}/sitemap.xml",
                f"{base}/sitemap_index.xml",
                f"{base}/sitemap-index.xml",
            ]
            # Try common feeds + look for <link rel=alternate> in homepage
            feed_candidates += [
                f"{base}/feed",
                f"{base}/rss",
                f"{base}/rss.xml",
                f"{base}/feed.xml",
                f"{base}/atom.xml",
                f"{base}/index.xml",
            ]
            home = await _fetch_text(client, entry_url)
            if home:
                for m in _re.finditer(
                    r'<link[^>]+rel=["\'](?:alternate|sitemap)["\'][^>]+href=["\']([^"\']+)["\']',
                    home, _re.I,
                ):
                    feed_candidates.append(urljoin(base, m.group(1)))
                # Also harvest <a href> as a last resort
                for m in _re.finditer(r'<a[^>]+href=["\']([^"\']+)["\']', home, _re.I):
                    href = urljoin(base, m.group(1))
                    if href.startswith("http") and "#" not in href:
                        # Reserve for fallback below
                        pass

        # 2. Try sitemap candidates, recursing into <sitemap> index nodes.
        async def _parse_sitemap(sm_url: str, depth: int = 0):
            if depth > 2 or len(found) >= max_urls:
                return
            txt = await _fetch_text(client, sm_url, timeout=20.0)
            if not txt:
                return
            locs = _SITEMAP_LOC_RE.findall(txt)
            if "<sitemapindex" in txt.lower():
                # Index of sitemaps — recurse, but cap fanout
                for loc in locs[:25]:
                    if len(found) >= max_urls:
                        break
                    await _parse_sitemap(loc, depth + 1)
                return
            for loc in locs:
                if not _add(loc, "sitemap"):
                    continue
                if len(found) >= max_urls:
                    return

        for sm in sitemap_candidates:
            if len(found) >= max_urls:
                break
            await _parse_sitemap(sm)

        # 3. If sitemap yielded few/none, try RSS/Atom (entries → <link>).
        if len(found) < max_urls:
            try:
                import feedparser  # type: ignore
            except Exception:
                feedparser = None  # type: ignore
            if feedparser is not None:
                for fc in feed_candidates:
                    if len(found) >= max_urls:
                        break
                    txt = await _fetch_text(client, fc)
                    if not txt:
                        continue
                    parsed_feed = feedparser.parse(txt)
                    for entry in (parsed_feed.entries or []):
                        link = entry.get("link") or entry.get("id")
                        if link and _add(link, "rss"):
                            if len(found) >= max_urls:
                                break

        # 4. Last-resort: homepage <a href> harvest. Only kicks in if both
        # sitemap and feed probes came up empty (very few sites do this).
        if not found:
            home = await _fetch_text(client, entry_url)
            if home:
                for m in _re.finditer(r'<a[^>]+href=["\']([^"\']+)["\']', home, _re.I):
                    href = urljoin(base, m.group(1))
                    if href.startswith("http") and "#" not in href[len(base):]:
                        if _add(href, "homepage_links"):
                            if len(found) >= max_urls:
                                break

    return found[:max_urls], counts


@app.post("/ingest/site", response_model=SiteIngestResponse)
async def ingest_site(req: SiteIngestRequest):
    """Discover URLs under a site (sitemap > RSS > homepage links) and crawl them.

    Pass `crawl=false` to just see what we'd queue without actually fetching.

    BLOCKING — for large sites use POST /ingest/site/async which returns a
    job_id immediately and crawls in the background.
    """
    t0 = time.monotonic()
    urls, sources = await _discover_site_urls(
        req.url, max_urls=req.max_urls, same_host_only=req.same_host_only,
    )
    if not req.crawl or not urls:
        return SiteIngestResponse(
            entry_url=req.url, discovered=len(urls), crawled=0,
            ok=0, failed=0, urls=urls, sources=sources,
            duration_ms=int((time.monotonic() - t0) * 1000),
        )

    sem = asyncio.Semaphore(req.concurrency)
    results = {"ok": 0, "failed": 0}

    async def _one(u: str):
        async with sem:
            try:
                inner = CrawlRequest(
                    url=u, source_provider="site-ingest",
                    found_via_query=req.url,
                )
                r = await _do_crawl(inner, rid="site")
                if r.success and r.word_count > 50:
                    results["ok"] += 1
                else:
                    results["failed"] += 1
            except Exception:
                results["failed"] += 1

    await asyncio.gather(*[_one(u) for u in urls])

    return SiteIngestResponse(
        entry_url=req.url, discovered=len(urls), crawled=len(urls),
        ok=results["ok"], failed=results["failed"],
        urls=urls, sources=sources,
        duration_ms=int((time.monotonic() - t0) * 1000),
    )


# ─── Async ingest queue ─────────────────────────────────────────────────
# Fire-and-forget pipeline: client POSTs site/url-list, gets a job_id back
# immediately, then polls /ingest-jobs/{id} for progress. The worker walks
# one job at a time so we don't burn the crawler with parallel campaigns.

_INGEST_JOB_DB = CACHE_DIR / "ingest_jobs.db"


def _init_ingest_jobs():
    with _connect_db(_INGEST_JOB_DB) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ingest_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,              -- 'site' | 'urls'
                entry_url TEXT,
                urls_json TEXT,                  -- list[str] for 'urls', also stored after discovery for 'site'
                max_urls INTEGER NOT NULL,
                concurrency INTEGER NOT NULL,
                same_host_only INTEGER NOT NULL DEFAULT 1,
                source_provider TEXT,
                status TEXT NOT NULL DEFAULT 'queued',  -- queued|running|done|failed
                discovered INTEGER DEFAULT 0,
                completed INTEGER DEFAULT 0,
                ok INTEGER DEFAULT 0,
                failed INTEGER DEFAULT 0,
                error TEXT,
                created_at REAL NOT NULL,
                started_at REAL,
                finished_at REAL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_ingest_jobs_status ON ingest_jobs(status, created_at)"
        )
        conn.commit()


_init_ingest_jobs()

# In-memory job queue. Persistence is in SQLite; the queue is just the
# wakeup signal for the worker. Items are job_id ints.
_ingest_job_queue: "asyncio.Queue[int]" = asyncio.Queue()


def _create_ingest_job(
    *, kind: str, entry_url: Optional[str],
    urls: Optional[list[str]],
    max_urls: int, concurrency: int, same_host_only: bool,
    source_provider: Optional[str] = None,
) -> int:
    """Persist a new job row and return the id. The worker picks it up via
    _ingest_job_queue."""
    urls_json = json.dumps(urls) if urls else None
    with _connect_db(_INGEST_JOB_DB) as conn:
        cursor = conn.execute(
            """INSERT INTO ingest_jobs
            (kind, entry_url, urls_json, max_urls, concurrency,
             same_host_only, source_provider, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'queued', ?)""",
            (kind, entry_url, urls_json, max_urls, concurrency,
             1 if same_host_only else 0, source_provider, time.time()),
        )
        conn.commit()
        return cursor.lastrowid


def _update_ingest_job(job_id: int, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    vals = list(fields.values()) + [job_id]
    with _connect_db(_INGEST_JOB_DB) as conn:
        conn.execute(f"UPDATE ingest_jobs SET {cols} WHERE id = ?", vals)
        conn.commit()


def _get_ingest_job(job_id: int) -> Optional[dict]:
    with _connect_db(_INGEST_JOB_DB) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM ingest_jobs WHERE id = ?", (job_id,),
        ).fetchone()
        return dict(row) if row else None


def _list_ingest_jobs(limit: int = 50, status: Optional[str] = None) -> list[dict]:
    with _connect_db(_INGEST_JOB_DB) as conn:
        conn.row_factory = sqlite3.Row
        if status:
            rows = conn.execute(
                "SELECT * FROM ingest_jobs WHERE status = ? ORDER BY id DESC LIMIT ?",
                (status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM ingest_jobs ORDER BY id DESC LIMIT ?", (limit,),
            ).fetchall()
        return [dict(r) for r in rows]


async def _run_ingest_job(job_id: int) -> None:
    """Worker body: fetch the job row, discover (if needed), crawl URLs,
    update counters along the way."""
    job = _get_ingest_job(job_id)
    if not job:
        return
    _update_ingest_job(job_id, status="running", started_at=time.time())
    try:
        # Discovery stage.
        urls: list[str] = []
        if job["urls_json"]:
            urls = json.loads(job["urls_json"])
        if not urls and job["entry_url"]:
            disc, _ = await _discover_site_urls(
                job["entry_url"],
                max_urls=job["max_urls"],
                same_host_only=bool(job["same_host_only"]),
            )
            urls = disc
            _update_ingest_job(
                job_id,
                discovered=len(urls),
                urls_json=json.dumps(urls),
            )
        else:
            _update_ingest_job(job_id, discovered=len(urls))

        if not urls:
            _update_ingest_job(
                job_id, status="done",
                finished_at=time.time(),
            )
            return

        sem = asyncio.Semaphore(max(1, int(job["concurrency"])))
        ok_count = 0
        fail_count = 0

        async def _one(u: str) -> bool:
            async with sem:
                try:
                    inner = CrawlRequest(
                        url=u,
                        source_provider=job["source_provider"] or "site-ingest",
                        found_via_query=job["entry_url"] or "ingest-job",
                    )
                    r = await _do_crawl(inner, rid=f"job{job_id}")
                    return bool(r.success and r.word_count > 50)
                except Exception:
                    return False

        # Process and persist progress every 5 completions so the UI can
        # show motion on large jobs.
        tasks = [asyncio.create_task(_one(u)) for u in urls]
        completed = 0
        for fut in asyncio.as_completed(tasks):
            success = await fut
            if success:
                ok_count += 1
            else:
                fail_count += 1
            completed += 1
            if completed % 5 == 0 or completed == len(tasks):
                _update_ingest_job(
                    job_id,
                    completed=completed, ok=ok_count, failed=fail_count,
                )

        _update_ingest_job(
            job_id,
            status="done",
            completed=completed, ok=ok_count, failed=fail_count,
            finished_at=time.time(),
        )
    except Exception as e:
        log.exception("ingest_job_failed job_id=%d err=%s", job_id, e)
        _update_ingest_job(
            job_id,
            status="failed",
            error=str(e)[:500],
            finished_at=time.time(),
        )


async def _ingest_worker_loop():
    """Single-consumer worker. Pulls one job at a time from _ingest_job_queue
    and runs it to completion. Crash-resilient: on startup we re-queue any
    jobs that were 'queued' or 'running' (a previous crash left them stuck)."""
    # Re-enqueue jobs left mid-flight by a previous boot.
    with _connect_db(_INGEST_JOB_DB) as conn:
        stuck = conn.execute(
            "SELECT id FROM ingest_jobs WHERE status IN ('queued','running')"
        ).fetchall()
        for (jid,) in stuck:
            # Treat 'running' as if we never started — reset and re-queue.
            conn.execute(
                "UPDATE ingest_jobs SET status='queued', started_at=NULL WHERE id=?",
                (jid,),
            )
            await _ingest_job_queue.put(jid)
        conn.commit()
    log.info("ingest_worker_started requeued=%d", len(stuck))

    while True:
        job_id = await _ingest_job_queue.get()
        try:
            await _run_ingest_job(job_id)
        finally:
            _ingest_job_queue.task_done()


# The worker task handle is set when lifespan() above starts it. This
# crawler's FastAPI app already declares lifespan_context which means
# @app.on_event("startup") would be silently ignored.
_ingest_worker_task: Optional[asyncio.Task] = None


# ─── Async ingest endpoints ─────────────────────────────────────────────

class AsyncSiteIngestResponse(BaseModel):
    job_id: int
    status: str
    entry_url: Optional[str] = None


@app.post("/ingest/site/async", response_model=AsyncSiteIngestResponse)
async def ingest_site_async(req: SiteIngestRequest):
    """Queue a site-ingest job and return immediately with the job_id.
    Use GET /ingest-jobs/{job_id} to poll progress."""
    job_id = _create_ingest_job(
        kind="site",
        entry_url=req.url,
        urls=None,
        max_urls=req.max_urls,
        concurrency=req.concurrency,
        same_host_only=req.same_host_only,
        source_provider="site-ingest",
    )
    await _ingest_job_queue.put(job_id)
    return AsyncSiteIngestResponse(
        job_id=job_id, status="queued", entry_url=req.url,
    )


class UrlsIngestRequest(BaseModel):
    urls: list[str]
    concurrency: int = Field(default=4, ge=1, le=16)
    source_provider: Optional[str] = "urls-ingest"


@app.post("/ingest/urls/async", response_model=AsyncSiteIngestResponse)
async def ingest_urls_async(req: UrlsIngestRequest):
    """Queue a list-of-URLs ingest job. Returns the job_id."""
    if not req.urls:
        raise HTTPException(status_code=400, detail="urls list is empty")
    job_id = _create_ingest_job(
        kind="urls",
        entry_url=None,
        urls=req.urls,
        max_urls=len(req.urls),
        concurrency=req.concurrency,
        same_host_only=False,
        source_provider=req.source_provider,
    )
    await _ingest_job_queue.put(job_id)
    return AsyncSiteIngestResponse(job_id=job_id, status="queued")


@app.get("/ingest-jobs")
async def list_ingest_jobs(limit: int = 50, status: Optional[str] = None):
    """List recent ingest jobs (newest first)."""
    jobs = _list_ingest_jobs(limit=limit, status=status)
    # Don't return the full urls blob on list (could be 5000 URLs)
    for j in jobs:
        j.pop("urls_json", None)
    return {"jobs": jobs, "count": len(jobs)}


@app.get("/ingest-jobs/{job_id}")
async def get_ingest_job(job_id: int, include_urls: bool = False):
    """Get a single ingest job, optionally with the discovered URLs."""
    job = _get_ingest_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="job not found")
    if not include_urls:
        job.pop("urls_json", None)
    else:
        if job.get("urls_json"):
            try:
                job["urls"] = json.loads(job["urls_json"])
            except Exception:
                job["urls"] = []
            del job["urls_json"]
    return job


@app.get("/admin/domain-strategies")
async def list_domain_strategies(limit: int = 50):
    """Inspect per-domain extraction memory."""
    with _connect_db(_DOMAIN_STRATEGY_DB) as conn:
        rows = conn.execute(
            "SELECT domain, method, ok_count, fail_count, last_success "
            "FROM domain_strategy ORDER BY ok_count + fail_count DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return {
        "total": len(rows),
        "strategies": [
            {"domain": r[0], "method": r[1], "ok": r[2], "fail": r[3],
             "last_success": r[4]}
            for r in rows
        ],
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
