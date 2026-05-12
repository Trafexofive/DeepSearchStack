"""
llm_gateway — Substrate Provider-Agnostic LLM Router

Routes LLM requests to configured providers (Ollama, Groq, OpenAI)
with fallback logic. No client code knows which provider is serving.
"""

import os
import logging
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("llm_gateway")


# ─── Models ──────────────────────────────────────────────────────────────────

class LLMRequest(BaseModel):
    model: Optional[str] = None
    provider: Optional[str] = None
    system_prompt: str = ""
    messages: list[dict] = []
    temperature: float = 0.7
    max_tokens: int = 2048


class LLMResponse(BaseModel):
    content: str
    model: str
    provider: str
    usage: dict = {}


# ─── Provider Base ───────────────────────────────────────────────────────────

class LLMProvider:
    """Base class for LLM providers."""

    name: str = "base"

    async def complete(self, req: LLMRequest) -> LLMResponse:
        raise NotImplementedError


class OllamaProvider(LLMProvider):
    name = "ollama"

    async def complete(self, req: LLMRequest) -> LLMResponse:
        import httpx

        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        model = req.model or os.getenv("LLM_MODEL", "llama3.2:latest")

        async with httpx.AsyncClient() as client:
            payload = {
                "model": model,
                "system": req.system_prompt,
                "messages": req.messages,
                "options": {
                    "temperature": req.temperature,
                    "num_predict": req.max_tokens,
                },
                "stream": False,
            }
            resp = await client.post(f"{base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()

        return LLMResponse(
            content=data["message"]["content"],
            model=model,
            provider="ollama",
            usage={"prompt_tokens": 0, "completion_tokens": 0},  # Ollama doesn't return counts
        )


class GroqProvider(LLMProvider):
    name = "groq"

    async def complete(self, req: LLMRequest) -> LLMResponse:
        import httpx

        api_key = os.getenv("GROQ_API_KEY", "")
        model = req.model or "llama3-70b-8192"

        async with httpx.AsyncClient() as client:
            payload = {
                "model": model,
                "messages": [{"role": "system", "content": req.system_prompt}] + req.messages
                if req.system_prompt
                else req.messages,
                "temperature": req.temperature,
                "max_tokens": req.max_tokens,
            }
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

        return LLMResponse(
            content=data["choices"][0]["message"]["content"],
            model=model,
            provider="groq",
            usage=data.get("usage", {}),
        )


# ─── Router ──────────────────────────────────────────────────────────────────

PROVIDERS: dict[str, LLMProvider] = {
    "ollama": OllamaProvider(),
    "groq": GroqProvider(),
}


class LLMRouter:
    """Routes requests to the appropriate provider with fallback."""

    def __init__(self):
        self.default_provider = os.getenv("LLM_PROVIDER", "ollama")
        self.providers = PROVIDERS

    async def route(self, req: LLMRequest) -> LLMResponse:
        provider_name = req.provider or self.default_provider
        provider = self.providers.get(provider_name)

        if not provider:
            available = list(self.providers.keys())
            raise ValueError(f"Unknown provider '{provider_name}'. Available: {available}")

        logger.info(f"Routing to provider: {provider_name}")
        try:
            return await provider.complete(req)
        except Exception as e:
            # Fallback to next available provider
            fallbacks = [p for p in self.providers.values() if p.name != provider_name]
            for fallback in fallbacks:
                logger.warning(f"Provider {provider_name} failed: {e}. Falling back to {fallback.name}")
                try:
                    req.provider = fallback.name
                    return await fallback.complete(req)
                except Exception:
                    continue
            raise


router = LLMRouter()

app = FastAPI(title="Substrate LLM Gateway", version="0.1.0")


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "default_provider": router.default_provider,
        "available_providers": list(router.providers.keys()),
    }


@app.post("/api/chat", response_model=LLMResponse)
async def chat(req: LLMRequest):
    """Unified LLM completion endpoint."""
    return await router.route(req)


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    import uvicorn

    port = int(os.getenv("LLM_GATEWAY_PORT", "8002"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
