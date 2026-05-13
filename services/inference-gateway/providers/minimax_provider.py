"""MiniMax provider — OpenAI-compatible API for abab models.

Models:
  - MiniMax-Text-01 → Flagship (4M token context, strong reasoning)
  - abab6.5s-chat   → Fast & cheap (200K context, best price/perf)
  - abab6.5s        → Legacy general-purpose

Pricing (abab6.5s-chat): ~$0.075/M input, ~$0.075/M output.
  One of the cheapest production-grade LLMs available.

Rate limit: ~30 RPM default.
"""

from typing import AsyncGenerator
import json

from .provider_base import BaseProvider
from models.requests import ChatCompletionRequest
from models.responses import ChatCompletionResponse, TokenUsage


class MiniMaxProvider(BaseProvider):
    def __init__(self, api_key: str):
        super().__init__(
            api_key=api_key,
            base_url="https://api.minimax.chat/v1/chat/completions",
            max_rpm=40,  # Free tier via NVIDIA NIM
        )

    @property
    def default_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        payload = request.model_dump()
        response = await self._post(payload)
        data = response.json()

        usage_data = data.get("usage", {})
        usage = TokenUsage(
            prompt_tokens=usage_data.get("prompt_tokens", 0),
            completion_tokens=usage_data.get("completion_tokens", 0),
            total_tokens=usage_data.get("total_tokens", 0),
        )

        choice = data["choices"][0]
        return ChatCompletionResponse(
            id=data.get("id", ""),
            model=data.get("model", request.model),
            content=choice["message"]["content"],
            finish_reason=choice.get("finish_reason", "stop"),
            usage=usage,
        )

    async def chat_stream(self, request: ChatCompletionRequest) -> AsyncGenerator[str, None]:
        payload = {**request.model_dump(), "stream": True}
        await self.rate_limiter.acquire()

        async with self._client.stream(
            "POST", self.base_url, headers=self.default_headers, json=payload
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if data_str == "[DONE]" or not data_str:
                        continue
                    try:
                        chunk = json.loads(data_str)
                        delta = chunk["choices"][0].get("delta", {})
                        if delta.get("content"):
                            yield delta["content"]
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

    @staticmethod
    def models() -> list[str]:
        return ["MiniMax-Text-01", "abab6.5s-chat", "abab6.5s"]
