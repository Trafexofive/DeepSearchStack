"""Pydantic models for LLM Gateway request/response schemas."""

from pydantic import BaseModel
from typing import List, Dict, Any, Optional


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    temperature: float = 0.7
    max_tokens: int = 1024
    stream: bool = False
