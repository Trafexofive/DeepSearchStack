# Provider Pattern — LLM Routing Architecture

## Class Diagram

```
┌─────────────────────────────────────────┐
│            BaseProvider (ABC)            │
├─────────────────────────────────────────┤
│  - api_key: str                         │
│  - base_url: str                        │
│  - rate_limiter: AsyncRateLimiter       │
│  - _client: httpx.AsyncClient           │
├─────────────────────────────────────────┤
│  + default_headers() → dict   [abstract]│
│  + chat(request) → response  [abstract]│
│  + chat_stream(request) → gen [abstract]│
│  + close()                              │
│  # _post(payload) → response [tenacity] │
└─────────────────────────────────────────┘
                    △
                    │ inherits
    ┌───────────────┼───────────────┐
    │               │               │
┌───▼────────┐ ┌───▼────────┐ ┌───▼────────┐
│ DeepSeek   │ │ Groq       │ │ NVIDIA     │
│ Provider   │ │ Provider   │ │ Provider   │
├────────────┤ ├────────────┤ ├────────────┤
│ url:       │ │ url:       │ │ url:       │
│ api.deep   │ │ api.groq   │ │ integrate. │
│ seek.com   │ │ .com       │ │ api.nvidia │
├────────────┤ ├────────────┤ ├────────────┤
│ max_rpm:50 │ │ max_rpm:30 │ │ max_rpm:40 │
│ timeout:300│ │ timeout:300│ │ timeout:300│
└────────────┘ └────────────┘ └────────────┘
```

## AsyncRateLimiter (Token Bucket)

```
┌──────────────────────────────────┐
│       AsyncRateLimiter           │
├──────────────────────────────────┤
│  - max_requests: int             │
│  - window_seconds: int           │
│  - timestamps: List[float]       │
│  - lock: asyncio.Lock            │
├──────────────────────────────────┤
│  + acquire() → await             │
│    • Evict stale timestamps      │
│    • If at capacity, sleep       │
│    • Record new timestamp        │
└──────────────────────────────────┘
```

## Adding a New Provider (3 Steps)

```bash
# 1. Create provider file
# services/inference-gateway/providers/new_provider.py

# 2. Register in main.py
# Add to specs list:
#   ("new_provider", NewProvider, "NEW_PROVIDER_API_KEY")

# 3. Add static models (optional, for catalog)
# In discover_models(), add:
#   "new_provider": [
#       ModelInfo(id="model-name", provider="new_provider", ...)
#   ]
```

Any provider that implements OpenAI-compatible `/v1/chat/completions` works with zero code changes. Non-OpenAI providers just override `chat()` and `chat_stream()`.
