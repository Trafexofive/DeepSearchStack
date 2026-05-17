"""
Search Agent's LLM Client — inference-gateway adapter.

Routes to inference-gateway's OpenAI-compatible /v1/chat/completions endpoint.
Handles the inference-gateway envelope (raw_response.choices wrapper).
"""
import os
import httpx
import json
from typing import List, Dict, Any, Optional

from libs.common.models import Message

class LLMClient:
    """Client for inference-gateway (OpenAI-compatible)."""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or os.environ.get("LLM_GATEWAY_URL", "http://inference_gateway:8005")
        self.endpoint = f"{self.base_url}/v1/chat/completions"

    async def get_completion(self,
                           messages: List[Message],
                           provider: Optional[str] = None,
                           temperature: float = 0.7) -> str:
        """Get a complete, non-streaming response."""
        payload = {
            "model": provider or "deepseek-chat",
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": 2048,
            "stream": False,
        }

        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(self.endpoint, json=payload)
            response.raise_for_status()
            result = response.json()
            # inference-gateway wraps in raw_response.choices
            choices = result.get("raw_response", result).get("choices", [{"message": {"content": ""}}])
            return choices[0]["message"]["content"]

    async def get_streaming_completion(self, messages: List[Message], provider: Optional[str] = None, temperature: float = 0.7):
        """Get a streaming response."""
        payload = {
            "model": provider or "deepseek-chat",
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": 2048,
            "stream": True,
        }

        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                async with client.stream("POST", self.endpoint, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data_str = line[5:].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            data = json.loads(data_str)
                            # Standard OpenAI streaming format: choices[0].delta.content
                            delta = data.get("choices", [{}])[0].get("delta", {})
                            content = delta.get("content", "")
                            if content:
                                yield content
                        except json.JSONDecodeError:
                            continue
        except httpx.ConnectError as e:
            raise ConnectionError(f"Could not connect to LLM Gateway at {self.base_url}") from e
