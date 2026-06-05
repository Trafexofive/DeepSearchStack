"""OpenCode/Zen provider — free tier OpenAI-compatible API for DeepSeek V4 Flash Free.

Models:
  - deepseek-v4-flash-free   (DeepSeek V4 Flash, 200K context, reasoning)

Base URL: https://opencode.ai/zen/v1
No API key required for free models. Set OPENCODE_API_KEY for paid models.
"""

from typing import AsyncGenerator
import json
import os

from .provider_base import BaseProvider
from models.requests import ChatCompletionRequest
from models.responses import ChatCompletionResponse, TokenUsage


class OpenCodeProvider(BaseProvider):
    """OpenCode/Zen free tier — https://opencode.ai/zen/v1

    Free models:
      - deepseek-v4-flash-free (reasoning, 200K context)
      - nemotron-3-super-free  (reasoning, 128K context)

    Requires OPENCODE_API_KEY env var for paid models; free tier works without one.
    Rate limit: generous for session-based usage (~30 RPM typical).
    """

    def __init__(self, api_key: str = ""):
        super().__init__(
            api_key=api_key,
            base_url="https://opencode.ai/zen/v1/chat/completions",
            max_rpm=30,
            timeout=240,
        )

    @property
    def default_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "deepsearch-inference-gateway/1.0",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

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
        """Build payload with DeepSeek-compatible config.

        Cap max_tokens at 8K (audit L182) — 128K was excessive for the
        free tier and could cause upstream rate-limit rejections. The
        cap is applied unconditionally, not just as a default, because
        Pydantic always fills max_tokens with a value (default 1024),
        so setdefault never fires. The cap protects against both the
        "user didn't set it" and "user set it too high" cases.
        """
        payload = request.model_dump(exclude_none=True)
        payload["max_tokens"] = min(payload.get("max_tokens") or 8192, 8192)
        return payload
