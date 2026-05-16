"""
web-api — DeepSearch Cross-Domain Aggregation Orchestrator

Endpoints:
  POST /api/search/stream     — search → synthesize (streaming)
  POST /api/aggregate         — cross-domain aggregation with source-of-truth extraction
  POST /api/completion/stream — direct LLM completion proxy
  GET  /api/providers         — list available LLM providers
  GET  /health                — health + dependency status
"""

import asyncio
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import List, Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

# Redis cache — optional, fails open if unreachable
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
        log.warning("Redis unavailable — caching disabled: %s", e)
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

class AggregateRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Research query")
    max_results: int = Field(default=10, ge=1, le=50)
    include_warehouse: bool = Field(default=True)
    reconcile: bool = Field(default=True, description="LLM-based cross-domain fact reconciliation")

class ConsensusFact(BaseModel):
    claim: str
    confidence: float
    supporting_sources: List[str]  # source names
    conflicting_sources: List[str]

class AggregateResponse(BaseModel):
    query: str
    domains_queried: List[str]
    total_sources: int
    sources: List[SourceResult]
    consensus: Optional[List[ConsensusFact]] = None
    synthesis: Optional[str] = None
    execution_time_ms: int

class ClientSearchRequest(BaseModel):
    query: str
    llm_provider: Optional[str] = None

class CompletionRequest(BaseModel):
    messages: List[dict]
    provider: Optional[str] = None


app = FastAPI(title="DeepSearch Web API", version="6.0.0")


# ─── Helpers ───────────────────────────────────────────────

# Provider list — 7 verified-working, non-redundant providers across 7 domains.
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
        # 12s deadline — return whatever we have by then
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


def _classify_domain(source: str) -> str:
    return DOMAIN_MAP.get(source, "unknown")


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
    Cross-domain aggregation — queries all search providers + warehouse,
    domain-tags results, optionally reconciles via LLM for source-of-truth extraction.
    Results cached in Redis (1h TTL, keyed by query+params hash).
    """
    # Check cache first
    ck = _cache_key(req.query, req.max_results, req.include_warehouse, req.reconcile)
    if cached := await _cache_get(ck):
        log.info("aggregate_cache_hit query=%s", req.query)
        return cached

    import time
    t0 = time.time()

    # 1. Warehouse-first search — check local FTS5 before hitting external APIs
    warehouse_results = []
    if req.include_warehouse:
        warehouse_results = await _warehouse_search(req.query, req.max_results)
    
    WAREHOUSE_SUFFICIENT = 5  # skip external providers if warehouse has enough
    if len(warehouse_results) >= WAREHOUSE_SUFFICIENT:
        log.info("warehouse_sufficient query=%s results=%d — skipping external providers",
                 req.query, len(warehouse_results))
        search_results = []
    else:
        search_results = await _multi_provider_search(req.query, req.max_results)

    # 2. Merge + domain-tag + deduplicate
    seen_urls = set()
    sources: List[SourceResult] = []

    for r in search_results + warehouse_results:
        url = r.get("url", "")
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        src = r.get("source", "unknown")
        sources.append(SourceResult(
            title=r.get("title", ""),
            url=url,
            description=r.get("description", r.get("snippet", "")),
            source=src,
            domain=_classify_domain(src),
            confidence=r.get("confidence", r.get("score", 0.5)),
        ))

    domains_queried = sorted(set(s.domain for s in sources))

    # 3. Cross-domain reconciliation via LLM
    consensus = None
    synthesis = None
    if req.reconcile and len(sources) >= 2:
        reconciliation = await _llm_reconcile(req.query, sources)
        consensus_raw = reconciliation.get("consensus", [])
        consensus = [
            ConsensusFact(
                claim=f["claim"],
                confidence=f["confidence"],
                supporting_sources=f.get("supporting_sources", []),
                conflicting_sources=f.get("conflicting_sources", []),
            )
            for f in consensus_raw
        ]
        synthesis = reconciliation.get("synthesis")

    elapsed_ms = int((time.time() - t0) * 1000)

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
        execution_time_ms=elapsed_ms,
    )

    # Cache the result (fire-and-forget)
    asyncio.create_task(_cache_set(ck, response.model_dump()))

    return response


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


@app.get("/")
async def root():
    return {
        "service": "DeepSearch Web API Orchestrator",
        "endpoints": ["/api/aggregate", "/api/search/stream", "/api/completion/stream", "/api/providers"],
    }
