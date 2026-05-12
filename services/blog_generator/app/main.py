"""Blog Generator — Substrate service for AI-powered blog post generation.

Endpoints:
  POST /generate     — Generate a blog post on a given topic
  GET  /history      — List past generations with token/cost tracking
  GET  /stats        — Aggregate usage statistics
  GET  /health       — Health check
"""

import os
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


# ─── Models ──────────────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    topic: str = Field(..., min_length=3, max_length=500, description="Blog post topic or title")
    model: str = Field(default="deepseek-chat", description="Model to use for generation")
    style: str = Field(default="technical", description="Writing style: technical, tutorial, thought")
    max_tokens: int = Field(default=2048, ge=256, le=8192)
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)


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


# ─── App ─────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("blog_generator starting...")
    yield
    log.info("blog_generator shutting down...")


app = FastAPI(
    title="Substrate Blog Generator",
    version="0.1.0",
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
            topic=req.topic,
            model=req.model,
            style=req.style,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
            rid=rid,
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
    rlog.info(f"Researched generate request: topic={req.topic[:80]} model={req.model} style={req.style}")

    try:
        result = await generate_researched_blog(
            topic=req.topic,
            model=req.model,
            style=req.style,
            max_tokens=req.max_tokens,
            temperature=req.temperature,
            rid=rid,
        )
        return GenerateResponse(**result)
    except Exception as e:
        rlog.error(f"Researched generation failed: {e}")
        raise HTTPException(status_code=502, detail=f"Researched generation failed: {str(e)}")


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
