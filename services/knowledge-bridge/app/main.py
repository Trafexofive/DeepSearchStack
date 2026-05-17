"""
knowledge-bridge — bridges DeepSearchStack research pipeline → blog_generator.

Endpoints:
  POST /bridge/research        — topic → research context + sources + key findings
  POST /bridge/generate        — topic + context → enriched blog generation
  POST /bridge/crawl-and-bridge — URL → crawl → research → generate (one-shot)
  GET  /bridge/status          — health + recent bridges + cache stats
"""

import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [bridge] %(message)s",
)
log = logging.getLogger("bridge")

DEEPSEARCH_URL = os.environ.get("DEEPSEARCH_URL", "http://dss-deepsearch:8001")
WEB_API_URL = os.environ.get("WEB_API_URL", "http://dss-web-api:8014")
WAREHOUSE_URL = os.environ.get("WAREHOUSE_URL", "http://dss-knowledge-warehouse:8009")
CRAWLER_URL = os.environ.get("CRAWLER_URL", "http://dss-crawler:8000")
BLOG_GENERATOR_URL = os.environ.get("BLOG_GENERATOR_URL", "http://blog_generator:8006")

app = FastAPI(title="knowledge-bridge", version="1.0.0")

http_client: Optional[httpx.AsyncClient] = None

# ─── Stats ────────────────────────────────────────────────
bridge_stats = {
    "research_calls": 0,
    "generate_calls": 0,
    "crawl_bridge_calls": 0,
    "errors": 0,
    "last_bridge": None,
    "uptime": None,
}

# ─── Models ───────────────────────────────────────────────

class ResearchRequest(BaseModel):
    topic: str = Field(..., min_length=1, description="Research topic")
    max_sources: int = Field(default=5, ge=1, le=20)
    include_warehouse: bool = Field(default=True)

class ResearchResponse(BaseModel):
    topic: str
    summary: str
    sources: list[dict]
    key_findings: list[str]
    context_blob: str

class GenerateRequest(BaseModel):
    topic: str
    research_id: Optional[str] = None
    context_blob: Optional[str] = None
    tone: str = Field(default="technical", pattern="^(technical|professional|conversational|tutorial)$")

class GenerateResponse(BaseModel):
    topic: str
    content: str
    sources: list[dict]
    model: str
    cost_usd: float

class CrawlBridgeRequest(BaseModel):
    url: str
    topic: Optional[str] = None
    tone: str = "technical"

class StatusResponse(BaseModel):
    status: str
    uptime: str
    calls: dict

# ─── Lifecycle ────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    global http_client
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))
    bridge_stats["uptime"] = datetime.now(timezone.utc).isoformat()
    log.info("bridge_started: deepsearch=%s warehouse=%s crawler=%s blog=%s",
             DEEPSEARCH_URL, WAREHOUSE_URL, CRAWLER_URL, BLOG_GENERATOR_URL)

@app.on_event("shutdown")
async def shutdown():
    if http_client:
        await http_client.aclose()

# ─── Helpers ──────────────────────────────────────────────

async def _research_deepsearch(topic: str, max_sources: int) -> dict:
    """Call dss-deepsearch for real-time research."""
    resp = await http_client.post(
        f"{DEEPSEARCH_URL}/deepsearch/quick",
        json={"query": topic, "max_results": max_sources},
    )
    resp.raise_for_status()
    return resp.json()

async def _search_warehouse(query: str, limit: int = 5) -> list[dict]:
    """Search knowledge warehouse for existing content on topic."""
    try:
        resp = await http_client.get(
            f"{WAREHOUSE_URL}/search",
            params={"q": query, "limit": limit},
        )
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
        return data.get("results", [])
    except httpx.HTTPStatusError as e:
        log.warning("warehouse_search_http_error: %s", str(e))
        return []
    except httpx.RequestError as e:
        log.warning("warehouse_search_unreachable: %s", str(e))
        return []

async def _crawl_url(url: str) -> dict:
    """Crawl a URL via dss-crawler."""
    resp = await http_client.post(
        f"{CRAWLER_URL}/crawl",
        json={"url": url},
    )
    resp.raise_for_status()
    return resp.json()

async def _generate_blog(topic: str, context: str, tone: str) -> dict:
    """Call blog_generator with enriched context."""
    prompt = (
        f"Topic: {topic}\n\n"
        f"Research context:\n{context}\n\n"
        f"Using the research above, write a {tone} blog post on this topic."
    )
    resp = await http_client.post(
        f"{BLOG_GENERATOR_URL}/generate",
        json={"topic": topic, "context": context, "style": tone},
    )
    resp.raise_for_status()
    return resp.json()

def _synthesize_context(topic: str, research: dict, warehouse_results: list[dict]) -> str:
    """Build a research context blob from all sources."""
    parts = [f"Research on: {topic}\n"]

    if research.get("summary"):
        parts.append(f"## Research Summary\n{research['summary']}\n")

    if research.get("sources"):
        parts.append("## Sources")
        for src in research["sources"][:5]:
            title = src.get("title", src.get("url", "unknown"))
            parts.append(f"- {title}")

    if warehouse_results:
        parts.append("\n## Existing Knowledge")
        for r in warehouse_results[:3]:
            parts.append(f"- {r.get('title', 'unknown')}")

    if research.get("key_findings"):
        parts.append("\n## Key Findings")
        for f in research["key_findings"][:5]:
            parts.append(f"- {f}")

    return "\n".join(parts)

# ─── Endpoints ────────────────────────────────────────────

@app.post("/bridge/research", response_model=ResearchResponse)
async def bridge_research(req: ResearchRequest):
    """Research a topic via deepsearch + warehouse, return synthesized context."""
    bridge_stats["research_calls"] += 1
    bridge_stats["last_bridge"] = datetime.now(timezone.utc).isoformat()
    log.info("research topic=%s", req.topic)

    try:
        research_task = _research_deepsearch(req.topic, req.max_sources)
        warehouse_task = _search_warehouse(req.topic) if req.include_warehouse else asyncio.sleep(0)

        research_result, warehouse_result = await asyncio.gather(
            research_task, warehouse_task, return_exceptions=True,
        )

        if isinstance(research_result, Exception):
            log.warning("deepsearch_failed: %s", str(research_result))
            research_result = {"summary": "", "sources": [], "key_findings": []}
        if isinstance(warehouse_result, Exception):
            log.warning("warehouse_failed: %s", str(warehouse_result))
            warehouse_result = []

        context_blob = _synthesize_context(req.topic, research_result, warehouse_result)

        return ResearchResponse(
            topic=req.topic,
            summary=research_result.get("summary", ""),
            sources=research_result.get("sources", []),
            key_findings=research_result.get("key_findings", []),
            context_blob=context_blob,
        )

    except Exception as e:
        bridge_stats["errors"] += 1
        log.error("research_failed topic=%s error=%s", req.topic, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/bridge/generate", response_model=GenerateResponse)
async def bridge_generate(req: GenerateRequest):
    """Generate a blog post using optionally pre-researched context."""
    bridge_stats["generate_calls"] += 1
    bridge_stats["last_bridge"] = datetime.now(timezone.utc).isoformat()
    log.info("generate topic=%s tone=%s", req.topic, req.tone)

    try:
        if not req.context_blob:
            research = await _research_deepsearch(req.topic, 3)
            context_blob = _synthesize_context(req.topic, research, [])
        else:
            context_blob = req.context_blob

        result = await _generate_blog(req.topic, context_blob, req.tone)

        return GenerateResponse(
            topic=req.topic,
            content=result.get("content", ""),
            sources=result.get("sources", []),
            model=result.get("model", "unknown"),
            cost_usd=result.get("cost_usd", 0),
        )

    except Exception as e:
        bridge_stats["errors"] += 1
        log.error("generate_failed topic=%s error=%s", req.topic, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/bridge/crawl-and-bridge")
async def crawl_and_bridge(req: CrawlBridgeRequest):
    """Crawl a URL, research the topic, generate a blog post — one shot."""
    bridge_stats["crawl_bridge_calls"] += 1
    bridge_stats["last_bridge"] = datetime.now(timezone.utc).isoformat()
    topic = req.topic or f"Analysis of {req.url}"
    log.info("crawl_and_bridge url=%s topic=%s", req.url, topic)

    try:
        crawl_result = await _crawl_url(req.url)
        content = crawl_result.get("content", "") or crawl_result.get("markdown", "")

        enhance = ""
        if content:
            enhance = f"\n\nSource content (from {req.url}):\n{content[:8000]}"

        context_blob = f"Topic: {topic}\n\nResearched from: {req.url}{enhance}"

        generate_result = await _generate_blog(topic, context_blob, req.tone)

        return {
            "topic": topic,
            "source_url": req.url,
            "content_sources": [
                {"url": req.url, "chars_crawled": len(content)},
            ],
            "content": generate_result.get("content", ""),
            "model": generate_result.get("model", "unknown"),
            "cost_usd": generate_result.get("cost_usd", 0),
        }

    except Exception as e:
        bridge_stats["errors"] += 1
        log.error("crawl_and_bridge_failed url=%s error=%s", req.url, str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/bridge/status")
async def status():
    uptime = ""
    if bridge_stats["uptime"]:
        start = datetime.fromisoformat(bridge_stats["uptime"])
        elapsed = datetime.now(timezone.utc) - start
        uptime = f"{elapsed.days}d {elapsed.seconds // 3600}h"

    return StatusResponse(
        status="ok",
        uptime=uptime,
        calls={
            "research": bridge_stats["research_calls"],
            "generate": bridge_stats["generate_calls"],
            "crawl_and_bridge": bridge_stats["crawl_bridge_calls"],
            "errors": bridge_stats["errors"],
        },
    )


@app.get("/health")
async def health():
    deps_ok = True
    deps = {}
    for name, url in [
        ("web_api", WEB_API_URL),
        ("warehouse", WAREHOUSE_URL),
        ("blog_generator", BLOG_GENERATOR_URL),
    ]:
        try:
            r = await http_client.get(f"{url}/health", timeout=3.0)
            deps[name] = "ok" if r.status_code == 200 else "degraded"
        except Exception:
            deps[name] = "unreachable"
            deps_ok = False
    return {"status": "ok" if deps_ok else "degraded", "dependencies": deps}


# ─── Main ─────────────────────────────────────────────────

def main():
    import uvicorn
    port = int(os.environ.get("BRIDGE_PORT", "8010"))
    uvicorn.run(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
