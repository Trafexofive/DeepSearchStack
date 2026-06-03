"""Inference Gateway SDK — typed async Python client for Substrate's LLM router.

Usage:
    from inference_gateway_client import InferenceGatewayClient

    async with InferenceGatewayClient() as gw:
        # Health check
        health = await gw.health()

        # List available models
        models = await gw.list_models()

        # Simple chat completion
        reply = await gw.chat("Explain Rust ownership in one sentence.")
        print(reply.content)

        # With custom params
        reply = await gw.chat(
            messages=[{"role": "user", "content": "Write a haiku about Docker"}],
            model="deepseek-chat",
            temperature=0.3,
            max_tokens=100,
        )

        # Route to specific provider
        reply = await gw.chat("Hello", provider="deepseek")

        # Use virtual model with fallback chain
        reply = await gw.chat("Write a function", model="virtual/coder")

        # Streaming (async generator)
        async for chunk in gw.chat_stream("Tell me a story"):
            print(chunk, end="", flush=True)
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional

import httpx


# ═══════════════════════════════════════════════════════════════════════════════
# Models
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    @property
    def ratio(self) -> float:
        """Input/output token ratio."""
        if self.completion_tokens == 0:
            return 0.0
        return self.prompt_tokens / self.completion_tokens


@dataclass
class ChatResponse:
    content: str
    usage: TokenUsage
    raw_response: dict = field(default_factory=dict)
    model: str = ""
    provider: str = ""


@dataclass
class ModelInfo:
    id: str
    provider: str
    owned_by: str = ""
    context_length: int | None = None


@dataclass
class HealthStatus:
    status: str
    providers: list[str]
    models: int


@dataclass
class VirtualModelInfo:
    name: str
    routes: list[dict]  # [{provider, model}, ...]


# ═══════════════════════════════════════════════════════════════════════════════
# Cost Estimator
# ═══════════════════════════════════════════════════════════════════════════════

# DeepSeek pricing (per 1M tokens)
DEEPSEEK_PRICES = {
    "deepseek-chat":       {"input": 0.27, "output": 1.10},
    "deepseek-reasoner":   {"input": 0.55, "output": 2.19},
}

# Add other provider prices here as needed
PROVIDER_PRICES: dict[str, dict[str, dict[str, float]]] = {
    "deepseek": DEEPSEEK_PRICES,
}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate cost in USD based on known model pricing."""
    for provider_prices in PROVIDER_PRICES.values():
        if model in provider_prices:
            p = provider_prices[model]
            return (prompt_tokens / 1_000_000) * p["input"] + \
                   (completion_tokens / 1_000_000) * p["output"]
    return 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# Client
# ═══════════════════════════════════════════════════════════════════════════════

class InferenceGatewayClient:
    """Async client for Substrate's inference-gateway."""

    def __init__(self, base_url: str = "http://localhost:8005", timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Use as context manager: async with InferenceGatewayClient() as gw:")
        return self._client

    # ── Health ────────────────────────────────────────────────────────────

    async def health(self) -> HealthStatus:
        """GET /health — check gateway status."""
        r = await self.client.get(f"{self.base_url}/health")
        r.raise_for_status()
        data = r.json()
        return HealthStatus(
            status=data["status"],
            providers=data["providers"],
            models=data["models"],
        )

    # ── Models ────────────────────────────────────────────────────────────

    async def list_models(self, provider: str | None = None) -> list[ModelInfo]:
        """GET /v1/models — list available models."""
        params = {}
        if provider:
            params["provider"] = provider
        r = await self.client.get(f"{self.base_url}/v1/models", params=params)
        r.raise_for_status()
        return [ModelInfo(**m) for m in r.json()["models"]]

    async def list_virtual_models(self) -> list[VirtualModelInfo]:
        """GET /v1/virtual-models — list virtual models with fallback chains."""
        r = await self.client.get(f"{self.base_url}/v1/virtual-models")
        r.raise_for_status()
        data = r.json()["virtual_models"]
        return [VirtualModelInfo(name=k, routes=v) for k, v in data.items()]

    # ── Chat Completions ──────────────────────────────────────────────────

    async def chat(
        self,
        messages: str | list[dict],
        model: str = "deepseek-chat",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        provider: str | None = None,
    ) -> ChatResponse:
        """POST /v1/chat/completions — single-turn chat completion.

        Args:
            messages: String prompt (converted to user message) or list of {role, content} dicts.
            model: Model ID to use.
            temperature: Sampling temperature (0-2).
            max_tokens: Maximum tokens in response.
            provider: Route to specific provider (uses x-provider header).
        """
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]

        headers = {}
        if provider:
            headers["x-provider"] = provider

        r = await self.client.post(
            f"{self.base_url}/v1/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            headers=headers,
        )
        r.raise_for_status()
        data = r.json()
        usage = TokenUsage(**data["usage"])
        raw = data.get("raw_response", {})
        return ChatResponse(
            content=data["content"],
            usage=usage,
            raw_response=raw,
            model=raw.get("model", model),
            provider=raw.get("provider", provider or "unknown"),
        )

    async def chat_stream(
        self,
        messages: str | list[dict],
        model: str = "deepseek-chat",
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        """POST /v1/chat/completions (stream=True) — streaming chat completion.

        Yields text chunks as they arrive.
        """
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]

        async with self.client.stream(
            "POST",
            f"{self.base_url}/v1/chat/completions",
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
            },
        ) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        content = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue

    # ── Batch ─────────────────────────────────────────────────────────────

    async def chat_batch(
        self,
        prompts: list[str],
        model: str = "deepseek-chat",
        temperature: float = 0.7,
        max_tokens: int = 1024,
        concurrency: int = 1,
    ) -> list[ChatResponse]:
        """Run multiple prompts in parallel with semaphore control."""
        if concurrency == 1:
            results = []
            for p in prompts:
                results.append(await self.chat(p, model=model, temperature=temperature, max_tokens=max_tokens))
            return results
        else:
            sem = asyncio.Semaphore(concurrency)

            async def _one(prompt):
                async with sem:
                    return await self.chat(prompt, model=model, temperature=temperature, max_tokens=max_tokens)

            return await asyncio.gather(*[_one(p) for p in prompts])

    # ── Utilities ─────────────────────────────────────────────────────────

    async def ping(self, model: str = "deepseek-chat") -> ChatResponse:
        """Minimal smoke test — 5 tokens, temp 0.0."""
        return await self.chat("ping", model=model, max_tokens=5, temperature=0.0)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

USAGE = """inference_gateway_client.py — CLI for Substrate inference gateway

Usage:
  python inference_gateway_client.py health
  python inference_gateway_client.py models
  python inference_gateway_client.py chat <prompt> [--model deepseek-chat] [--temp 0.7] [--max-tokens 1024]
  python inference_gateway_client.py virtual
  python inference_gateway_client.py ping
"""


async def _main():
    if len(sys.argv) < 2:
        print(USAGE)
        sys.exit(1)

    cmd = sys.argv[1]

    async with InferenceGatewayClient() as gw:
        if cmd == "health":
            h = await gw.health()
            print(json.dumps({
                "status": h.status,
                "providers": h.providers,
                "models": h.models,
            }, indent=2))

        elif cmd == "models":
            provider = None
            for i, arg in enumerate(sys.argv):
                if arg == "--provider" and i + 1 < len(sys.argv):
                    provider = sys.argv[i + 1]
            models = await gw.list_models(provider=provider)
            for m in models:
                ctx = f" (ctx: {m.context_length})" if m.context_length else ""
                print(f"  {m.id:<30} [{m.provider}]{ctx}")

        elif cmd == "virtual":
            vms = await gw.list_virtual_models()
            for vm in vms:
                print(f"  {vm.name}:")
                for route in vm.routes:
                    print(f"    → {route['provider']}/{route['model']}")

        elif cmd == "chat":
            prompt = sys.argv[2] if len(sys.argv) > 2 else "Hello"
            model = "deepseek-chat"
            temp = 0.7
            max_tokens = 1024
            for i, arg in enumerate(sys.argv):
                if arg == "--model" and i + 1 < len(sys.argv):
                    model = sys.argv[i + 1]
                elif arg == "--temp" and i + 1 < len(sys.argv):
                    temp = float(sys.argv[i + 1])
                elif arg == "--max-tokens" and i + 1 < len(sys.argv):
                    max_tokens = int(sys.argv[i + 1])

            resp = await gw.chat(prompt, model=model, temperature=temp, max_tokens=max_tokens)
            cost = estimate_cost(resp.model, resp.usage.prompt_tokens, resp.usage.completion_tokens)
            print(resp.content)
            print(f"\n── {resp.usage.total_tokens}t | ${cost:.6f} | {resp.model}")

        elif cmd == "ping":
            resp = await gw.ping()
            cost = estimate_cost(resp.model, resp.usage.prompt_tokens, resp.usage.completion_tokens)
            print(f"✓ {resp.content[:50]} | {resp.usage.total_tokens}t | ${cost:.6f}")

        else:
            print(f"Unknown command: {cmd}\n{USAGE}")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(_main())
