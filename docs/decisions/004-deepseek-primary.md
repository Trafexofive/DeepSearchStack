# ADR 004: DeepSeek v4-flash as Primary Model

**Status**: Accepted  
**Date**: 2026-05-12

## Context
Need a primary LLM for the indie hacker control plane. Must be cost-effective for automated content generation, support OpenAI-compatible API, and have a paid API key (no free-tier rate limit anxiety).

## Decision
Use **DeepSeek** platform API as the primary provider, with `deepseek-chat` → `deepseek-v4-flash` as the default model.

## Rationale
- DeepSeek v4-flash is their latest unified model (replaces separate chat/reasoner models)
- Extremely cost-effective: ~$0.27/M input tokens, ~$1.10/M output tokens
- OpenAI-compatible API — works with our provider pattern unchanged
- API key already available (set in host zsh env as `DEEPSEEK_API_KEY`)
- 50 RPM rate limit (configurable in provider)
- 64K context window covers most blog/content generation needs

## Observed Behavior
- Requesting `deepseek-chat` resolves to `deepseek-v4-flash` on DeepSeek's platform
- Requesting `deepseek-reasoner` also resolves to `deepseek-v4-flash`
- This is DeepSeek's own routing — both aliases point to the unified model
- E2E verified: 1239 tokens, $0.001184, 19.3s for a full blog post

## Alternatives Considered
- **OpenRouter free tier**: Unreliable, rate-limited, model availability varies
- **Ollama local**: Requires GPU, no cloud redundancy
- **Groq**: Fast but free tier is rate-limited; API key needed for reliable use
- **NVIDIA NIM**: Good free tier but model availability is unpredictable

## Consequences
- `DEEPSEEK_API_KEY` is the only required environment variable for inference
- Cost tracking is built into `blog_generator/tracker.py` with DeepSeek pricing
- Adding more providers is additive — DeepSeek remains the default, others are fallback
