"""NVIDIA NIM provider — free-tier inference gateway for 40+ models.

NVIDIA NIM (NVIDIA Inference Microservices) provides a unified OpenAI-compatible
API endpoint for a growing catalog of open-source and third-party models.

Free tier: 40 requests/minute, no credit card required.
Base URL: https://integrate.api.nvidia.com/v1/chat/completions
Auth:    Bearer nvapi-<your_key>

Notable models:
  - zhipuai/glm-4-9b-chat       → GLM-4 (Zhipu AI, 128K context)
  - minimax/minimax-m1           → MiniMax M1 (4M context)
  - deepseek-ai/deepseek-r1      → DeepSeek R1 reasoning
  - meta/llama-4-maverick-17b    → Llama 4 Maverick
  - meta/llama-4-scout-17b       → Llama 4 Scout (10M context)
  - qwen/qwen3-235b-a22b         → Qwen3 MoE
  - mistralai/mistral-large-2    → Mistral Large 2
  - google/gemma-3-27b-it        → Gemma 3
  - nvidia/nemotron-4            → NVIDIA Nemotron
  - microsoft/phi-4-mini         → Phi-4 Mini

Full catalog: https://build.nvidia.com/explore/discover
"""

from typing import AsyncGenerator
import json

from .provider_base import BaseProvider
from models.requests import ChatCompletionRequest
from models.responses import ChatCompletionResponse, TokenUsage


class NvidiaNimProvider(BaseProvider):
    def __init__(self, api_key: str):
        super().__init__(
            api_key=api_key,
            base_url="https://integrate.api.nvidia.com/v1/chat/completions",
            max_rpm=40,  # Free tier limit
            timeout=600.0,
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
        return [
            "zhipuai/glm-4-9b-chat",
            "minimax/minimax-m1",
            "deepseek-ai/deepseek-r1",
            "meta/llama-4-maverick-17b",
            "meta/llama-4-scout-17b",
            "qwen/qwen3-235b-a22b",
            "mistralai/mistral-large-2",
            "google/gemma-3-27b-it",
            "microsoft/phi-4-mini",
            "nvidia/nemotron-4",
        ]
