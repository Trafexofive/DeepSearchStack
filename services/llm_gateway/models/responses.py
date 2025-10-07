"""
Enhanced response models for LLM Gateway
"""
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field
from datetime import datetime

class Usage(BaseModel):
    """Token usage statistics"""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    
    # Enhanced metrics
    prompt_time: Optional[float] = None
    completion_time: Optional[float] = None
    total_time: Optional[float] = None
    queue_time: Optional[float] = None
    
    # Cost tracking
    prompt_cost: Optional[float] = None
    completion_cost: Optional[float] = None
    total_cost: Optional[float] = None

class CompletionResponse(BaseModel):
    content: str = Field(..., description="Generated content")
    provider_name: str = Field(..., description="Provider that generated the response")
    model: str = Field(..., description="Model used for generation")
    
    # Enhanced metadata
    usage: Usage = Field(default_factory=Usage)
    response_time: Optional[float] = Field(None, description="Total response time in seconds")
    request_id: Optional[str] = Field(None, description="Request tracking ID")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    # Quality metrics
    finish_reason: Optional[str] = Field(None, description="Why generation stopped")
    confidence_score: Optional[float] = Field(None, description="Model confidence (if available)")
    
    # Additional metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ProviderStatus(BaseModel):
    """Provider availability and health status"""
    available: bool
    healthy: bool = True
    latency_ms: Optional[float] = None
    error_rate: Optional[float] = None
    last_success: Optional[datetime] = None
    last_error: Optional[str] = None
    circuit_breaker_open: bool = False
    
    # Capacity metrics
    active_requests: int = 0
    queue_length: int = 0
    rate_limit_remaining: Optional[int] = None
    
class HealthResponse(BaseModel):
    """Gateway health status"""
    status: str = Field(..., description="Overall health status")
    version: str = Field(..., description="Gateway version")
    uptime_seconds: float = Field(..., description="Uptime in seconds")
    active_providers: List[str] = Field(..., description="List of active providers")
    total_requests: int = Field(..., description="Total requests processed")
    
    # Detailed provider health
    providers: Dict[str, ProviderStatus] = Field(default_factory=dict)

class MetricsResponse(BaseModel):
    """Comprehensive metrics response"""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    gateway_metrics: Dict[str, Any] = Field(default_factory=dict)
    provider_metrics: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    
    # Performance metrics
    avg_response_time: float = 0.0
    requests_per_second: float = 0.0
    error_rate: float = 0.0
    
    # Resource usage
    memory_usage_mb: Optional[float] = None
    cpu_usage_percent: Optional[float] = None

class ErrorResponse(BaseModel):
    """Standardized error response"""
    error: str = Field(..., description="Error type")
    message: str = Field(..., description="Error message")
    details: Optional[Dict[str, Any]] = Field(None, description="Additional error details")
    request_id: Optional[str] = Field(None, description="Request ID for tracking")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    # Provider context
    provider: Optional[str] = Field(None, description="Provider where error occurred")
    retry_after: Optional[int] = Field(None, description="Suggested retry delay in seconds")