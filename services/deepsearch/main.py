"""
DeepSearch Service — DEPRECATED. Proxies to web-api:8014.
Session management preserved.
"""
import os
import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from models import (
    DeepSearchRequest, DeepSearchResponse, QuickSearchRequest,
    RecursiveResearchRequest,
    SessionCreate, SessionListResponse, HealthCheck, ServiceMetrics,
    SessionMessage, StreamChunk
)
from config import config
from core.engine import DeepSearchEngine
from storage.sessions import SessionStorage

# Logging configuration
logging.basicConfig(
    level=getattr(logging, config.get("service.log_level", "INFO")),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("deepsearch")

# Global instances
engine: DeepSearchEngine = None
storage: SessionStorage = None
start_time: float = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global engine, storage, start_time
    
    logger.info("🚀 DeepSearch service starting...")
    start_time = time.time()
    
    # Initialize engine (always works, no dependencies)
    engine = DeepSearchEngine()
    await engine.initialize()
    logger.info("✓ DeepSearch engine initialized")
    
    # Initialize session storage (best-effort, don't crash if DB unavailable)
    if config.session_config.get("enabled", True):
        try:
            storage = SessionStorage()
            await storage.initialize()
            logger.info("✓ Session storage initialized")
        except Exception as e:
            logger.warning(f"⚠ Session storage unavailable (degraded mode): {e}")
            storage = None
    
    logger.info("✓ DeepSearch service ready")
    
    yield
    
    # Cleanup
    logger.info("Shutting down DeepSearch service...")
    await engine.shutdown()
    if storage:
        await storage.shutdown()
    logger.info("Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title=config.get("service.name", "DeepSearch"),
    version=config.get("service.version", "2.0.0"),
    description="DeepSearch — DEPRECATED. Use web-api:8014/api/aggregate instead.",
    lifespan=lifespan
)

# Web-API URL for proxying
WEB_API_URL = os.environ.get("WEB_API_URL", "http://web-api:8014")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Core DeepSearch Endpoints — DEPRECATED (proxied to web-api aggregate)
# ============================================================================

@app.post("/deepsearch", response_class=StreamingResponse)
async def deepsearch_endpoint(request: DeepSearchRequest):
    """DEPRECATED: proxied to web-api /api/search/stream."""
    return await _proxy_stream(
        f"{WEB_API_URL}/api/search/stream",
        {"query": request.query, "llm_provider": request.llm_provider},
    )


@app.post("/deepsearch/quick")
async def quick_search(request: QuickSearchRequest):
    """DEPRECATED: proxied to web-api /api/aggregate (non-streaming)."""
    return await _proxy_json(
        f"{WEB_API_URL}/api/aggregate",
        {
            "query": request.query,
            "max_results": request.max_results,
            "reconcile": True,
            "include_warehouse": True,
        },
    )


@app.post("/deepsearch/research")
async def recursive_research(request: RecursiveResearchRequest):
    """DEPRECATED: proxied to web-api /api/aggregate with scraping+RAG."""
    if request.stream:
        return await _proxy_stream(
            f"{WEB_API_URL}/api/search/stream",
            {"query": request.query, "llm_provider": getattr(request, 'llm_provider', None)},
        )
    return await _proxy_json(
        f"{WEB_API_URL}/api/aggregate",
        {
            "query": request.query,
            "max_results": request.max_results_per_iter or 10,
            "reconcile": True,
            "include_warehouse": True,
            "enable_scraping": True,
            "max_scrape_urls": min(request.max_scrape_per_iter or 5, 10),
            "enable_rag": True,
        },
    )


# ── Proxy helpers ──────────────────────────────────────────────

async def _proxy_stream(target_url: str, payload: dict):
    """Stream proxy to web-api."""
    import httpx
    async def generator():
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                async with client.stream("POST", target_url, json=payload) as resp:
                    async for chunk in resp.aiter_bytes():
                        yield chunk.decode()
        except Exception as e:
            logger.error(f"Proxy stream error: {e}")
            yield f"data: {{\"error\": \"{str(e)}\"}}\n\n"
    return StreamingResponse(generator(), media_type="text/event-stream")


async def _proxy_json(target_url: str, payload: dict):
    """JSON proxy to web-api."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(target_url, json=payload)
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        logger.error(f"Proxy error: {e}")
        raise HTTPException(status_code=502, detail=f"Web-API proxy failed: {str(e)}")


# ============================================================================
# Session Management Endpoints
# ============================================================================

@app.post("/sessions", response_model=SessionCreate)
async def create_session(create_req: SessionCreate):
    """Create a new conversation session"""
    if not storage:
        raise HTTPException(status_code=503, detail="Session storage not enabled")
    
    session = await storage.create_session(create_req)
    return session


@app.get("/sessions/{session_id}")
async def get_session(session_id: str):
    """Retrieve a session by ID"""
    if not storage:
        raise HTTPException(status_code=503, detail="Session storage not enabled")
    
    session = await storage.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return session


@app.get("/sessions", response_model=SessionListResponse)
async def list_sessions(limit: int = 50, offset: int = 0):
    """List all sessions"""
    if not storage:
        raise HTTPException(status_code=503, detail="Session storage not enabled")
    
    sessions = await storage.list_sessions(limit, offset)
    return SessionListResponse(
        sessions=sessions,
        total=len(sessions)
    )


@app.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """Delete a session"""
    if not storage:
        raise HTTPException(status_code=503, detail="Session storage not enabled")
    
    success = await storage.delete_session(session_id)
    if not success:
        raise HTTPException(status_code=404, detail="Session not found")
    
    return {"message": "Session deleted"}


# ============================================================================
# Health & Monitoring Endpoints
# ============================================================================

@app.get("/health", response_model=HealthCheck)
async def health_check():
    """Service health check"""
    uptime = time.time() - start_time if start_time else 0
    
    # Check dependencies
    dependencies = {
        "search_gateway": True,  # TODO: actual health checks
        "inference_gateway": True,
        "vector_store": config.rag_config.get("enabled", True),
        "crawler": config.scraping_config.get("enabled", True),
    }
    
    # Determine overall status
    all_healthy = all(dependencies.values())
    status = "healthy" if all_healthy else "degraded"
    
    return HealthCheck(
        status=status,
        version=config.get("service.version", "1.0.0"),
        uptime=uptime,
        dependencies=dependencies,
        cache_enabled=config.cache_config.get("enabled", True),
        rag_enabled=config.rag_config.get("enabled", True)
    )


@app.get("/config")
async def get_config():
    """Get current configuration (sanitized)"""
    return {
        "search": config.search_config,
        "scraping": config.scraping_config,
        "rag": config.rag_config,
        "synthesis": {
            "model": config.synthesis_config.get("model"),
            "streaming": config.synthesis_config.get("streaming"),
            "temperature": config.synthesis_config.get("temperature"),
        },
        "cache": config.cache_config,
        "sessions": {
            "enabled": config.session_config.get("enabled"),
            "storage": config.session_config.get("storage"),
        }
    }


@app.get("/")
async def root():
    """API information"""
    return {
        "service": config.get("service.name", "DeepSearch"),
        "version": config.get("service.version", "1.0.0"),
        "description": "Powerful AI search with scraping, RAG, and synthesis",
        "endpoints": {
            "POST /deepsearch": "Full pipeline with streaming",
            "POST /deepsearch/quick": "Quick non-streaming search",
            "POST /sessions": "Create session",
            "GET /sessions/{id}": "Get session",
            "GET /sessions": "List sessions",
            "GET /health": "Health check",
            "GET /config": "Current configuration"
        },
        "documentation": "/docs"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=config.get("service.host", "0.0.0.0"),
        port=config.get("service.port", 8001),
        log_level=config.get("service.log_level", "info").lower()
    )
