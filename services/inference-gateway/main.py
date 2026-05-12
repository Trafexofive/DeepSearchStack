"""Substrate Inference Gateway — provider-agnostic LLM routing with DeepSeek.

Multi-provider routing with virtual models, cascading fallback, and key pools.
Drop more providers into providers/ and register them below.
"""

import os
import json
import httpx
import logging
from copy import deepcopy
from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import StreamingResponse
from typing import Optional

from models.requests import ChatCompletionRequest
from models.responses import ChatCompletionResponse, ModelCatalogResponse, ModelInfo
from providers.deepseek_provider import DeepSeekProvider

logger = logging.getLogger("inference-gateway")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))


# ─── Provider Registry ───────────────────────────────────────────────────────

def _init_providers() -> dict:
    """Build provider instances from env. Skip any with missing keys.

    To add a new provider:
    1. Drop it into providers/your_provider.py
    2. Import it at the top of this file
    3. Add a tuple below: (name, Class, env_var)
    """
    registry = {}

    specs = [
        ("deepseek", DeepSeekProvider, "DEEPSEEK_API_KEY"),
        # Add more providers here as they're implemented:
        # ("openrouter",  OpenRouterProvider,  "OPENROUTER_API_KEY"),
        # ("nvidia",      NvidiaProvider,      "NVIDIA_API_KEY"),
        # ("groq",        GroqProvider,        "GROQ_API_KEY"),
        # ("cerebras",    CerebrasProvider,    "CEREBRAS_API_KEY"),
        # ("gemini",      GeminiProvider,      "GEMINI_API_KEY"),
        # ("github",      GitHubProvider,      "GITHUB_TOKEN"),
        # ("siliconflow", SiliconFlowProvider, "SILICONFLOW_API_KEY"),
        # ("sambanova",   SambaNovaProvider,   "SAMBA_NOVA_API_KEY"),
    ]

    for name, cls, env_var in specs:
        key = os.getenv(env_var, "")
        if key:
            registry[name] = cls(api_key=key)
            logger.info(f"Provider registered: {name}")
        else:
            logger.warning(f"Provider skipped (no key): {name} — set {env_var}")

    return registry


providers = _init_providers()


# ─── FastAPI App ─────────────────────────────────────────────────────────────

app = FastAPI(
    title="Substrate Inference Gateway",
    version="0.1.0",
    description="Provider-agnostic LLM routing. Drop providers into providers/.",
)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "providers": list(providers.keys()),
        "models": len(model_catalog),
    }


# ─── Model Catalog ───────────────────────────────────────────────────────────

model_catalog: dict[str, ModelInfo] = {}


@app.on_event("startup")
async def discover_models():
    """Build the model catalog from static entries + live discovery."""
    static_models = {
        "deepseek": [
            ModelInfo(id="deepseek-chat", provider="deepseek", owned_by="deepseek-ai", context_length=65536),
            ModelInfo(id="deepseek-reasoner", provider="deepseek", owned_by="deepseek-ai", context_length=65536),
        ],
        # Add static models for other providers here
    }

    for provider_name, models in static_models.items():
        if provider_name in providers:
            for m in models:
                model_catalog[f"{provider_name}:{m.id}"] = m

    logger.info(f"Model catalog: {len(model_catalog)} models across {len(providers)} providers")


@app.get("/v1/models", response_model=ModelCatalogResponse)
async def list_models(provider: Optional[str] = None):
    """Return the unified model catalog. Optionally filter by provider."""
    models = list(model_catalog.values())
    if provider:
        models = [m for m in models if m.provider == provider]
    return ModelCatalogResponse(models=models)


# ─── Virtual Models (Cascading Fallback) ─────────────────────────────────────

VIRTUAL_MODELS: dict[str, list[dict]] = {
    "virtual/coder": [
        {"provider": "deepseek", "model": "deepseek-chat"},
    ],
    "virtual/reasoning": [
        {"provider": "deepseek", "model": "deepseek-reasoner"},
    ],
    # Extend with multi-provider fallback chains:
    # "virtual/coder-heavy": [
    #     {"provider": "deepseek", "model": "deepseek-chat"},
    #     {"provider": "groq",    "model": "deepseek-r1-distill-llama-70b"},
    # ],
}


@app.get("/v1/virtual-models")
async def list_virtual_models():
    return {"virtual_models": {k: v for k, v in VIRTUAL_MODELS.items()}}


# ─── Chat Completions ────────────────────────────────────────────────────────

@app.post("/v1/chat/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    x_provider: Optional[str] = Header(default=None),
):
    """Route a chat completion request.

    Three routing modes:
    1. Virtual model: request.model starts with "virtual/" → cascade through fallback chain
    2. Explicit provider: x-provider header set → route to that provider
    3. Auto-resolve: no header → look up model in catalog, fall back to first available provider
    """
    if not providers:
        raise HTTPException(status_code=503, detail="No providers configured")

    # Mode 1: Virtual model cascade
    if request.model.startswith("virtual/"):
        return await _cascade(request)

    # Mode 2: Explicit provider via header
    if x_provider:
        if x_provider not in providers:
            raise HTTPException(status_code=400, detail=f"Unknown provider: {x_provider}. Available: {list(providers.keys())}")
        return await _single_request(request, x_provider)

    # Mode 3: Auto-resolve from catalog
    resolved = _resolve_provider_from_catalog(request.model)
    return await _single_request(request, resolved)


def _resolve_provider_from_catalog(model: str) -> str:
    """Look up which provider hosts a given model. Falls back to first available."""
    for key, info in model_catalog.items():
        if info.id == model:
            return info.provider
    return list(providers.keys())[0]


async def _single_request(request: ChatCompletionRequest, provider_name: str) -> ChatCompletionResponse:
    """Execute a request against a single provider."""
    provider = providers.get(provider_name)
    if not provider:
        raise HTTPException(status_code=400, detail=f"Provider not configured: {provider_name}")

    try:
        if request.stream:
            async def stream_generator():
                async for chunk in provider.chat_stream(request):
                    yield f"data: {json.dumps(chunk)}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(stream_generator(), media_type="text/event-stream")

        return await provider.chat(request)

    except httpx.HTTPStatusError as e:
        try:
            detail = e.response.json()
        except Exception:
            detail = f"Upstream error: {e.response.text[:500]}"
        raise HTTPException(status_code=e.response.status_code, detail=detail)

    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Network error: {str(e)}")


async def _cascade(request: ChatCompletionRequest) -> ChatCompletionResponse:
    """Try each provider in a virtual model's fallback chain until one succeeds."""
    route_list = VIRTUAL_MODELS.get(request.model)
    if not route_list:
        raise HTTPException(status_code=400, detail=f"Unknown virtual model: {request.model}")

    last_error = None

    for route in route_list:
        provider_name = route["provider"]
        provider = providers.get(provider_name)

        if not provider:
            logger.info(f"Cascade: skipping {provider_name} (not configured)")
            continue

        req_copy = request.model_copy(update={"model": route["model"]})

        try:
            logger.info(f"Cascade: trying {provider_name}/{route['model']}")
            response = await provider.chat(req_copy)
            logger.info(f"Cascade: success on {provider_name}/{route['model']}")
            return response

        except httpx.HTTPStatusError as e:
            if e.response.status_code in {429, 402, 503}:
                logger.warning(f"Cascade: {provider_name} returned {e.response.status_code}, trying next...")
                last_error = e
                continue
            raise HTTPException(status_code=e.response.status_code, detail=f"Upstream error from {provider_name}: {e.response.text[:500]}")

        except httpx.RequestError as e:
            logger.warning(f"Cascade: {provider_name} network error: {e}")
            last_error = e
            continue

    raise HTTPException(
        status_code=429,
        detail=f"All providers in virtual model '{request.model}' exhausted. Last error: {last_error}",
    )


# ─── Shutdown ────────────────────────────────────────────────────────────────

@app.on_event("shutdown")
async def shutdown():
    for p in providers.values():
        await p.close()
