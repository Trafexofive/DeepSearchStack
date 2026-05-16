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

# ── Boilerplate stripping ─────────────────────────────────────────────────

import re as _re

_BOILERPLATE_PATTERNS = [
    _re.compile(r, _re.IGNORECASE) for r in [
        r'^\[Jump to content\]', r'^\[Skip to (content|main|navigation)\]',
        r'^Main menu$', r'^move to sidebar', r'^(Navigation|Contents|Menu)\s*$',
        r'^\[.*?(Privacy|Terms|Cookie|Legal|Accessibility)\]',
        r'^(Cookie|Privacy|Terms|Legal|Accessibility)\b',
        r'^(Theme|Language|Version)\s+(Auto|Light|Dark)',
        r'^(Previous|Next) topic', r'^Keyboard shortcuts$',
        r'^Press .(←|→|S|\?|Esc). to', r'^\[.*?\]\(https?://.*?(privacy|terms|cookie)\)',
        r'^\[ Sign in \]', r'^Sign in$', r'^Navigation Menu$',
        r'^Toggle navigation$', r'^Search or jump to',
    ]
]
_BOILERPLATE_SECTIONS = [
    'see also', 'references', 'external links', 'further reading',
    'notes', 'footnotes', 'citations', 'bibliography', 'navigation menu',
]

def _strip_boilerplate(markdown: str) -> str:
    if not markdown:
        return markdown
    lines = markdown.split('\n')
    cleaned = []
    skip_section = False
    skip_level = 0
    for line in lines:
        stripped = line.strip()
        heading = _re.match(r'^(#{1,6})\s+', stripped)
        if heading:
            level = len(heading.group(1))
            text = stripped[heading.end():].strip().lower()
            if skip_section and level <= skip_level:
                skip_section = False
            if text in _BOILERPLATE_SECTIONS:
                skip_section = True
                skip_level = level
                continue
        if skip_section:
            continue
        if stripped and any(p.search(stripped) for p in _BOILERPLATE_PATTERNS):
            continue
        cleaned.append(line)
    result = '\n'.join(cleaned).strip()
    result = _re.sub(r'\n{3,}', '\n\n', result)
    return result if result else markdown


# ─── Config ───────────────────────────────────────────────
CACHE_DIR = Path(os.environ.get("CRAWLER_CACHE_DIR", "/app/cache"))
CACHE_DB = CACHE_DIR / "cache.db"
DEFAULT_TTL_SECONDS = int(os.environ.get("CRAWLER_CACHE_TTL", "86400"))  # 24h
CRAWL_CONCURRENCY = int(os.environ.get("CRAWLER_CONCURRENCY", "10"))  # concurrent crawls
WAREHOUSE_URL = os.environ.get("KNOWLEDGE_WAREHOUSE_URL", "http://knowledge-warehouse:8009")
FORWARD_TO_WAREHOUSE = os.environ.get("FORWARD_TO_WAREHOUSE", "false").lower() == "true"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [crawler] %(message)s",
)
log = logging.getLogger("crawler")

app = FastAPI(title="DeepSearch Crawler v2", version="2.0.0")

# ─── Cache ────────────────────────────────────────────────
def _init_cache():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(CACHE_DB)) as conn:
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

def _cache_get(url: str, ttl: int = DEFAULT_TTL_SECONDS) -> Optional[dict]:
    key = _cache_key(url)
    with sqlite3.connect(str(CACHE_DB)) as conn:
        row = conn.execute(
            "SELECT * FROM cache WHERE url_hash = ? AND crawled_at > ?",
            (key, time.time() - ttl),
        ).fetchone()
    if row:
        cols = [d[0] for d in conn.execute("PRAGMA table_info(cache)").fetchall()]
        return dict(zip(cols, row))
    return None

def _cache_put(url: str, data: dict):
    key = _cache_key(url)
    domain = data.get("source_domain", "")
    with sqlite3.connect(str(CACHE_DB)) as conn:
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
    with sqlite3.connect(str(CACHE_DB)) as conn:
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
    with sqlite3.connect(str(_PENDING_FORWARD_DB)) as conn:
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

async def _forward_to_warehouse(**payload) -> bool:
    """Forward content to warehouse with 3 retries, exponential backoff."""
    import httpx
    max_retries = 3
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(f"{WAREHOUSE_URL}/ingest", json=payload)
                if resp.status_code == 200:
                    return True
                log.warning("warehouse_forward_fail attempt=%d/%d status=%d url=%s",
                           attempt + 1, max_retries, resp.status_code, payload.get("url", "")[:120])
        except Exception as e:
            log.warning("warehouse_forward_error attempt=%d/%d url=%s: %s",
                       attempt + 1, max_retries, payload.get("url", "")[:120], str(e))
        if attempt < max_retries - 1:
            await asyncio.sleep(2 ** attempt)  # 1s, 2s, 4s
    return False

def _store_pending_forward(**payload):
    """Store failed forward in persistent queue for background retry."""
    with sqlite3.connect(str(_PENDING_FORWARD_DB)) as conn:
        conn.execute("""
            INSERT INTO pending_forwards (url, markdown, content, title, source_domain, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            payload.get("url", ""), payload.get("markdown", ""),
            payload.get("content", ""), payload.get("title", ""),
            payload.get("source_domain", ""), time.time(),
        ))
        conn.commit()

async def _retry_pending_forwards():
    """Background task: retry pending warehouse forwards every 60s."""
    while True:
        await asyncio.sleep(60)
        with sqlite3.connect(str(_PENDING_FORWARD_DB)) as conn:
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
            with sqlite3.connect(str(_PENDING_FORWARD_DB)) as conn:
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
    global _crawler
    log.info("Starting crawl4ai AsyncWebCrawler...")
    _crawler = AsyncWebCrawler(verbose=False)
    await _crawler.start()
    # Background warehouse forward retry worker
    retry_task = asyncio.create_task(_retry_pending_forwards())
    log.info("Crawler v2 ready — cache at %s, forward retry worker started", CACHE_DB)
    yield
    log.info("Shutting down crawler...")
    retry_task.cancel()
    if _crawler:
        await _crawler.close()
    log.info("Crawler stopped")

app.router.lifespan_context = lifespan


# ─── Core Crawl ───────────────────────────────────────────
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
            return CrawlResponse(
                url=url, content="", markdown="", success=False,
                error_type="crawl_error", error_message=str(error_msg),
                source_domain=domain, crawled_at=time.time(),
            )

        markdown = ""
        if hasattr(result, "markdown") and result.markdown:
            markdown = str(result.markdown)
        elif hasattr(result, "markdown_v2") and result.markdown_v2:
            m2 = result.markdown_v2
            markdown = str(m2.text) if hasattr(m2, "text") else str(m2)

        text = markdown or getattr(result, "cleaned_html", "") or ""

        # Metadata
        metadata = {}
        if hasattr(result, "metadata") and isinstance(result.metadata, dict):
            metadata = result.metadata

        title = metadata.get("title") or getattr(result, "title", None)
        author = metadata.get("author") or metadata.get("og:author")
        published = metadata.get("published") or metadata.get("article:published_time")
        language = metadata.get("language") or metadata.get("og:locale", "en")[:2]

        resp = CrawlResponse(
            url=url, content=text, markdown=markdown,
            title=title, author=author, published=published,
            language=language, word_count=len(text.split()),
            source_domain=domain, success=True,
            crawled_at=time.time(), cache_hit=False,
        )

        # Store in cache (only if we got actual content)
        if len(text) > 50:  # don't cache near-empty pages
            cache_data = {
                "url": url, "content": text, "markdown": markdown,
                "title": title, "author": author, "published": published,
                "language": language, "word_count": len(text.split()),
                "success": True, "source_domain": domain,
                "crawled_at": time.time(), "headers": {},
            }
            _cache_put(url, cache_data)

        # Forward to knowledge warehouse (with retry, boilerplate stripped)
        if FORWARD_TO_WAREHOUSE and len(text) > 50:
            clean_md = _strip_boilerplate(markdown)
            clean_text = _strip_boilerplate(text)
            forwarded = await _forward_to_warehouse(
                url=url, markdown=clean_md, content=clean_text,
                title=title or "", author=author or "", published=published or "",
                language=language or "en", word_count=len(clean_md.split()),
                source_domain=domain,
            )
            if not forwarded:
                _store_pending_forward(
                    url=url, markdown=clean_md, content=clean_text,
                    title=title or "", source_domain=domain,
                )
                log.warning("warehouse_forward_queued url=%s — will retry", url[:120])

        log.info("crawl_ok [%s] url=%s title=%s len=%d %.0fms", rid, url[:120], title, len(markdown), elapsed)
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
    with sqlite3.connect(str(CACHE_DB)) as conn:
        conn.execute("DELETE FROM cache")
        conn.commit()
    return {"cleared": True}

@app.get("/health")
async def health():
    # Count pending forwards
    with sqlite3.connect(str(_PENDING_FORWARD_DB)) as conn:
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
    with sqlite3.connect(str(_PENDING_FORWARD_DB)) as conn:
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
