"""Pydantic models for LLM Gateway response schemas."""

from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    content: str
    usage: TokenUsage
    raw_response: Dict[str, Any] = Field(default_factory=dict)


class ModelInfo(BaseModel):
    id: str
    provider: str
    owned_by: str = ""
    context_length: Optional[int] = None


class ModelCatalogResponse(BaseModel):
    models: List[ModelInfo]
