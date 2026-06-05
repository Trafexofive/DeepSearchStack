"""Groq provider — fast inference for open-source LLMs (OpenAI-compatible).

Models:
  - llama-3.1-8b-instant     (fast, 128K context)
  - llama-3.3-70b-versatile  (versatile, 128K context)
  - mixtral-8x7b-32768       (32K context)
  - gemma2-9b-it             (8K context)

Base URL: https://api.groq.com/openai/v1
Requires GROQ_API_KEY. Generous free tier.
"""

from typing import AsyncGenerator
import json

from .provider_base import BaseProvider
from models.requests import ChatCompletionRequest
from models.responses import ChatCompletionResponse, TokenUsage


class GroqProvider(BaseProvider):
    """Groq — fast inference for open-source LLMs. OpenAI-compatible API."""

    def __init__(self, api_key: str):
        super().__init__(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1/chat/completions",
            max_rpm=30,
            timeout=120,
        )

    @property
    def default_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

    async def chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        payload = self._build_payload(request)
        response = await self._post(payload)
        data = response.json()

        usage_data = data.get("usage", {})
        usage = TokenUsage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )

        return ChatCompletionResponse(
            content=data["choices"][0]["message"]["content"],
            usage=usage,
            raw_response=data,
        )

    async def chat_stream(self, request: ChatCompletionRequest) -> AsyncGenerator[dict, None]:
        payload = self._build_payload(request)
        payload["stream"] = True

        await self.rate_limiter.acquire()
        async with self._client.stream(
            "POST", self.base_url, headers=self.default_headers, json=payload
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    chunk_str = line[6:]
                    if chunk_str.strip() == "[DONE]":
                        break
                    try:
                        yield json.loads(chunk_str)
                    except json.JSONDecodeError:
                        continue

    def _build_payload(self, request: ChatCompletionRequest) -> dict:
        """Build Groq-compatible payload. Cap max_tokens at 8K (free tier safe)."""
        payload = request.model_dump(exclude_none=True)
        payload.setdefault("max_tokens", 8192)
        return payload
