"""Pydantic models for LLM Gateway request/response schemas."""

from pydantic import BaseModel
from typing import List, Dict, Any, Optional, Union


class ChatMessage(BaseModel):
    role: str
    # OpenAI multimodal: either a plain string, or a list of content parts
    # ({"type":"text","text":...}, {"type":"image_url","image_url":{"url":...}}).
    # Forwarded as-is to the provider — only vision-capable providers
    # (NVIDIA NIM for Llama-4 vision, etc.) will accept the list form.
    content: Union[str, List[Dict[str, Any]]]


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    temperature: float = 0.7
    max_tokens: int = 1024
    stream: bool = False
