"""Blog Generator — Substrate service for AI-powered blog post generation.

Endpoints:
  POST /generate              — Generate a blog post on a given topic
  POST /generate-researched   — Research via DSS, then generate
  POST /generate/from-warehouse — Auto-discover topic from warehouse, generate
  GET  /topics                — Discover potential topics from warehouse
  GET  /history               — List past generations with token/cost tracking
  GET  /stats                 — Aggregate usage statistics
  GET  /health                — Health check
"""

import os
import httpx
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field

from app.logger import init_logging, new_request_id, RequestLogger
from app.tracker import init_db, get_stats, get_history
from app.generator import generate_blog_post, generate_researched_blog

init_logging(os.getenv("LOG_LEVEL", "INFO"))
init_db()

log = logging.getLogger("blog_generator")

WAREHOUSE_URL = os.environ.get("WAREHOUSE_URL", "http://dss-knowledge-warehouse:8009")


# ─── Models ──────────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    topic: str = Field(..., min_length=3, max_length=500, description="Blog post topic or title")
    model: str = Field(default="deepseek-chat", description="Model to use for generation")
    style: str = Field(default="technical", description="Writing style: technical, tutorial, thought")
    max_tokens: int = Field(default=2048, ge=256, le=8192)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    context: str = Field(default="", description="Research context to enrich generation")


class GenerateResponse(BaseModel):
    id: str
    topic: str
    model: str
    content: str
    sources: list[dict] = []
    usage: dict
    cost_usd: float
    duration_ms: int


class StatsResponse(BaseModel):
    total_generations: int
    total_tokens: int
    total_cost_usd: float
    avg_duration_ms: float


class HistoryEntry(BaseModel):
    id: str
    topic: str
    model: str
    status: str
    total_tokens: int
    cost_usd: float
    duration_ms: int
    created_at: str


class TopicDiscovery(BaseModel):
    topics: list[dict]


# ─── App ─────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("blog_generator starting...")
    yield
    log.info("blog_generator shutting down...")


app = FastAPI(
    title="Substrate Blog Generator",
    version="0.2.0",
    lifespan=lifespan,
)


# ─── Middleware: request ID injection ────────────────────────────────────────

@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    rid = request.headers.get("X-Request-ID", new_request_id())
    request.state.rid = rid
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    return response


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    stats = get_stats()
    return {"status": "ok", "generations": stats["total_generations"]}


@app.post("/generate", response_model=GenerateResponse)
async def generate(req: GenerateRequest, request: Request):
    rid = getattr(request.state, "rid", new_request_id())
    rlog = RequestLogger(log, rid)
    rlog.info(f"Generate request: topic={req.topic[:80]} model={req.model} style={req.style}")

    try:
        result = await generate_blog_post(
            topic=req.topic, model=req.model, style=req.style,
            max_tokens=req.max_tokens, temperature=req.temperature,
            context=req.context, rid=rid,
        )
        return GenerateResponse(**result)
    except Exception as e:
        rlog.error(f"Generation failed: {e}")
        raise HTTPException(status_code=502, detail=f"Generation failed: {str(e)}")


@app.post("/generate-researched", response_model=GenerateResponse)
async def generate_researched(req: GenerateRequest, request: Request):
    """Research a topic via DeepSearch, then generate a blog post with real sources."""
    rid = getattr(request.state, "rid", new_request_id())
    rlog = RequestLogger(log, rid)
    rlog.info(f"Researched generate request: topic={req.topic[:80]}")

    try:
        result = await generate_researched_blog(
            topic=req.topic, model=req.model, style=req.style,
            max_tokens=req.max_tokens, temperature=req.temperature, rid=rid,
        )
        return GenerateResponse(**result)
    except Exception as e:
        rlog.error(f"Researched generation failed: {e}")
        raise HTTPException(status_code=502, detail=f"Researched generation failed: {str(e)}")


@app.post("/generate/from-warehouse", response_model=GenerateResponse)
async def generate_from_warehouse(request: Request):
    """Auto-discover topic from warehouse, generate a blog post."""
    rid = getattr(request.state, "rid", new_request_id())
    rlog = RequestLogger(log, rid)

    try:
        # Pull newest warehouse entries for topic ideas
        async with httpx.AsyncClient(timeout=15.0) as client:
            topics_resp = await client.get(
                f"{WAREHOUSE_URL}/list",
                params={"sort": "ingested_at", "order": "desc", "limit": 5, "min_words": 500},
            )
            topics_resp.raise_for_status()
            top_entries = topics_resp.json()

            if not top_entries:
                raise HTTPException(status_code=404, detail="No warehouse content found")

            entry = top_entries[0]
            topic = entry["title"][:200]
            rlog.info(f"warehouse_topic: {topic[:80]}")

            # Fetch context from warehouse
            wh_search = await client.get(
                f"{WAREHOUSE_URL}/search", params={"q": topic, "limit": 5}
            )
            wh_search.raise_for_status()
            related = wh_search.json()
            context = "\n".join(
                f"- {r.get('title','')} ({r.get('source_domain','')}): {r.get('snippet','')[:300]}"
                for r in related
            )

        result = await generate_blog_post(
            topic=topic, context=context, rid=rid,
            max_tokens=2048, temperature=0.7, style="technical",
        )
        return GenerateResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        rlog.error(f"warehouse_generation_failed: {e}")
        raise HTTPException(status_code=502, detail=f"Generation failed: {str(e)}")


@app.get("/topics", response_model=TopicDiscovery)
async def discover_topics(min_words: int = 500, limit: int = 10):
    """Discover potential blog topics from warehouse content."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{WAREHOUSE_URL}/list",
                params={"sort": "word_count", "order": "desc", "limit": limit, "min_words": min_words},
            )
            resp.raise_for_status()
            entries = resp.json()
            topics = [
                {"title": e["title"], "domain": e.get("source_domain", ""),
                 "words": e["word_count"], "id": e["id"]}
                for e in entries
            ]
            return TopicDiscovery(topics=topics)
    except Exception as e:
        log.warning(f"topic_discovery_failed: {e}")
        return TopicDiscovery(topics=[])


@app.get("/stats", response_model=StatsResponse)
async def stats():
    s = get_stats()
    return StatsResponse(
        total_generations=s["total_generations"],
        total_tokens=s["total_tokens"],
        total_cost_usd=s["total_cost_usd"],
        avg_duration_ms=s["avg_duration_ms"],
    )


@app.get("/history", response_model=list[HistoryEntry])
async def history(limit: int = 20, offset: int = 0):
    rows = get_history(limit=limit, offset=offset)
    return [HistoryEntry(
        id=r["id"], topic=r["topic"], model=r["model"],
        status=r["status"], total_tokens=r["total_tokens"],
        cost_usd=r["cost_usd"], duration_ms=r["duration_ms"],
        created_at=r["created_at"],
    ) for r in rows]


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    import uvicorn
    port = int(os.getenv("BLOG_GENERATOR_PORT", "8006"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
