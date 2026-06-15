"""
web-api - DeepSearch Cross-Domain Aggregation Orchestrator

Endpoints:
  POST /api/search/stream     - search → synthesize (streaming)
  POST /api/aggregate         - cross-domain aggregation with source-of-truth extraction
  POST /api/completion/stream - direct LLM completion proxy
  GET  /api/providers         - list available LLM providers
  GET  /health                - health + dependency status
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, FileResponse
from pydantic import BaseModel, Field

# Redis cache - optional, fails open if unreachable
_REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
_redis = None
_CACHE_TTL = int(os.environ.get("AGGREGATE_CACHE_TTL", "3600"))  # 1 hour
_CACHE_PREFIX = "dss:aggregate:"

async def _get_redis():
    global _redis
    if _redis is not None:
        return _redis
    try:
        import redis.asyncio as aioredis
        _redis = aioredis.from_url(_REDIS_URL, decode_responses=True, socket_connect_timeout=2)
        await _redis.ping()
        log.info("Redis cache connected: %s", _REDIS_URL)
    except Exception as e:
        log.warning("Redis unavailable - caching disabled: %s", e)
        _redis = False
    return _redis

def _cache_key(query: str, max_results: int, include_warehouse: bool, reconcile: bool) -> str:
    raw = f"{query}|{max_results}|{include_warehouse}|{reconcile}"
    return _CACHE_PREFIX + hashlib.sha256(raw.encode()).hexdigest()[:16]

async def _cache_get(key: str) -> Optional[dict]:
    r = await _get_redis()
    if not r:
        return None
    try:
        data = await r.get(key)
        return json.loads(data) if data else None
    except Exception:
        return None

async def _cache_set(key: str, data: dict):
    r = await _get_redis()
    if not r:
        return
    try:
        await r.setex(key, _CACHE_TTL, json.dumps(data, default=str))
    except Exception:
        pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [web-api] %(message)s",
)
log = logging.getLogger("web_api")

# ─── Service URLs ──────────────────────────────────────────
SEARCH_AGENT_URL = os.environ.get("SEARCH_AGENT_URL", "http://search-agent:8013")
INFERENCE_GATEWAY_URL = os.environ.get("INFERENCE_GATEWAY_URL", "http://inference_gateway:8005")
SEARCH_GATEWAY_URL = os.environ.get("SEARCH_GATEWAY_URL", "http://search-gateway:8002")
WAREHOUSE_URL = os.environ.get("WAREHOUSE_URL", "http://knowledge-warehouse:8009")
CRAWLER_URL = os.environ.get("CRAWLER_URL", "http://crawler:8000")
VECTOR_STORE_URL = os.environ.get("VECTOR_STORE_URL", "http://vector-store:8004")
HASH_DB_PATH = Path(os.environ.get("HASH_DB_PATH", "/app/volumes/data/embed_hashes.json"))

# ── Content hash dedup (prevents re-embedding identical content) ──
_embed_hashes: set[str] = set()

def _load_hashes():
    global _embed_hashes
    try:
        if HASH_DB_PATH.exists():
            _embed_hashes = set(json.loads(HASH_DB_PATH.read_text()))
            log.info("loaded_hashes count=%d", len(_embed_hashes))
    except Exception as e:
        log.warning("load_hashes_failed: %s", e)

def _save_hashes():
    try:
        HASH_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        HASH_DB_PATH.write_text(json.dumps(list(_embed_hashes)))
    except Exception as e:
        log.warning("save_hashes_failed: %s", e)

def _content_hash(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()


# ─── Metrics (in-memory, no external deps) ──────────────────

import threading
from collections import defaultdict

class Metrics:
    """Thread-safe in-memory metrics collector."""
    def __init__(self):
        self._lock = threading.Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._timers: dict[str, list] = defaultdict(list)  # last 100 values
        self._gauges: dict[str, int] = defaultdict(int)
        self._start_time = time.time()

    def incr(self, key: str, n: int = 1):
        with self._lock:
            self._counters[key] += n

    def time(self, key: str, ms: float):
        with self._lock:
            buf = self._timers[key]
            buf.append(ms)
            if len(buf) > 100:
                buf.pop(0)

    def gauge(self, key: str, value: int):
        with self._lock:
            self._gauges[key] = value

    def snapshot(self) -> dict:
        with self._lock:
            timers = {}
            for k, vals in self._timers.items():
                if vals:
                    sv = sorted(vals)
                    timers[k] = {
                        "count": len(vals),
                        "p50": sv[len(sv)//2],
                        "p95": sv[int(len(sv)*0.95)],
                        "p99": sv[int(len(sv)*0.99)],
                        "avg": sum(vals)/len(vals),
                    }
            return {
                "uptime_seconds": time.time() - self._start_time,
                "counters": dict(self._counters),
                "timers_ms": timers,
                "gauges": dict(self._gauges),
            }

metrics = Metrics()

# ─── Domain Classification ─────────────────────────────────
DOMAIN_MAP = {
    "wikipedia": "encyclopedia",
    "stackexchange": "q_and_a",
    "reddit": "social",
    "hackernews": "social_news",
    "arxiv": "academic",
    "pubmed": "academic",
    "crossref": "academic",
    "github": "code",
    "searxng": "web",
    "yacy": "web",
    "duckduckgo": "web",
    "internetarchive": "archive",
    "warehouse": "internal",
}

# ─── Models ────────────────────────────────────────────────

class SourceResult(BaseModel):
    title: str
    url: str
    description: str
    source: str
    domain: str
    confidence: float
    summary: str = ""  # auto-generated for long descriptions
    entities: list[str] = []  # extracted URLs, code blocks, headings
    # Populated only when enable_scraping=true and crawl succeeded.
    content: str = ""
    markdown: str = ""
    word_count: int = 0

class AggregateRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Research query")
    max_results: int = Field(default=10, ge=1, le=50)
    include_warehouse: bool = Field(default=True)
    reconcile: bool = Field(default=True, description="LLM-based cross-domain fact reconciliation")
    # DeepSearch pipeline extensions (unified API)
    enable_scraping: bool = Field(default=False, description="Scrape top result pages for full content")
    max_scrape_urls: int = Field(default=5, ge=1, le=20)
    enable_rag: bool = Field(default=False, description="Embed → retrieve relevant chunks via vector-store")
    rag_top_k: int = Field(default=10, ge=1, le=50)
    enable_synthesis: bool = Field(default=True, description="LLM synthesis of search context")

class ConsensusFact(BaseModel):
    claim: str
    confidence: float
    supporting_sources: List[str]
    conflicting_sources: List[str]
    quality: str = "probable"  # verified (≥0.80), probable (≥0.70), uncertain (<0.70)

class AggregateResponse(BaseModel):
    query: str
    domains_queried: List[str]
    total_sources: int
    sources: List[SourceResult]
    consensus: Optional[List[ConsensusFact]] = None
    synthesis: Optional[str] = None
    execution_time_ms: int
    # Unified DeepSearch fields
    scraped_urls: int = 0
    rag_chunks: int = 0
    answer: Optional[str] = None  # synthesized answer (alias for synthesis)

class ClientSearchRequest(BaseModel):
    query: str
    llm_provider: Optional[str] = None

class CompletionRequest(BaseModel):
    messages: List[dict]
    provider: Optional[str] = None


app = FastAPI(title="DeepSearch Web API", version="6.1.0")

# CORS middleware (audit L50): a UI on a different origin (e.g. a
# separate frontend on :3000 calling the API on :8083) needs CORS
# headers or browser fetches will fail. Origins configurable via
# CORS_ORIGINS env var (comma-separated). Defaults to * for dev.
_cors_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Shared HTTP client ─────────────────────────────────────────
# 10x perf win: every outbound call used to allocate a fresh
# httpx.AsyncClient (19 sites). Each allocation = new connection pool
# + TCP handshake per RTT. Switched to one lifespan-managed client with
# keep-alive across all upstream services. Per-call timeouts are still
# overridable via the `timeout=` kwarg on the request method.
_HTTP: Optional[httpx.AsyncClient] = None

def http() -> httpx.AsyncClient:
    if _HTTP is None:
        raise RuntimeError("shared http client not initialized")
    return _HTTP


class _TimedClient:
    """Drop-in adapter so call sites can keep their `async with _shared_client(timeout=X) as client:`
    shape while actually using the lifespan-managed shared pool. The `timeout`
    becomes the default for every request method; per-call overrides still win.
    Supports the same `.post`, `.get`, `.stream` surface the call sites use.
    """
    __slots__ = ("_t",)

    def __init__(self, timeout: Optional[float] = None):
        self._t = timeout

    async def post(self, *a, **kw):
        if self._t is not None:
            kw.setdefault("timeout", self._t)
        return await http().post(*a, **kw)

    async def get(self, *a, **kw):
        if self._t is not None:
            kw.setdefault("timeout", self._t)
        return await http().get(*a, **kw)

    def stream(self, *a, **kw):
        if self._t is not None:
            kw.setdefault("timeout", self._t)
        return http().stream(*a, **kw)


from contextlib import asynccontextmanager as _asynccontextmanager

@_asynccontextmanager
async def _shared_client(timeout: Optional[float] = None):
    """Yields a _TimedClient bound to the shared pool. No allocation, no
    connection setup — just a wrapper that lets existing `async with ... as client:`
    code keep working unchanged."""
    yield _TimedClient(timeout)


@app.on_event("startup")
async def startup():
    """Load content hash dedup set + bring up the shared http client."""
    global _HTTP
    _HTTP = httpx.AsyncClient(
        timeout=httpx.Timeout(15.0, connect=5.0),
        limits=httpx.Limits(
            max_connections=200,
            max_keepalive_connections=100,
            keepalive_expiry=30.0,
        ),
        http2=False,  # http2=True needs `h2` package; keep deps minimal
    )
    _load_hashes()
    log.info("startup_complete hashes=%d http_client=ready", len(_embed_hashes))
    # PERSISTENCE: periodic flush of embed-hash dedup set to disk so restarts
    # don't trigger full re-embed of all content. Saves every 60s; also on shutdown.
    asyncio.create_task(_periodic_save_hashes())


@app.on_event("shutdown")
async def _http_shutdown():
    global _HTTP
    if _HTTP is not None:
        await _HTTP.aclose()
        _HTTP = None
        log.info("http_client_closed")


async def _periodic_save_hashes():
    """Save _embed_hashes to disk every 60s. Cancel-safe."""
    try:
        while True:
            await asyncio.sleep(60)
            try:
                _save_hashes()
            except Exception as e:
                log.warning("periodic_save_hashes_failed: %s", e)
    except asyncio.CancelledError:
        try:
            _save_hashes()
        except Exception:
            pass
        raise


@app.on_event("shutdown")
async def shutdown():
    """Final save of embed-hash dedup set on shutdown."""
    try:
        _save_hashes()
        log.info("shutdown_saved_hashes count=%d", len(_embed_hashes))
    except Exception as e:
        log.warning("shutdown_save_hashes_failed: %s", e)


@app.post("/api/admin/save-hashes")
async def force_save_hashes():
    """Force an immediate save of the embed-hash dedup set to disk.

    Useful for tests that need to verify persistence without waiting
    for the 60s periodic save or a clean shutdown. Also exposes
    the current state for observability.
    """
    try:
        _save_hashes()
        return {"saved": True, "count": len(_embed_hashes), "path": str(HASH_DB_PATH)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/admin/hash-state")
async def get_hash_state():
    """Return the current in-memory + on-disk hash state (for tests/observability)."""
    disk = []
    try:
        if HASH_DB_PATH.exists():
            disk = json.loads(HASH_DB_PATH.read_text())
    except Exception as e:
        return {"memory_count": len(_embed_hashes), "disk_count": -1, "disk_error": str(e)}
    return {
        "memory_count": len(_embed_hashes),
        "disk_count": len(disk),
        "memory_minus_disk": list(_embed_hashes - set(disk)),
    }


# ─── Helpers ───────────────────────────────────────────────

# Provider list — every working provider, every domain.
# searxng/yacy are meta-search channels: their hits surface real source URLs
# (wikipedia, github, news, gov, etc.) which we re-attribute downstream so
# the orchestrator's "sources" reflect actual origins, not channel names.
# Override via env var AGGREGATE_PROVIDERS (comma-separated).
_DEFAULT_AGGREGATE_PROVIDERS = [
    "searxng",          # meta-search channel (Google/Bing/DDG)
    "yacy",             # meta-search channel (P2P)
    "wikipedia",        # encyclopedia
    "stackexchange",    # q_and_a (programming/eng)
    "hackernews",       # social_news (tech)
    "github",           # code repositories
    "arxiv",            # academic preprints
    "pubmed",           # biomedical literature
    "crossref",         # cross-disciplinary scholarly metadata
    "internetarchive",  # archived web
    # "reddit",        # excluded by default — needs proxy from docker net
    # "duckduckgo",    # excluded — DDG Instant Answer API is thin; searxng covers it
]

# Meta-search channels: hits already carry the real origin URL, so we
# re-attribute `source` to that URL's host instead of the channel name.
_META_SEARCH_CHANNELS = {"searxng", "yacy", "duckduckgo"}

def _resolve_aggregate_providers() -> List[str]:
    """Resolve provider list from AGGREGATE_PROVIDERS env var, falling back to defaults."""
    override = os.environ.get("AGGREGATE_PROVIDERS", "").strip()
    if not override:
        return list(_DEFAULT_AGGREGATE_PROVIDERS)
    providers = [p.strip() for p in override.split(",") if p.strip()]
    return providers or list(_DEFAULT_AGGREGATE_PROVIDERS)

_AGGREGATE_PROVIDERS = _resolve_aggregate_providers()

async def _multi_provider_search(query: str, max_results: int) -> List[dict]:
    """Query ALL search providers via search-gateway with deadline."""
    try:
        # 12s deadline - return whatever we have by then
        async with _shared_client(timeout=12.0) as client:
            resp = await client.post(
                f"{SEARCH_GATEWAY_URL}/search",
                json={
                    "query": query,
                    "providers": _AGGREGATE_PROVIDERS,
                    "max_results": max_results,
                    "timeout": 10,
                },
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        log.warning("search_gateway_failed: %s", str(e))
        return []


async def _warehouse_fetch_bodies(ids: List[int], cap_chars: int = 4000) -> dict:
    """Fetch warehouse markdown bodies for a list of row ids, in parallel.

    Returns `{id: markdown[:cap_chars]}`. Failures swallow per-id (logged)
    so a single missing row doesn't kill the synthesis pipeline.
    Used by /aggregate to lift hybrid hits from snippet → full body for
    the reconciliation prompt.
    """
    if not ids:
        return {}
    sem = asyncio.Semaphore(8)

    async def one(i: int) -> tuple[int, str]:
        async with sem:
            try:
                async with _shared_client(timeout=5.0) as client:
                    r = await client.get(f"{WAREHOUSE_URL}/content/{i}")
                    if r.status_code != 200:
                        return i, ""
                    body = (r.json().get("markdown") or "")[:cap_chars]
                    return i, body
            except Exception as e:
                log.warning("warehouse_body_fetch_failed id=%s err=%s", i, e)
                return i, ""

    pairs = await asyncio.gather(*[one(i) for i in ids])
    return {i: md for i, md in pairs if md}


async def _warehouse_search(query: str, limit: int = 10) -> List[dict]:
    """Hybrid retrieval: FTS5 + vector store fused with RRF.

    Replaces the prior FTS5-only lookup. Hits whose embedding wasn't reached
    by FTS still surface via the dense rank; exact-keyword hits the vector
    missed still surface via FTS. ~150ms typical, parallel internally.
    """
    try:
        client = http()
        # Loopback to our own /api/search/hybrid — web-api listens on 8014.
        resp = await client.get(
            "http://localhost:8014/api/search/hybrid",
            params={"q": query, "limit": limit, "fts_k": max(20, limit * 2), "vec_k": max(20, limit * 2)},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        out: List[dict] = []
        for h in data.get("hits", []):
            out.append({
                "id": h.get("id"),
                "url": h.get("url", ""),
                "title": h.get("title", ""),
                "description": h.get("snippet", "") or "",
                "source": "warehouse",
                "source_domain": h.get("source_domain"),
                "word_count": h.get("word_count", 0),
                "confidence": min(1.0, 0.5 + 5.0 * h.get("rrf_score", 0.0)),
                "fts_rank": h.get("fts_rank"),
                "vec_rank": h.get("vec_rank"),
            })
        return out
    except Exception as e:
        log.warning("warehouse_hybrid_failed: %s — falling back to FTS5", e)
        # Last-ditch fallback: raw FTS5 so the cascade keeps working if hybrid
        # blows up (e.g., vector-store cold-start).
        try:
            client = http()
            resp = await client.get(
                f"{WAREHOUSE_URL}/search",
                params={"q": query, "limit": limit},
                timeout=10.0,
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            results = resp.json() or []
            for r in results:
                r["source"] = "warehouse"
            return results
        except Exception as e2:
            log.warning("warehouse_fallback_failed: %s", e2)
            return []


async def _vector_search(query: str, limit: int = 10) -> List[dict]:
    """Semantic search via vector-store - second hop in progressive cascade."""
    try:
        async with _shared_client(timeout=5.0) as client:
            resp = await client.post(
                f"{VECTOR_STORE_URL}/query",
                json={"query_text": query, "n_results": limit},
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        ids_list = data.get("ids", [[]])[0]
        metas_list = data.get("metadatas", [[]])[0]
        docs_list = data.get("documents", [[]])[0]
        distances = data.get("distances", [[]])[0]

        for i in range(len(ids_list)):
            meta = metas_list[i] if i < len(metas_list) else {}
            doc = docs_list[i] if i < len(docs_list) else ""
            dist = distances[i] if i < len(distances) else 1.0
            url = meta.get("url", "")
            if not url:
                continue
            results.append({
                "url": url,
                "title": meta.get("title", "") or doc[:80],
                "description": doc[:300],
                "source": "vector_store",
                "confidence": max(0.3, 1.0 - dist),  # convert distance to confidence
            })
        return results
    except Exception as e:
        log.warning("vector_search_failed: %s", str(e))
        return []


def _classify_domain(source: str) -> str:
    return DOMAIN_MAP.get(source, "unknown")


# ── Boilerplate stripping (DRY: single source of truth in libs/common/text.py) ─────────

from libs.common.text import strip_boilerplate as _strip_boilerplate_unwrapped
import re as _re

def _strip_boilerplate(markdown: str) -> str:
    """Web-api wrapper: post-processes the shared strip_boilerplate to
    collapse 3+ newlines and strip leading/trailing whitespace.

    Falls back to the original markdown if stripping produced empty
    (so we never silently return nothing for a real document).
    """
    if not markdown:
        return markdown
    result = _strip_boilerplate_unwrapped(markdown)
    result = _re.sub(r'\n{3,}', '\n\n', result).strip()
    return result if result else markdown


# ── Scraping & RAG helpers ─────────────────────────────────

async def _scrape_sources(
    sources: List[SourceResult],
    session_id: Optional[str] = None,
    query: Optional[str] = None,
) -> list:
    """Scrape full content from source URLs via crawler service.

    Lineage propagation: stamps each crawler call with the aggregate's session_id
    and the originating query, so warehouse rows trace back to "which research
    session, which query found this".
    """
    sem = asyncio.Semaphore(10)  # matches crawler concurrency

    async def scrape_one(s: SourceResult):
        async with sem:
            try:
                async with _shared_client(timeout=20.0) as client:
                    resp = await client.post(
                        f"{CRAWLER_URL}/crawl",
                        json={
                            "url": s.url,
                            "extraction_strategy": "markdown",
                            "timeout": 15,
                            # ── lineage stamp (warehouse v2) ────────────
                            "seen_in_session": session_id,
                            "found_via_query": query,
                            "source_provider": s.source,
                        },
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    if data.get("success"):
                        md = data.get("markdown", "")
                        cleaned_md = _strip_boilerplate(md)
                        return {"url": s.url, "title": s.title, "markdown": cleaned_md,
                                "word_count": len(cleaned_md.split())}
            except Exception as e:
                log.warning("scrape_failed url=%s: %s", s.url, str(e))
            return None

    results = await asyncio.gather(*[scrape_one(s) for s in sources])
    return [r for r in results if r and r.get("markdown")]


async def _rag_pipeline(query: str, scraped: list, top_k: int) -> list:
    """Embed scraped content → semantic search via vector-store.
    Content hash dedup prevents re-embedding identical text."""
    try:
        # Embed documents (skip duplicates via content hash)
        docs = []
        for s in scraped:
            text = s.get("markdown", "")
            if not text:
                continue
            h = _content_hash(text)
            if h in _embed_hashes:
                continue
            _embed_hashes.add(h)
            docs.append({"text": text[:5000], "metadata": {"url": s["url"], "title": s["title"]}})
        if not docs:
            return []

        async with _shared_client(timeout=30.0) as client:
            await client.post(f"{VECTOR_STORE_URL}/embed", json={"documents": docs})
            resp = await client.post(
                f"{VECTOR_STORE_URL}/query",
                json={"query_text": query, "n_results": top_k},
            )
            resp.raise_for_status()
            data = resp.json()
            # Return documents with distances
            chunks = []
            ids_list = data.get("ids", [[]])[0]
            docs_list = data.get("documents", [[]])[0]
            metas_list = data.get("metadatas", [[]])[0]
            distances = data.get("distances", [[]])[0]
            for i in range(len(ids_list)):
                chunks.append({
                    "id": ids_list[i] if i < len(ids_list) else "",
                    "content": docs_list[i] if i < len(docs_list) else "",
                    "metadata": metas_list[i] if i < len(metas_list) else {},
                    "distance": distances[i] if i < len(distances) else 1.0,
                })
            return chunks
    except Exception as e:
        log.error("rag_failed: %s", str(e))
        return []


def _extract_domain(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url).netloc or "unknown"


def _extract_entities(text: str) -> list[str]:
    """Basic entity extraction — URLs, code blocks, headings."""
    entities = []
    # Extract URLs
    urls = re.findall(r'https?://[^\s\)]+', text)
    entities.extend(urls[:3])
    # Extract code blocks
    code_blocks = re.findall(r'```(\w+)?\n([^`]+)```', text)
    for lang, code in code_blocks[:2]:
        entities.append(f"code:{lang or 'plain'}:{code[:50].strip()}")
    # Extract markdown headings
    headings = re.findall(r'^#{1,3}\s+(.+)$', text, re.MULTILINE)
    entities.extend(h[:60] for h in headings[:5])
    return entities[:10]


# ─── Reconciliation ────────────────────────────────────────


def _build_reconciliation_prompt(query: str, sources: List[SourceResult]) -> str:
    """Build a prompt asking the LLM to reconcile facts across domains.

    Context budget: total source body text capped (env-tunable). Per
    source: prefer full markdown (from scrape or warehouse hit) up to
    per_source_cap, else fall back to the 300-char snippet. Sources are
    added until either the budget is exhausted or 15 sources are included.

    Tuning knobs (env):
      RECONCILE_PER_SOURCE_CAP   default 1200  (chars per source body)
      RECONCILE_TOTAL_BUDGET     default 6000  (total source body chars)
    Defaults sized for a free/queued reasoning model — bigger context
    causes long latency or timeouts in practice.
    """
    PER_SOURCE_CAP = int(os.environ.get("RECONCILE_PER_SOURCE_CAP", "1200"))
    TOTAL_BUDGET = int(os.environ.get("RECONCILE_TOTAL_BUDGET", "6000"))
    used = 0
    parts: list[str] = []
    for i, s in enumerate(sources[:15]):
        if s.markdown:
            body = s.markdown[:PER_SOURCE_CAP].strip()
            kind = "BODY"
        else:
            body = (s.description or "")[:300].strip()
            kind = "SNIPPET"
        parts.append(f"[{i+1}] [{s.domain}] {s.title}\n    ({kind}) {body}")
        used += len(body)
        if used >= TOTAL_BUDGET:
            break
    source_text = "\n\n".join(parts)
    return f"""You are a cross-domain fact reconciler. Analyze these sources about "{query}" and extract a consensus.

SOURCES:
{source_text}

TASK:
1. Identify facts claimed across multiple sources (with citation numbers like [1], [3])
2. Note any conflicting claims between sources
3. Rate consensus confidence (0.0-1.0) for each fact

Return JSON only:
{{
  "consensus": [
    {{"claim": "fact statement", "confidence": 0.95, "supporting_sources": ["[1]", "[3]"], "conflicting_sources": []}},
    ...
  ],
  "synthesis": "2-3 paragraph synthesis of what we know with high confidence"
}}"""


async def _llm_reconcile(query: str, sources: List[SourceResult]) -> dict:
    """Use inference-gateway to reconcile cross-domain results."""
    try:
        prompt = _build_reconciliation_prompt(query, sources)
        model = os.environ.get("RECONCILE_MODEL", "deepseek-v4-flash-free")
        max_tokens = int(os.environ.get("RECONCILE_MAX_TOKENS", "8192"))
        timeout_s = float(os.environ.get("RECONCILE_TIMEOUT_SEC", "120"))
        async with _shared_client(timeout=timeout_s) as client:
            resp = await client.post(
                f"{INFERENCE_GATEWAY_URL}/v1/chat/completions",
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": "You are a fact reconciliation engine. Return valid JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": max_tokens,
                },
            )
            resp.raise_for_status()
            result = resp.json()
            # inference-gateway wraps in raw_response.choices
            choices = result.get("raw_response", result).get("choices", [{"message": {"content": ""}}])
            content = choices[0]["message"]["content"]
            # Extract JSON from markdown code blocks if present
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]
            return json.loads(content.strip())
    except Exception as e:
        log.error("llm_reconcile_failed: %s", str(e))
        return {"consensus": [], "synthesis": None}


# ─── Hybrid search ─────────────────────────────────────────
# Reciprocal Rank Fusion: combines independent rankings (FTS5 lexical +
# vector-store dense) into one. Each ranker contributes `1 / (k + rank)` per
# document. k=60 is the canonical TREC-style constant; larger k weights
# rankers more equally, smaller k weights top hits more.

RRF_K = int(os.environ.get("RRF_K", "60"))

# Cross-encoder reranker. After RRF fusion produces a candidate list, we
# can rerank the top-N with a small CE model that scores (query, document)
# pairs directly. Published benchmarks show 30-50% MRR lift. Model is
# ms-marco-MiniLM-L-6-v2 (~80 MB), CPU-fast.
#
# Loaded lazily on first reranking request so service startup stays fast.
# Disable entirely with RERANKER_ENABLED=false; default on.

RERANKER_ENABLED = os.environ.get("RERANKER_ENABLED", "true").lower() == "true"
RERANKER_MODEL = os.environ.get("RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
RERANK_TOP_K = int(os.environ.get("RERANK_TOP_K", "20"))

_reranker = None  # lazy: CrossEncoder | None | False (init failed)


def _get_reranker():
    """Lazily load the cross-encoder. Returns the model or False if load failed."""
    global _reranker
    if _reranker is not None:
        return _reranker
    if not RERANKER_ENABLED:
        _reranker = False
        return False
    try:
        from sentence_transformers import CrossEncoder  # type: ignore
        log.info("loading_reranker model=%s", RERANKER_MODEL)
        _reranker = CrossEncoder(RERANKER_MODEL, max_length=512)
        log.info("reranker_ready")
        return _reranker
    except Exception as e:
        log.warning("reranker_load_failed: %s — falling back to RRF-only", e)
        _reranker = False
        return False


def _rerank_hits(query: str, candidates: list, content_by_id: dict[int, str]) -> list:
    """Rerank a candidate list in-place by cross-encoder score.

    Returns the candidates sorted by descending CE score. If reranker is
    disabled or unavailable, returns candidates unchanged. CE scores are
    attached as `ce_score` on each candidate dict.
    """
    rr = _get_reranker()
    if not rr:
        return candidates
    pairs = []
    keep = []
    for c in candidates[:RERANK_TOP_K]:
        text = content_by_id.get(c.id) or c.snippet or c.title or ""
        if not text:
            continue
        # CE only sees the first ~512 tokens; truncate generously at chars.
        pairs.append((query, text[:2000]))
        keep.append(c)
    if not pairs:
        return candidates
    try:
        scores = rr.predict(pairs, show_progress_bar=False, batch_size=16)
    except Exception as e:
        log.warning("rerank_predict_failed: %s", e)
        return candidates
    for c, s in zip(keep, scores):
        c.ce_score = float(s)
    # Sort the reranked subset by CE score; append the un-reranked tail.
    keep.sort(key=lambda c: -getattr(c, "ce_score", 0.0))
    tail = candidates[RERANK_TOP_K:]
    return keep + tail


class HybridHit(BaseModel):
    id: int                                 # warehouse row id
    url: str
    title: Optional[str] = None
    snippet: Optional[str] = None
    source_domain: Optional[str] = None
    word_count: int = 0
    fts_rank: Optional[int] = None          # 1-based rank in FTS5 result (None = miss)
    vec_rank: Optional[int] = None          # 1-based rank in vector result (None = miss)
    rrf_score: float = 0.0
    ce_score: Optional[float] = None        # cross-encoder score (None if not reranked)


class HybridSearchResponse(BaseModel):
    query: str
    hits: List[HybridHit]
    fts_hits: int
    vec_hits: int
    merged: int
    elapsed_ms: int


@app.get("/api/search/hybrid", response_model=HybridSearchResponse)
async def hybrid_search(
    q: str,
    limit: int = 15,
    fts_k: int = 30,
    vec_k: int = 30,
):
    """FTS5 lexical + vector dense, fused with Reciprocal Rank Fusion.

    Both halves run in parallel. Documents present in either ranking get a
    score of sum(1 / (k + rank_i)). The vector-store ids are `wh-{row_id}`
    so we can join the dense hits straight onto warehouse rows. Returns
    enriched HybridHit objects so callers can show provenance + content.
    """
    import time
    # Degenerate-query gate: FTS5 returns nothing for whitespace-only or
    # 1-char queries, but the vector store happily embeds " " and returns
    # its 30 nearest neighbors — essentially a random sample. Bail
    # early so callers can't accidentally pull "random highly-ranked rows"
    # by sending an empty query.
    if not q or len(q.strip()) < 2:
        return HybridSearchResponse(
            query=q, hits=[], fts_hits=0, vec_hits=0, merged=0, elapsed_ms=0,
        )
    t0 = time.time()
    client = http()

    async def _fts() -> list[dict]:
        try:
            r = await client.get(f"{WAREHOUSE_URL}/search", params={"q": q, "limit": fts_k}, timeout=15.0)
            r.raise_for_status()
            return r.json() or []
        except Exception as e:
            log.warning("hybrid_fts_err: %s", e)
            return []

    async def _vec() -> dict:
        try:
            r = await client.post(
                f"{VECTOR_STORE_URL}/query",
                json={"query_text": q, "n_results": vec_k, "namespace": "warehouse"},
                timeout=15.0,
            )
            r.raise_for_status()
            return r.json() or {}
        except Exception as e:
            log.warning("hybrid_vec_err: %s", e)
            return {}

    fts_rows, vec_rows = await asyncio.gather(_fts(), _vec())

    # ── Index by warehouse id ──────────────────────────────────────
    by_id: dict[int, HybridHit] = {}
    rrf: dict[int, float] = {}

    for rank, row in enumerate(fts_rows, start=1):
        wid = int(row.get("id"))
        rrf[wid] = rrf.get(wid, 0.0) + 1.0 / (RRF_K + rank)
        by_id[wid] = HybridHit(
            id=wid,
            url=row.get("url", ""),
            title=row.get("title"),
            snippet=row.get("snippet"),
            source_domain=row.get("source_domain"),
            word_count=row.get("word_count", 0),
            fts_rank=rank,
        )

    vec_ids: list = vec_rows.get("ids", [[]])[0] if isinstance(vec_rows.get("ids"), list) else []
    vec_metas: list = vec_rows.get("metadatas", [[]])[0] if isinstance(vec_rows.get("metadatas"), list) else []
    vec_docs: list = vec_rows.get("documents", [[]])[0] if isinstance(vec_rows.get("documents"), list) else []
    for rank, vid in enumerate(vec_ids, start=1):
        if not isinstance(vid, str):
            continue
        # Vector-store namespaces ids as "{namespace}:{id}" when written with a
        # namespace, so the actual id is the part after the last ':'. Then we
        # peel off the "wh-" prefix to get the warehouse row id.
        bare = vid.rsplit(":", 1)[-1]
        if not bare.startswith("wh-"):
            continue
        try:
            wid = int(bare[3:])
        except ValueError:
            continue
        rrf[wid] = rrf.get(wid, 0.0) + 1.0 / (RRF_K + rank)
        if wid in by_id:
            by_id[wid].vec_rank = rank
        else:
            meta = vec_metas[rank - 1] if rank - 1 < len(vec_metas) else {}
            doc = vec_docs[rank - 1] if rank - 1 < len(vec_docs) else ""
            by_id[wid] = HybridHit(
                id=wid,
                url=(meta or {}).get("url", ""),
                title=(meta or {}).get("title"),
                snippet=(doc or "")[:240],
                source_domain=None,
                word_count=int((meta or {}).get("word_count", 0)),
                vec_rank=rank,
            )

    # Sort by RRF score descending, keep more candidates than we'll return so
    # the reranker has room to reshuffle.
    candidate_count = max(limit, RERANK_TOP_K)
    sorted_ids = sorted(rrf.keys(), key=lambda i: -rrf[i])[:candidate_count]
    candidates = []
    for wid in sorted_ids:
        h = by_id[wid]
        h.rrf_score = round(rrf[wid], 6)
        candidates.append(h)

    # Cross-encoder rerank — fetch the body for the top candidates so the CE
    # has actual text (not just title) to score against the query.
    if candidates and RERANKER_ENABLED:
        rerank_ids = [c.id for c in candidates[:RERANK_TOP_K]]
        content_by_id: dict[int, str] = {}
        try:
            client = http()
            # Fetch top candidates' content from the warehouse in parallel.
            async def _fetch(wid: int):
                try:
                    r = await client.get(f"{WAREHOUSE_URL}/content/{wid}", timeout=5.0)
                    if r.status_code == 200:
                        data = r.json()
                        return wid, data.get("markdown") or ""
                except Exception:
                    pass
                return wid, ""
            fetches = await asyncio.gather(*[_fetch(wid) for wid in rerank_ids])
            for wid, md in fetches:
                content_by_id[wid] = md
            candidates = await asyncio.to_thread(_rerank_hits, q, candidates, content_by_id)
        except Exception as e:
            log.warning("rerank_pipeline_failed: %s", e)

    hits = candidates[:limit]

    elapsed_ms = int((time.time() - t0) * 1000)
    metrics.incr("hybrid.requests")
    metrics.time("hybrid.duration_ms", elapsed_ms)
    reranked = sum(1 for h in hits if h.ce_score is not None)
    log.info("hybrid query=%s fts=%d vec=%d merged=%d reranked=%d elapsed=%dms",
             q[:80], len(fts_rows), len(vec_ids), len(hits), reranked, elapsed_ms)
    return HybridSearchResponse(
        query=q,
        hits=hits,
        fts_hits=len(fts_rows),
        vec_hits=len(vec_ids),
        merged=len(hits),
        elapsed_ms=elapsed_ms,
    )


# ─── Endpoints ─────────────────────────────────────────────

@app.post("/api/aggregate", response_model=AggregateResponse)
async def cross_domain_aggregate(req: AggregateRequest):
    """
    Unified DeepSearch entry point - replaces deepsearch (8001) and web-api (8014).

    Flow: warehouse → external search → (optional: scrape → embed → retrieve) → reconcile
    Results cached in Redis (1h TTL).
    """
    # Check cache (only for non-scraping requests - scraped content is fresh)
    if not req.enable_scraping:
        ck = _cache_key(req.query, req.max_results, req.include_warehouse, req.reconcile)
        if cached := await _cache_get(ck):
            metrics.incr("aggregate.cache_hits")
            log.info("aggregate_cache_hit query=%s", req.query)
            return cached
        metrics.incr("aggregate.cache_misses")
    else:
        ck = None  # don't cache scraping results

    import time
    import uuid
    t0 = time.time()
    # session_id traces every artifact produced by this aggregate call back to
    # the originating research session. Propagated to scrape → warehouse.
    session_id = f"agg-{uuid.uuid4().hex[:12]}"
    metrics.incr("aggregate.requests")

    # 1. Warehouse-first search - check local FTS5 before hitting external APIs
    warehouse_results = []
    if req.include_warehouse:
        warehouse_results = await _warehouse_search(req.query, req.max_results)

    WAREHOUSE_SUFFICIENT = 5  # skip external providers if warehouse has enough

    # 2. Vector-store semantic search - second hop in the cascade
    vector_results = []
    combined_sufficient = len(warehouse_results) >= WAREHOUSE_SUFFICIENT

    if not combined_sufficient:
        vector_results = await _vector_search(req.query, req.max_results)
        combined_sufficient = (len(warehouse_results) + len(vector_results)) >= WAREHOUSE_SUFFICIENT

    if vector_results:
        metrics.incr("aggregate.vector_store_hits")

    # 3. External providers - only if local cascade is insufficient
    if combined_sufficient:
        metrics.incr("aggregate.local_cascade_hits")
        log.info("local_cascade_sufficient query=%s warehouse=%d vector=%d",
                 req.query, len(warehouse_results), len(vector_results))
        search_results = []
    else:
        metrics.incr("aggregate.external_searches")
        search_results = await _multi_provider_search(req.query, req.max_results)

    # 4. Merge + domain-tag + deduplicate (warehouse + vector + external)
    seen_urls = set()
    sources: List[SourceResult] = []

    for r in search_results + warehouse_results + vector_results:
        url = r.get("url", "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        provider = r.get("source", "unknown")

        # Re-attribute the `source` for meta-search hits: searxng/yacy/ddg
        # aggregate from real origins (wikipedia.org, nytimes.com, github.com,
        # ...). Treating "searxng" as a single source is wrong — every hit
        # has a real origin URL. We use the URL host as the source; the
        # original channel goes into `entities` for traceability.
        if provider in _META_SEARCH_CHANNELS:
            origin = _extract_domain(url) or provider
            src = origin
            # Domain class for meta-search hits is inferred from the origin
            # host (wikipedia → encyclopedia, github → code, ...).
            origin_key = origin.replace("www.", "").split(".")[0]
            classified = DOMAIN_MAP.get(origin_key, "web")
            domain = classified
        else:
            src = provider
            domain = _classify_domain(src)

        desc = r.get("description", r.get("snippet", ""))
        summary = ""
        if len(desc) > 500:
            sentences = desc.replace('\n', ' ').split('. ')
            summary = '. '.join(sentences[:2]) + '.' if len(sentences) >= 2 else desc[:300]
        entities = _extract_entities(r.get("title", "") + " " + desc)
        # Keep the channel that surfaced this hit so downstream telemetry can
        # see which gateway found it.
        if provider in _META_SEARCH_CHANNELS:
            entities.append(f"via:{provider}")

        sources.append(SourceResult(
            title=r.get("title", ""),
            url=url,
            description=desc,
            source=src,
            domain=domain,
            confidence=r.get("confidence", r.get("score", 0.5)),
            summary=summary,
            entities=entities,
        ))

    domains_queried = sorted(set(s.domain for s in sources))

    # 2.5 Optional: Scrape top results for full content
    scraped_content: list = []
    if req.enable_scraping and sources:
        t_scrape = time.monotonic()
        scraped_content = await _scrape_sources(
            sources[:req.max_scrape_urls],
            session_id=session_id,
            query=req.query,
        )
        metrics.time("scrape.duration_ms", (time.monotonic() - t_scrape) * 1000)
        metrics.incr("scrape.requests")
        metrics.incr("scrape.urls", len(scraped_content))
        log.info("scraped urls=%d for query=%s", len(scraped_content), req.query)
        # Attach scraped content back to the matching sources so callers
        # actually receive what they asked for. Without this, scraping
        # silently feeds only the RAG pipeline.
        by_url = {item["url"]: item for item in scraped_content}
        for s in sources:
            hit = by_url.get(s.url)
            if hit:
                md = hit.get("markdown") or ""
                s.markdown = md
                s.content = md
                s.word_count = hit.get("word_count") or len(md.split())

    # 2.6 Optional: Embed → Retrieve via vector-store
    rag_chunks: list = []
    if req.enable_rag and scraped_content:
        t_rag = time.monotonic()
        rag_chunks = await _rag_pipeline(req.query, scraped_content, req.rag_top_k)
        metrics.time("rag.duration_ms", (time.monotonic() - t_rag) * 1000)
        metrics.incr("rag.requests")
        metrics.incr("rag.chunks_retrieved", len(rag_chunks))
        log.info("rag chunks=%d for query=%s", len(rag_chunks), req.query)

    # 2.7 Warehouse-hit body hydration. Top warehouse hits arrive with
    # only a snippet (FTS5 highlight). When synthesis is going to run, fetch
    # the full markdown so the LLM gets the actual archived page text — turns
    # every prior crawl into compounding context for future answers.
    if req.enable_synthesis and req.reconcile and warehouse_results:
        wh_ids = [r["id"] for r in warehouse_results[:8] if r.get("id")]
        # Skip sources we already filled via scraping above (avoid double cost).
        wh_ids = [i for i, r in zip(wh_ids, warehouse_results[:8])
                  if not any(s.url == r["url"] and s.markdown for s in sources)]
        bodies = await _warehouse_fetch_bodies(wh_ids, cap_chars=2500)
        if bodies:
            url_to_md = {r["url"]: bodies.get(r["id"], "")
                         for r in warehouse_results if r.get("id") in bodies}
            for s in sources:
                if not s.markdown and url_to_md.get(s.url):
                    s.markdown = url_to_md[s.url]
            log.info("warehouse_bodies_loaded count=%d query=%s",
                     len(bodies), req.query)

    # 3. Cross-domain reconciliation via LLM
    consensus = None
    synthesis = None
    if req.reconcile and len(sources) >= 2:
        t_rec = time.monotonic()
        reconciliation = await _llm_reconcile(req.query, sources)
        metrics.time("reconcile.duration_ms", (time.monotonic() - t_rec) * 1000)
        metrics.incr("reconcile.requests")
        consensus_raw = reconciliation.get("consensus", [])
        consensus = [
            ConsensusFact(
                claim=f["claim"],
                confidence=f["confidence"],
                supporting_sources=f.get("supporting_sources", []),
                conflicting_sources=f.get("conflicting_sources", []),
                quality="verified" if f["confidence"] >= 0.80 else ("probable" if f["confidence"] >= 0.70 else "uncertain"),
            )
            for f in consensus_raw
            if f.get("claim")  # skip empty claims
        ]
        synthesis = reconciliation.get("synthesis")

    elapsed_ms = int((time.time() - t0) * 1000)
    metrics.time("aggregate.duration_ms", elapsed_ms)

    log.info("aggregate query=%s domains=%d sources=%d consensus=%d time=%dms",
             req.query, len(domains_queried), len(sources),
             len(consensus) if consensus else 0, elapsed_ms)

    response = AggregateResponse(
        query=req.query,
        domains_queried=domains_queried,
        total_sources=len(sources),
        sources=sources,
        consensus=consensus,
        synthesis=synthesis,
        answer=synthesis,  # unified field
        execution_time_ms=elapsed_ms,
        scraped_urls=len(scraped_content),
        rag_chunks=len(rag_chunks),
    )

    # Cache the result (fire-and-forget). Warehouse persistence is the
    # crawler's job — it forwards every successful /crawl to the warehouse
    # via FORWARD_TO_WAREHOUSE. web-api stays out of the persistence path.
    # Skip the cache when the caller asked for synthesis and we returned
    # nothing — almost always a transient LLM timeout; we'd rather pay the
    # next call than poison the cache with a null answer.
    expected_synth = req.enable_synthesis and req.reconcile
    if not (expected_synth and not synthesis):
        asyncio.create_task(_cache_set(ck, response.model_dump()))
    else:
        log.info("skip_cache_empty_synthesis query=%s", req.query)

    return response


@app.post("/api/aggregate/stream")
async def aggregate_stream(req: AggregateRequest):
    """Streaming aggregate — warehouse results first, then external.
    Returns SSE events: warehouse, vector, external, complete."""
    async def event_stream():
        t0 = time.time()
        metrics.incr("aggregate.requests")
        
        # 1. Warehouse — send immediately
        t_wh = time.time()
        wh = []
        if req.include_warehouse:
            wh = await _warehouse_search(req.query, req.max_results)
        wh_sources = [{"title":r.get("title",""),"url":r.get("url",""),
            "description":r.get("snippet","")[:500],"source":"warehouse",
            "domain":r.get("source_domain",""),"confidence":0.9} for r in wh]
        yield f"data: {json.dumps({'type':'warehouse','sources':wh_sources,'count':len(wh),'time_ms':int((time.time()-t_wh)*1000)})}\n\n"
        
        # 2. External (only if needed)
        if len(wh) < 3:
            ext = await _search_external(req.query, req.max_results)
            ext_src = [{"title":r.get("title",""),"url":r.get("url",""),
                "description":r.get("snippet","")[:500],"source":r.get("source",""),
                "domain":r.get("source_domain",""),"confidence":r.get("score",0.5)} for r in ext]
            yield f"data: {json.dumps({'type':'external','sources':ext_src,'count':len(ext),'time_ms':int((time.time()-t_wh)*1000)})}\n\n"
        
        # 3. Complete
        elapsed = int((time.time()-t0)*1000)
        yield f"data: {json.dumps({'type':'complete','total_sources':len(wh),'time_ms':elapsed})}\n\n"
    
    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/search/stream")
async def stream_search(request: ClientSearchRequest):
    """Search → synthesize (streaming)."""
    async def _stream():
        # 1. Search
        try:
            async with _shared_client(timeout=30.0) as client:
                resp = await client.post(
                    f"{SEARCH_GATEWAY_URL}/search",
                    json={
                        "query": request.query,
                        "providers": _AGGREGATE_PROVIDERS,
                        "max_results": 10,
                        "timeout": 10,
                    },
                )
                resp.raise_for_status()
                sources = resp.json()
        except Exception as e:
            log.error("search_failed: %s", str(e))
            yield f"data: {json.dumps({'content': 'Search failed.', 'finished': True, 'sources': []})}\n\n"
            return

        # 2. Synthesize via search-agent
        try:
            async with _shared_client(timeout=180.0) as client:
                async with client.stream(
                    "POST",
                    f"{SEARCH_AGENT_URL}/synthesize/stream",
                    json={
                        "query": request.query,
                        "llm_provider": request.llm_provider,
                        "sources": sources,
                    },
                ) as agent_resp:
                    agent_resp.raise_for_status()
                    async for chunk in agent_resp.aiter_bytes():
                        yield chunk.decode()
        except Exception as e:
            log.error("synthesis_failed: %s", str(e))
            yield f"data: {json.dumps({'content': 'Synthesis failed.', 'finished': True, 'sources': sources})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@app.post("/api/completion/stream")
async def stream_completion(request: CompletionRequest):
    """Direct LLM completion proxy."""
    async def _stream():
        try:
            async with _shared_client(timeout=180.0) as client:
                async with client.stream(
                    "POST",
                    f"{INFERENCE_GATEWAY_URL}/v1/chat/completions",
                    json={
                        "model": "deepseek-chat",
                        "messages": request.messages,
                        "stream": True,
                    },
                ) as resp:
                    resp.raise_for_status()
                    async for chunk in resp.aiter_bytes():
                        yield chunk.decode()
        except Exception as e:
            log.error("completion_stream_failed: %s", str(e))
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream")


@app.get("/api/providers")
async def get_providers():
    """Available LLM providers."""
    try:
        async with _shared_client(timeout=10.0) as client:
            resp = await client.get(f"{INFERENCE_GATEWAY_URL}/v1/models")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        log.error("providers_failed: %s", str(e))
        raise HTTPException(status_code=503, detail="Inference gateway unavailable")


@app.get("/health")
async def health():
    """Health + dependency status."""
    deps = {}
    for name, url in [
        ("search_agent", f"{SEARCH_AGENT_URL}/health"),
        ("search_gateway", f"{SEARCH_GATEWAY_URL}/health"),
        ("inference_gateway", f"{INFERENCE_GATEWAY_URL}/health"),
        ("warehouse", f"{WAREHOUSE_URL}/health"),
    ]:
        try:
            async with _shared_client(timeout=5.0) as client:
                r = await client.get(url)
                deps[name] = "ok" if r.status_code == 200 else "degraded"
        except Exception:
            deps[name] = "unreachable"

    all_ok = all(v == "ok" for v in deps.values())
    return {"status": "ok" if all_ok else "degraded", "dependencies": deps}


@app.get("/api/metrics")
async def get_metrics():
    """Service metrics - request counts, latencies, cache/warehouse hit rates."""
    snap = metrics.snapshot()
    # Add derived metrics
    total = snap["counters"].get("aggregate.requests", 0)
    cache_hits = snap["counters"].get("aggregate.cache_hits", 0)
    wh_hits = snap["counters"].get("aggregate.warehouse_hits", 0)
    snap["derived"] = {
        "cache_hit_rate": round(cache_hits / total, 3) if total > 0 else 0,
        "local_cascade_rate": round(snap["counters"].get("aggregate.local_cascade_hits", 0) / total, 3) if total > 0 else 0,
        "external_search_rate": round(snap["counters"].get("aggregate.external_searches", 0) / total, 3) if total > 0 else 0,
        "vector_store_rate": round(snap["counters"].get("aggregate.vector_store_hits", 0) / total, 3) if total > 0 else 0,
    }
    return snap


@app.get("/ui")
async def ui():
    """Serve the web frontend."""
    ui_path = Path(__file__).parent / "app" / "static" / "index.html"
    if not ui_path.exists():
        raise HTTPException(status_code=404, detail="UI not built")
    return FileResponse(ui_path, media_type="text/html")


@app.get("/")
async def root():
    return {
        "service": "DeepSearch Web API Orchestrator",
        "endpoints": ["/api/aggregate", "/api/search/stream", "/api/completion/stream", "/api/providers", "/api/ingest/urls"],
    }


# ─── Provisioning: Bulk URL Ingestion ──────────────────────────────────────

class IngestURLsRequest(BaseModel):
    urls: List[str] = Field(..., min_items=1, max_items=100, description="URLs to crawl and store")
    extraction_strategy: str = Field(default="markdown", pattern="^(markdown|text)$")
    timeout: int = Field(default=20, ge=5, le=60)
    bypass_cache: bool = False

class IngestURLsResponse(BaseModel):
    urls_submitted: int
    success_count: int
    failure_count: int
    cache_hits: int
    total_duration_ms: float
    warehouse_entries_after: int


@app.get("/api/warehouse/list")
async def warehouse_list_proxy(
    sort: str = "ingested_at", order: str = "desc",
    domain: str = None, min_words: int = None, max_words: int = None,
    offset: int = 0, limit: int = 30,
):
    """Proxy warehouse paginated list with sort/filter."""
    params = {"sort": sort, "order": order, "offset": offset, "limit": min(limit, 100)}
    if domain: params["domain"] = domain
    if min_words is not None: params["min_words"] = min_words
    if max_words is not None: params["max_words"] = max_words
    try:
        async with _shared_client(timeout=10.0) as client:
            resp = await client.get(f"{WAREHOUSE_URL}/list", params=params)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        log.warning("warehouse_list_proxy_failed: %s", e)
        return []


@app.get("/api/warehouse/stats")
async def warehouse_stats_proxy():
    """Proxy warehouse stats through web-api."""
    try:
        async with _shared_client(timeout=10.0) as client:
            resp = await client.get(f"{WAREHOUSE_URL}/stats")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        log.warning("warehouse_stats_proxy_failed: %s", e)
        return {"total_entries": 0, "db_size_mb": 0}


@app.get("/api/warehouse/search")
async def warehouse_search_proxy(q: str, limit: int = 30):
    """Proxy warehouse FTS5 search through web-api."""
    try:
        async with _shared_client(timeout=10.0) as client:
            resp = await client.get(f"{WAREHOUSE_URL}/search", params={"q": q, "limit": min(limit, 100)})
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        log.warning("warehouse_search_proxy_failed: %s", e)
        return []


@app.get("/api/warehouse/content/{content_id}")
async def warehouse_content_proxy(content_id: int):
    """Proxy warehouse content fetch through web-api."""
    try:
        async with _shared_client(timeout=10.0) as client:
            resp = await client.get(f"{WAREHOUSE_URL}/content/{content_id}")
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        log.warning("warehouse_content_proxy_failed: %s", e)
        raise HTTPException(status_code=404, detail="Content not found")


@app.post("/api/ingest/urls", response_model=IngestURLsResponse)
async def ingest_urls(req: IngestURLsRequest):
    """Bulk URL ingestion - crawl + warehouse store.

    Accepts up to 100 URLs. Crawls in parallel via crawler service,
    results automatically forwarded to knowledge warehouse.
    Returns crawl stats and updated warehouse entry count.
    """
    # Validate and dedup URLs
    urls = list(dict.fromkeys(u.strip() for u in req.urls if u.strip().startswith("http")))
    if not urls:
        raise HTTPException(status_code=400, detail="No valid HTTP URLs provided")

    log.info("ingest_urls submitting=%d urls", len(urls))

    try:
        async with _shared_client(timeout=req.timeout + 30) as client:
            resp = await client.post(
                f"{CRAWLER_URL}/crawl/batch",
                json={
                    "urls": urls,
                    "extraction_strategy": req.extraction_strategy,
                    "timeout": req.timeout,
                    "bypass_cache": req.bypass_cache,
                },
            )
            resp.raise_for_status()
            batch_result = resp.json()
    except Exception as e:
        log.error("ingest_urls_crawl_failed: %s", str(e))
        raise HTTPException(status_code=502, detail=f"Crawler service failed: {str(e)}")

    # Get current warehouse stats
    warehouse_entries = 0
    try:
        async with _shared_client(timeout=5.0) as client:
            wh_resp = await client.get(f"{WAREHOUSE_URL}/stats")
            wh_resp.raise_for_status()
            warehouse_entries = wh_resp.json().get("total_entries", 0)
    except Exception:
        pass

    return IngestURLsResponse(
        urls_submitted=len(urls),
        success_count=batch_result.get("success_count", 0),
        failure_count=batch_result.get("failure_count", 0),
        cache_hits=batch_result.get("cache_hits", 0),
        total_duration_ms=batch_result.get("total_duration_ms", 0),
        warehouse_entries_after=warehouse_entries,
    )


class IngestFeedRequest(BaseModel):
    feed_url: str = Field(..., min_length=1, description="RSS/Atom feed URL")
    max_items: int = Field(default=20, ge=1, le=100)
    timeout: int = Field(default=20, ge=5, le=60)

class IngestFeedResponse(BaseModel):
    feed_url: str
    feed_title: str = ""
    items_found: int = 0
    urls_extracted: int = 0
    queued_for_crawl: int = 0


@app.post("/api/ingest/feed", response_model=IngestFeedResponse)
async def ingest_feed(req: IngestFeedRequest):
    """Ingest an RSS/Atom feed - extract links, queue for crawling."""
    import xml.etree.ElementTree as ET

    # Fetch feed
    try:
        async with _shared_client(timeout=req.timeout) as client:
            resp = await client.get(
                req.feed_url,
                headers={"User-Agent": "DeepSearchStack/1.0 (feed reader)"},
            )
            resp.raise_for_status()
            xml_text = resp.text
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Feed fetch failed: {str(e)}")

    # Parse feed (RSS or Atom)
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        raise HTTPException(status_code=400, detail=f"Invalid XML: {str(e)}")

    # Extract feed title
    feed_title = ""
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    # RSS 2.0
    channel = root.find("channel")
    if channel is not None:
        feed_title = (channel.findtext("title") or "").strip()
        items = channel.findall("item")
        links = []
        for item in items[:req.max_items]:
            link = item.findtext("link")
            if link:
                links.append(link.strip())
    else:
        # Atom feed
        feed_title = (root.findtext("atom:title", namespaces=ns) or root.findtext("title") or "").strip()
        entries = root.findall("atom:entry", ns) or root.findall("entry")
        links = []
        for entry in entries[:req.max_items]:
            link_el = entry.find("atom:link", ns) or entry.find("link")
            if link_el is not None:
                href = link_el.get("href") or link_el.text
                if href:
                    links.append(href.strip())

    if not links:
        return IngestFeedResponse(
            feed_url=req.feed_url, feed_title=feed_title,
            items_found=0, urls_extracted=0, queued_for_crawl=0,
        )

    # Queue for crawling (fire-and-forget to not block)
    asyncio.create_task(_crawl_feed_links(links))

    log.info("feed_ingested url=%s title=%s links=%d", req.feed_url, feed_title, len(links))
    return IngestFeedResponse(
        feed_url=req.feed_url, feed_title=feed_title,
        items_found=len(links), urls_extracted=len(links),
        queued_for_crawl=len(links),
    )


async def _crawl_feed_links(links: list[str]):
    """Background: crawl feed links in batches."""
    batch_size = 10
    for i in range(0, len(links), batch_size):
        batch = links[i:i + batch_size]
        try:
            async with _shared_client(timeout=60.0) as client:
                await client.post(
                    f"{CRAWLER_URL}/crawl/batch",
                    json={"urls": batch, "timeout": 20},
                )
            log.info("feed_crawl_batch done=%d/%d", min(i + batch_size, len(links)), len(links))
        except Exception as e:
            log.warning("feed_crawl_batch_failed: %s", str(e))
        await asyncio.sleep(2)  # gentle pacing
