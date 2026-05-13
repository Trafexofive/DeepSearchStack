"""
InferenceClient — LLM inference gateway (OpenAI-compatible).

Endpoints:
  GET  /api/inference/models          — Available models
  POST /api/inference/chat/completions — OpenAI-compatible chat
"""

from typing import Optional

from pydantic import BaseModel


class ModelInfo(BaseModel):
    id: str
    provider: str
    owned_by: str
    context_length: int = 0


class InferenceClient:
    def __init__(self, base_url: str = "http://localhost:80", api_key: Optional[str] = None, timeout: float = 120.0):
        from substrate.client import SubstrateClient
        self._client = SubstrateClient(base_url, api_key, timeout)

    async def models(self) -> list[ModelInfo]:
        resp = await self._client._request("GET", "/api/inference/models")
        resp.raise_for_status()
        return [ModelInfo(**m) for m in resp.json().get("models", [])]

    async def chat(self, model: str, messages: list[dict],
                   max_tokens: int = 2048, temperature: float = 0.7,
                   **kwargs) -> dict:
        """OpenAI-compatible chat completion."""
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            **kwargs,
        }
        resp = await self._client._request("POST", "/api/inference/chat/completions", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self._client.close()
