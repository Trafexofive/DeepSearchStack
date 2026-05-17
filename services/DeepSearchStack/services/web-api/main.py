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
FACT_DB_PATH = Path(os.environ.get("FACT_DB_PATH", "/app/volumes/data/facts.json"))
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


# ── Consensus Fact Database ─────────────────────────────────────
# Stores high-confidence (verified) facts for instant lookup.
# Checked before running the full search pipeline.

_fact_db: list[dict] = []

def _load_facts():
    global _fact_db
    try:
        if FACT_DB_PATH.exists():
            _fact_db = json.loads(FACT_DB_PATH.read_text())
            log.info("loaded_facts count=%d", len(_fact_db))
    except Exception as e:
        log.warning("load_facts_failed: %s", e)
        _fact_db = []

def _save_facts():
    try:
        FACT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        FACT_DB_PATH.write_text(json.dumps(_fact_db, indent=2))
    except Exception as e:
        log.warning("save_facts_failed: %s", e)

def _store_verified_facts(facts: list[dict]):
    """Store verified consensus facts (confidence ≥ 0.80) in fact DB."""
    for f in facts:
        if f.get("quality") != "verified":
            continue
        claim = f.get("claim", "").strip()
        if not claim:
            continue
        # Check if this claim is already stored
        existing = any(c.get("claim") == claim for c in _fact_db)
        if not existing:
            _fact_db.append({
                "claim": claim,
                "confidence": f.get("confidence", 0),
                "sources": f.get("supporting_sources", []),
                "stored_at": datetime.fromtimestamp(time.time(), tz=timezone.utc).isoformat(),
            })
    if _fact_db:
        _save_facts()

def _query_facts(query: str, limit: int = 5) -> list[dict]:
    """Simple keyword match against stored facts."""
    query_lower = query.lower()
    words = query_lower.split()
    scored = []
    for f in _fact_db:
        claim_lower = f["claim"].lower()
        score = sum(1 for w in words if w in claim_lower)
        if score > 0:
            scored.append((score, f))
    scored.sort(key=lambda x: -x[0])
    return [f for _, f in scored[:limit]]

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
    "whoogle": "web",
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
    fact_db_hit: bool = False  # returned from consensus fact cache
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


@app.on_event("startup")
async def startup():
    """Load content hash dedup set and consensus fact database."""
    _load_hashes()
    _load_facts()
    log.info("startup_complete hashes=%d facts=%d", len(_embed_hashes), len(_fact_db))


# ─── Helpers ───────────────────────────────────────────────

# Provider list - 7 verified-working, non-redundant providers across 7 domains.
# Redundant providers removed: whoogle/duckduckgo (SearXNG covers Google+Bing+DDG),
#   pubmed/crossref/internetarchive (lower priority, keep domain count lean).
# IP-blocked from Docker: reddit (needs proxy).
_AGGREGATE_PROVIDERS = [
    "searxng",         # web (multi-engine: Google, Bing, DDG, etc.)
    "wikipedia",       # encyclopedia
    "stackexchange",    # q_and_a
    "hackernews",       # social_news
    "github",           # code
    "arxiv",            # academic
    "yacy",             # web (P2P, complementary results)
]

async def _multi_provider_search(query: str, max_results: int) -> List[dict]:
    """Query ALL search providers via search-gateway with deadline."""
    try:
        # 12s deadline - return whatever we have by then
        async with httpx.AsyncClient(timeout=12.0) as client:
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


async def _warehouse_search(query: str, limit: int = 10) -> List[dict]:
    """Search knowledge warehouse for existing stored content."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{WAREHOUSE_URL}/search",
                params={"q": query, "limit": limit},
            )
            if resp.status_code == 404:
                return []
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", []) if isinstance(data, dict) else data
            for r in results:
                r["source"] = "warehouse"
            return results
    except Exception as e:
        log.warning("warehouse_search_failed: %s", str(e))
        return []


async def _vector_search(query: str, limit: int = 10) -> List[dict]:
    """Semantic search via vector-store - second hop in progressive cascade."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
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


# ── Boilerplate stripping (ported from deepsearch/core/scraper.py) ─────────

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
    ]
]
_BOILERPLATE_SECTIONS = [
    'see also', 'references', 'external links', 'further reading',
    'notes', 'footnotes', 'citations', 'bibliography', 'navigation menu',
]

def _strip_boilerplate(markdown: str) -> str:
    """Strip nav chrome, sidebars, footers from crawled markdown."""
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


# ── Scraping & RAG helpers ─────────────────────────────────

async def _scrape_sources(sources: List[SourceResult]) -> list:
    """Scrape full content from source URLs via crawler service."""
    sem = asyncio.Semaphore(10)  # matches crawler concurrency

    async def scrape_one(s: SourceResult):
        async with sem:
            try:
                async with httpx.AsyncClient(timeout=20.0) as client:
                    resp = await client.post(
                        f"{CRAWLER_URL}/crawl",
                        json={"url": s.url, "extraction_strategy": "markdown", "timeout": 15},
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

        async with httpx.AsyncClient(timeout=30.0) as client:
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


async def _seed_warehouse(sources: List[SourceResult]):
    """Fire-and-forget: seed warehouse with search result metadata.
    
    Every search enriches the warehouse for future instant retrieval.
    Uses snippet as lightweight markdown — full content comes from crawler later.
    Only seeds quality snippets (≥50 chars, not just dots/punctuation).
    """
    seeded = 0
    for s in sources[:20]:  # top 20 only
        if not s.url or not s.description:
            continue
        desc = s.description.strip()
        # Quality gate: skip garbage snippets
        if len(desc) < 50:
            continue
        # Skip snippets that are just dots/ellipsis/punctuation
        alpha_chars = sum(1 for c in desc if c.isalpha())
        if alpha_chars < 20:
            continue
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{WAREHOUSE_URL}/ingest",
                    json={
                        "url": s.url,
                        "markdown": desc[:1000],
                        "title": s.title,
                        "source_domain": _extract_domain(s.url),
                        "word_count": len(desc.split()),
                        "tags": ["search_seed", s.domain],
                    },
                )
                if resp.status_code == 200 and resp.json().get("ingested"):
                    seeded += 1
        except Exception:
            pass
    if seeded:
        log.info("warehouse_seeded sources=%d", seeded)


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
    """Build a prompt asking the LLM to reconcile facts across domains."""
    source_text = "\n\n".join(
        f"[{i+1}] [{s.domain}] {s.title}\n    {s.description[:300]}"
        for i, s in enumerate(sources[:15])
    )
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
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{INFERENCE_GATEWAY_URL}/v1/chat/completions",
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": "You are a fact reconciliation engine. Return valid JSON only."},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.1,
                    "max_tokens": 2048,
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
    t0 = time.time()
    metrics.incr("aggregate.requests")

    # 0. Consensus fact database lookup — instant cached facts
    fact_results = _query_facts(req.query, limit=3)
    if fact_results and not req.enable_scraping:
        elapsed_ms = int((time.time() - t0) * 1000)
        metrics.incr("aggregate.fact_db_hits")
        log.info("aggregate_fact_hit query=%s facts=%d time=%dms", req.query, len(fact_results), elapsed_ms)
        return AggregateResponse(
            query=req.query,
            total_sources=len(fact_results),
            sources=[],
            domains_queried=[],
            consensus=[ConsensusFact(
                claim=f["claim"], confidence=f.get("confidence", 1.0),
                supporting_sources=f.get("sources", []), conflicting_sources=[],
                quality="verified",
            ) for f in fact_results],
            synthesis=None,
            execution_time_ms=elapsed_ms,
            fact_db_hit=True,
        )

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
        src = r.get("source", "unknown")
        desc = r.get("description", r.get("snippet", ""))
        # Auto-summarize long descriptions
        summary = ""
        if len(desc) > 500:
            sentences = desc.replace('\n', ' ').split('. ')
            summary = '. '.join(sentences[:2]) + '.' if len(sentences) >= 2 else desc[:300]
        # Basic entity extraction
        entities = _extract_entities(r.get("title", "") + " " + desc)
        sources.append(SourceResult(
            title=r.get("title", ""),
            url=url,
            description=desc,
            source=src,
            domain=_classify_domain(src),
            confidence=r.get("confidence", r.get("score", 0.5)),
            summary=summary,
            entities=entities,
        ))

    domains_queried = sorted(set(s.domain for s in sources))

    # 2.5 Optional: Scrape top results for full content
    scraped_content: list = []
    if req.enable_scraping and sources:
        t_scrape = time.monotonic()
        scraped_content = await _scrape_sources(sources[:req.max_scrape_urls])
        metrics.time("scrape.duration_ms", (time.monotonic() - t_scrape) * 1000)
        metrics.incr("scrape.requests")
        metrics.incr("scrape.urls", len(scraped_content))
        log.info("scraped urls=%d for query=%s", len(scraped_content), req.query)

    # 2.6 Optional: Embed → Retrieve via vector-store
    rag_chunks: list = []
    if req.enable_rag and scraped_content:
        t_rag = time.monotonic()
        rag_chunks = await _rag_pipeline(req.query, scraped_content, req.rag_top_k)
        metrics.time("rag.duration_ms", (time.monotonic() - t_rag) * 1000)
        metrics.incr("rag.requests")
        metrics.incr("rag.chunks_retrieved", len(rag_chunks))
        log.info("rag chunks=%d for query=%s", len(rag_chunks), req.query)

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
        # Store verified facts in persistent fact database
        if consensus:
            _store_verified_facts([c.dict() for c in consensus])

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

    # Cache the result (fire-and-forget)
    asyncio.create_task(_cache_set(ck, response.model_dump()))

    # Seed warehouse with search result metadata (fire-and-forget)
    asyncio.create_task(_seed_warehouse(sources))

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
            async with httpx.AsyncClient(timeout=30.0) as client:
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
            async with httpx.AsyncClient(timeout=180.0) as client:
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
            async with httpx.AsyncClient(timeout=180.0) as client:
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
        async with httpx.AsyncClient(timeout=10.0) as client:
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
            async with httpx.AsyncClient(timeout=5.0) as client:
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


@app.get("/api/facts")
async def get_facts(q: str = ""):
    """Query the consensus fact database."""
    if q:
        return {"facts": _query_facts(q, limit=10), "total": len(_fact_db)}
    return {"facts": _fact_db[-50:], "total": len(_fact_db)}


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
        async with httpx.AsyncClient(timeout=10.0) as client:
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
        async with httpx.AsyncClient(timeout=10.0) as client:
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
        async with httpx.AsyncClient(timeout=10.0) as client:
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
        async with httpx.AsyncClient(timeout=10.0) as client:
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
        async with httpx.AsyncClient(timeout=req.timeout + 30) as client:
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
        async with httpx.AsyncClient(timeout=5.0) as client:
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
        async with httpx.AsyncClient(timeout=req.timeout) as client:
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
            async with httpx.AsyncClient(timeout=60.0) as client:
                await client.post(
                    f"{CRAWLER_URL}/crawl/batch",
                    json={"urls": batch, "timeout": 20},
                )
            log.info("feed_crawl_batch done=%d/%d", min(i + batch_size, len(links)), len(links))
        except Exception as e:
            log.warning("feed_crawl_batch_failed: %s", str(e))
        await asyncio.sleep(2)  # gentle pacing
