"""
Enhanced LLM API Gateway - Production-Ready Multi-Provider Gateway
"""
import os
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import Dict, List, Optional, Any
import json

from fastapi import FastAPI, HTTPException, Depends, Request, Response
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .provider_base import LLMProvider
from .providers.gemini_provider import GeminiProvider
from .providers.groq_provider import GroqProvider
from .providers.ollama_provider import OllamaProvider
from .providers.github_models_provider import GitHubModelsProvider

from .models.requests import CompletionRequest, RoutingStrategy
from .models.responses import CompletionResponse, HealthResponse, ProviderStatus, MetricsResponse, ErrorResponse

from .services.provider_manager import ProviderManager
from .services.metrics_service import MetricsService
from .services.rate_limiter import RateLimiter

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("llm_gateway_enhanced")

# Global services
provider_manager: Optional[ProviderManager] = None
metrics_service: Optional[MetricsService] = None
rate_limiter: Optional[RateLimiter] = None
security = HTTPBearer(auto_error=False)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global provider_manager, metrics_service, rate_limiter
    
    logger.info("🚀 Starting Enhanced LLM Gateway...")
    
    try:
        # Initialize services
        metrics_service = MetricsService()
        rate_limiter = RateLimiter()
        provider_manager = ProviderManager(metrics_service)
        
        # Register providers based on environment
        await _initialize_providers()
        
        # Start services
        await metrics_service.start()
        await provider_manager.start()
        
        logger.info("✅ Enhanced LLM Gateway started successfully")
        
        yield
        
    finally:
        logger.info("🛑 Shutting down Enhanced LLM Gateway...")
        
        # Cleanup services
        if provider_manager:
            await provider_manager.stop()
        if metrics_service:
            await metrics_service.stop()
            
        logger.info("✅ Enhanced LLM Gateway stopped")

async def _initialize_providers():
    """Initialize providers based on environment configuration"""
    logger.info("Initializing providers based on environment flags...")
    
    # Gemini
    if os.getenv('ENABLE_GEMINI', 'false').lower() == 'true' and os.getenv("GEMINI_API_KEY"):
        provider_manager.register_provider("gemini", GeminiProvider())
        logger.info("✅ Gemini provider registered")
    
    # Groq
    if os.getenv('ENABLE_GROQ', 'false').lower() == 'true' and os.getenv("GROQ_API_KEY"):
        provider_manager.register_provider("groq", GroqProvider())
        logger.info("✅ Groq provider registered")
    
    # GitHub Models
    if os.getenv('ENABLE_GITHUB_MODELS', 'false').lower() == 'true' and os.getenv("GITHUB_TOKEN"):
        provider_manager.register_provider("github_models", GitHubModelsProvider())
        logger.info("✅ GitHub Models provider registered")
    
    # Ollama (always enabled)
    provider_manager.register_provider("ollama", OllamaProvider())
    logger.info("✅ Ollama provider registered")
    
    logger.info(f"Provider initialization complete. Active providers: {list(provider_manager.providers.keys())}")

# Create FastAPI app
app = FastAPI(
    title="Enhanced LLM Gateway",
    description="Production-ready multi-provider LLM gateway with advanced routing, monitoring, and reliability features",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency injection
def get_provider_manager() -> ProviderManager:
    if provider_manager is None:
        raise HTTPException(status_code=503, detail="Provider manager not initialized")
    return provider_manager

def get_metrics_service() -> MetricsService:
    if metrics_service is None:
        raise HTTPException(status_code=503, detail="Metrics service not initialized")
    return metrics_service

def get_rate_limiter() -> RateLimiter:
    if rate_limiter is None:
        raise HTTPException(status_code=503, detail="Rate limiter not initialized")
    return rate_limiter

# Authentication middleware
async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Optional[str]:
    """Extract user from authentication token"""
    if credentials:
        # Simple token validation (implement proper JWT validation in production)
        token = credentials.credentials
        # For now, just use token as user ID
        return token
    return "anonymous"

# Rate limiting middleware
async def check_rate_limit(request: Request, 
                          user_id: str = Depends(get_current_user),
                          limiter: RateLimiter = Depends(get_rate_limiter)):
    """Check rate limits for the request"""
    client_ip = request.client.host
    
    # Apply rate limits
    if not await limiter.is_allowed(user_id or client_ip):
        metrics_service.record_rate_limit_hit()
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded",
            headers={"Retry-After": "60"}
        )

# Exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler"""
    request_id = getattr(request.state, 'request_id', str(uuid.uuid4()))
    logger.error(f"Request {request_id} failed: {exc}", exc_info=True)
    
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="internal_error",
            message="An internal error occurred",
            request_id=request_id
        ).dict()
    )

# Middleware for request tracking
@app.middleware("http")
async def request_tracking_middleware(request: Request, call_next):
    """Add request tracking and timing"""
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    
    # Add headers
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Process-Time"] = str(process_time)
    
    return response

# Routes
@app.get("/", tags=["Gateway"])
async def root():
    """Root endpoint with basic info"""
    return {
        "service": "Enhanced LLM Gateway",
        "version": "2.0.0",
        "status": "operational",
        "docs": "/docs",
        "health": "/health"
    }

@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check(pm: ProviderManager = Depends(get_provider_manager),
                      ms: MetricsService = Depends(get_metrics_service)):
    """Comprehensive health check"""
    # Get provider statuses
    provider_statuses = {}
    for name in pm.providers.keys():
        try:
            provider_statuses[name] = await pm.get_provider_status(name)
        except Exception as e:
            logger.error(f"Health check failed for {name}: {e}")
            provider_statuses[name] = ProviderStatus(
                available=False,
                healthy=False,
                last_error=str(e)
            )
    
    # Get gateway stats
    gateway_stats = ms.get_gateway_stats(window_minutes=5)
    
    return HealthResponse(
        status="healthy" if any(p.available for p in provider_statuses.values()) else "degraded",
        version="2.0.0",
        uptime_seconds=gateway_stats['uptime_seconds'],
        active_providers=[name for name, status in provider_statuses.items() if status.available],
        total_requests=gateway_stats['total_requests'],
        providers=provider_statuses
    )

@app.get("/providers", tags=["Providers"])
async def list_providers(pm: ProviderManager = Depends(get_provider_manager)):
    """List all providers and their status"""
    provider_statuses = {}
    for name in pm.providers.keys():
        try:
            provider_statuses[name] = await pm.get_provider_status(name)
        except Exception as e:
            provider_statuses[name] = ProviderStatus(
                available=False,
                healthy=False,
                last_error=str(e)
            )
    
    return provider_statuses

@app.post("/v1/chat/completions", response_model=CompletionResponse, tags=["Completions"])
@app.post("/completion", response_model=CompletionResponse, tags=["Completions"])
async def get_completion(
    request: CompletionRequest,
    http_request: Request,
    user_id: str = Depends(get_current_user),
    pm: ProviderManager = Depends(get_provider_manager),
    ms: MetricsService = Depends(get_metrics_service),
    _: None = Depends(check_rate_limit)
):
    """Get completion from LLM providers with advanced routing"""
    
    request_id = http_request.state.request_id
    start_time = time.time()
    
    try:
        # Select provider based on strategy
        selected_provider = await pm.select_provider(
            strategy=request.routing_strategy,
            preferred_provider=request.provider
        )
        
        if not selected_provider:
            raise HTTPException(
                status_code=503,
                detail="No providers available"
            )
        
        # Add request metadata
        request.request_id = request_id
        if user_id:
            request.user_id = user_id
        
        # Handle streaming
        if request.stream:
            return StreamingResponse(
                _stream_completion(pm, request, selected_provider, ms, start_time),
                media_type="text/event-stream",
                headers={"X-Selected-Provider": selected_provider}
            )
        
        # Execute completion
        response = await pm.execute_completion(
            selected_provider,
            request,
            fallback=request.fallback
        )
        
        # Record metrics
        elapsed = time.time() - start_time
        await ms.record_request(
            provider=selected_provider,
            response_time=elapsed,
            success=True,
            tokens_used=response.usage.total_tokens if response.usage else None,
            model=response.model
        )
        
        # Add metadata
        response.request_id = request_id
        response.response_time = elapsed
        
        return response
        
    except HTTPException:
        raise
    except Exception as e:
        # Record failure
        elapsed = time.time() - start_time
        if 'selected_provider' in locals():
            await ms.record_request(
                provider=selected_provider,
                response_time=elapsed,
                success=False,
                error_type=type(e).__name__
            )
        
        logger.error(f"Completion request failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

async def _stream_completion(pm: ProviderManager, 
                           request: CompletionRequest, 
                           provider_name: str,
                           ms: MetricsService,
                           start_time: float):
    """Handle streaming completion"""
    try:
        provider = pm.providers[provider_name]
        
        # Convert to provider request format
        from .provider_base import CompletionRequest as ProviderRequest
        provider_request = ProviderRequest(
            messages=request.messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            stream=True
        )
        
        chunk_count = 0
        async for chunk in provider.get_streaming_completion(provider_request):
            chunk_count += 1
            
            # Format as SSE
            data = {
                "id": f"chunk_{chunk_count}",
                "object": "chat.completion.chunk",
                "content": chunk,
                "provider": provider_name,
                "model": getattr(provider, 'model_name', 'unknown')
            }
            
            yield f"data: {json.dumps(data)}\n\n"
        
        # Send completion marker
        yield f"data: {json.dumps({'done': True})}\n\n"
        
        # Record success
        elapsed = time.time() - start_time
        await ms.record_request(
            provider=provider_name,
            response_time=elapsed,
            success=True
        )
        
    except Exception as e:
        # Record failure
        elapsed = time.time() - start_time
        await ms.record_request(
            provider=provider_name,
            response_time=elapsed,
            success=False,
            error_type=type(e).__name__
        )
        
        # Send error
        error_data = {
            "error": str(e),
            "provider": provider_name,
            "done": True
        }
        yield f"data: {json.dumps(error_data)}\n\n"

@app.get("/metrics", response_model=MetricsResponse, tags=["Monitoring"])
async def get_metrics(window_minutes: int = 60,
                     provider: Optional[str] = None,
                     ms: MetricsService = Depends(get_metrics_service)):
    """Get comprehensive metrics"""
    
    if provider:
        provider_stats = ms.get_provider_stats(provider, window_minutes)
        provider_metrics = {provider: provider_stats}
    else:
        provider_metrics = ms.get_all_provider_stats(window_minutes)
    
    gateway_stats = ms.get_gateway_stats(window_minutes)
    
    return MetricsResponse(
        gateway_metrics=gateway_stats,
        provider_metrics=provider_metrics,
        avg_response_time=gateway_stats['avg_response_time'],
        requests_per_second=gateway_stats['requests_per_second'],
        error_rate=gateway_stats['error_rate']
    )

@app.get("/admin/providers/{provider_name}/circuit-breaker", tags=["Administration"])
async def get_circuit_breaker_stats(provider_name: str,
                                   pm: ProviderManager = Depends(get_provider_manager)):
    """Get circuit breaker statistics for a provider"""
    if provider_name not in pm.circuit_breakers:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    return pm.circuit_breakers[provider_name].get_stats()

@app.post("/admin/providers/{provider_name}/circuit-breaker/reset", tags=["Administration"])
async def reset_circuit_breaker(provider_name: str,
                               pm: ProviderManager = Depends(get_provider_manager)):
    """Reset circuit breaker for a provider"""
    if provider_name not in pm.circuit_breakers:
        raise HTTPException(status_code=404, detail="Provider not found")
    
    pm.circuit_breakers[provider_name]._reset()
    return {"message": f"Circuit breaker reset for {provider_name}"}

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", 8080))
    host = os.getenv("HOST", "0.0.0.0")
    
    uvicorn.run(
        "enhanced_api_gateway:app",
        host=host,
        port=port,
        reload=False,
        log_level="info"
    )