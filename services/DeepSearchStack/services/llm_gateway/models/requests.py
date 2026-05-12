"""
Enhanced request models for LLM Gateway
"""
from typing import Dict, List, Optional, Any, Literal
from pydantic import BaseModel, Field, validator
from enum import Enum

class Message(BaseModel):
    role: str = Field(..., description="Message role (user, assistant, system)")
    content: str = Field(..., description="Message content")
    
    @validator('role')
    def validate_role(cls, v):
        if v not in ['user', 'assistant', 'system']:
            raise ValueError('Role must be user, assistant, or system')
        return v

class RoutingStrategy(str, Enum):
    """Provider routing strategies"""
    ROUND_ROBIN = "round_robin"
    LEAST_LATENCY = "least_latency" 
    LOWEST_COST = "lowest_cost"
    HIGHEST_QUALITY = "highest_quality"
    RANDOM = "random"
    FAILOVER = "failover"

class CompletionRequest(BaseModel):
    messages: List[Message] = Field(..., description="List of messages")
    temperature: float = Field(0.7, ge=0.0, le=2.0, description="Sampling temperature")
    max_tokens: Optional[int] = Field(None, ge=1, le=32000, description="Maximum tokens")
    stream: bool = Field(False, description="Enable streaming response")
    
    # Enhanced routing options
    provider: Optional[str] = Field(None, description="Specific provider to use")
    routing_strategy: RoutingStrategy = Field(RoutingStrategy.RANDOM, description="Provider selection strategy") 
    fallback: bool = Field(True, description="Enable fallback to other providers")
    timeout: int = Field(30, ge=1, le=300, description="Request timeout in seconds")
    
    # Model selection
    model: Optional[str] = Field(None, description="Specific model to use")
    
    # Advanced options
    top_p: Optional[float] = Field(None, ge=0.0, le=1.0, description="Nucleus sampling")
    frequency_penalty: Optional[float] = Field(None, ge=-2.0, le=2.0)
    presence_penalty: Optional[float] = Field(None, ge=-2.0, le=2.0)
    stop: Optional[List[str]] = Field(None, description="Stop sequences")
    
    # Metadata
    user_id: Optional[str] = Field(None, description="User identifier for rate limiting")
    request_id: Optional[str] = Field(None, description="Request tracking ID")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")

class ProviderHealthRequest(BaseModel):
    provider: str = Field(..., description="Provider name to check")
    detailed: bool = Field(False, description="Include detailed health metrics")

class MetricsRequest(BaseModel):
    provider: Optional[str] = Field(None, description="Filter by provider")
    start_time: Optional[str] = Field(None, description="Start time for metrics (ISO format)")
    end_time: Optional[str] = Field(None, description="End time for metrics (ISO format)")
    metric_type: Optional[str] = Field(None, description="Specific metric type")