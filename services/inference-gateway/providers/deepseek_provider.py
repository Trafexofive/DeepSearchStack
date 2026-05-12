"""DeepSeek provider — OpenAI-compatible API for DeepSeek-V3 and DeepSeek-R1."""

from typing import AsyncGenerator
import json

from .provider_base import BaseProvider
from models.requests import ChatCompletionRequest
from models.responses import ChatCompletionResponse, TokenUsage


class DeepSeekProvider(BaseProvider):
    """DeepSeek Platform API — https://platform.deepseek.com/api-docs

    Models:
      - deepseek-chat     → DeepSeek-V3 (general-purpose, 64K context)
      - deepseek-reasoner → DeepSeek-R1 (reasoning, 64K context)

    Rate limit: ~50 RPM (varies by account tier).
    """

    def __init__(self, api_key: str):
        super().__init__(
            api_key=api_key,
            base_url="https://api.deepseek.com/v1/chat/completions",
            max_rpm=50,
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

        return ChatCompletionResponse(
            content=data["choices"][0]["message"]["content"],
            usage=usage,
            raw_response=data,
        )

    async def chat_stream(self, request: ChatCompletionRequest) -> AsyncGenerator[str, None]:
        payload = request.model_dump()
        payload["stream"] = True

        await self.rate_limiter.acquire()
        async with self._client.stream(
            "POST", self.base_url, headers=self.default_headers, json=payload
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    line = line[6:]
                if line == "[DONE]":
                    break
                try:
                    chunk = json.loads(line)
                    delta = chunk["choices"][0].get("delta", {})
                    if "content" in delta:
                        yield delta["content"]
                except (json.JSONDecodeError, KeyError):
                    continue
