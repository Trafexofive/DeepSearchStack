"""
DeepSearch Service - Main API
Powerful, configurable search → scrape → RAG → synthesis endpoint
"""
import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from models import (
    DeepSearchRequest, DeepSearchResponse, QuickSearchRequest,
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
    
    # Initialize engine
    engine = DeepSearchEngine()
    await engine.initialize()
    logger.info("✓ DeepSearch engine initialized")
    
    # Initialize storage
    if config.session_config.get("enabled", True):
        storage = SessionStorage()
        await storage.initialize()
        logger.info("✓ Session storage initialized")
    
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
    version=config.get("service.version", "1.0.0"),
    description="Powerful AI search engine with scraping, RAG, and synthesis",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================================
# Core DeepSearch Endpoints
# ============================================================================

@app.post("/deepsearch", response_class=StreamingResponse)
async def deepsearch_endpoint(request: DeepSearchRequest):
    """
    Main DeepSearch endpoint - Execute full search pipeline with streaming
    
    Pipeline: Search → Scrape → Embed → Retrieve → Synthesize
    
    Returns streaming response with:
    - Progress updates
    - Synthesized content chunks
    - Sources and metadata
    """
    async def stream_response():
        """Stream DeepSearch results"""
        try:
            # Add to session if enabled
            if request.session_id and storage:
                user_message = SessionMessage(
                    role="user",
                    content=request.query
                )
                await storage.add_message(request.session_id, user_message)
            
            # Execute pipeline
            async for chunk in engine.deep_search(request):
                # Yield SSE format
                yield f"data: {chunk.json()}\n\n"
                
                # Save assistant response to session
                if request.session_id and storage and chunk.type == "complete":
                    assistant_message = SessionMessage(
                        role="assistant",
                        content=chunk.data.get("answer", ""),
                        metadata=chunk.data
                    )
                    await storage.add_message(request.session_id, assistant_message)
        
        except Exception as e:
            logger.error(f"DeepSearch error: {e}", exc_info=True)
            error_chunk = StreamChunk(
                type="error",
                data={"message": str(e)}
            )
            yield f"data: {error_chunk.json()}\n\n"
    
    return StreamingResponse(
        stream_response(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.post("/deepsearch/quick")
async def quick_search(request: QuickSearchRequest):
    """
    Quick search endpoint - Non-streaming, simplified response
    Good for CLI tools and scripts
    """
    full_request = DeepSearchRequest(
        query=request.query,
        max_results=request.max_results,
        stream=False,
        session_id=request.session_id
    )
    
    # Collect all chunks
    answer_parts = []
    final_data = None
    
    async for chunk in engine.deep_search(full_request):
        if chunk.type == "content":
            answer_parts.append(chunk.data.get("content", ""))
        elif chunk.type == "complete":
            final_data = chunk.data
    
    if final_data:
        return final_data
    else:
        raise HTTPException(status_code=500, detail="Search failed")


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
        "llm_gateway": True,
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
            "default_provider": config.synthesis_config.get("default_provider"),
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
