# ADR 003: Provider Pattern for LLM Routing

**Status**: Accepted  
**Date**: 2026-05-12

## Context
Need to support multiple LLM providers (DeepSeek, Groq, NVIDIA, Gemini, GitHub, etc.) through a unified interface. Providers have different auth mechanisms, rate limits, and model catalogs but share an OpenAI-compatible chat completions API.

## Decision
Use a **Provider Pattern** with an abstract `BaseProvider` class and concrete implementations in `providers/`. The router (`main.py`) discovers providers from environment variables, builds a unified model catalog, and handles routing/fallback.

## Architecture
```
providers/
├── provider_base.py        ← AsyncRateLimiter, tenacity retry, _post()
├── deepseek_provider.py    ← DeepSeek (OpenAI-compatible)
└── (more providers...)     ← Drop in, import, register
```

### Base Provider Features
- Token-bucket rate limiter (configurable RPM)
- Exponential backoff retry (tenacity, 20 attempts, retryable errors only)
- Abstract `chat()` and `chat_stream()` methods
- Single `httpx.AsyncClient` per provider instance

### Routing Modes
1. **Virtual model**: `model: "virtual/reasoning"` → cascades through fallback chain
2. **Explicit provider**: `x-provider: deepseek` header → direct route
3. **Auto-resolve**: look up model in catalog → route to owning provider

## Rationale
- Adding a provider is 3 steps: copy a file, import it, add to the `specs` list
- Providers share 90% of their code (OpenAI-compatible API, same streaming pattern)
- Rate limiting + retry is handled once in the base class
- Virtual models enable multi-provider fallback without client awareness
- Adapted from Free Inference Stack's battle-tested provider pattern

## Consequences
- All providers speak OpenAI-compatible chat completions (standard interface)
- Model catalog is a flat dict indexed by `"provider:model_id"`
- Adding a non-OpenAI-compatible provider requires overriding `chat()` but is still possible
