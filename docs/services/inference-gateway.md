# Inference Gateway (port 8005)

> **Status**: ✅ Working · **Source**: Morphed from `~/repos/free-inference-stack/services/llm_gateway/`

## Purpose
Provider-agnostic LLM router. Drop providers into `providers/`, register in `main.py`, route via `/v1/chat/completions`.

## Architecture
```
providers/
├── provider_base.py        ← Token bucket + tenacity retry
├── deepseek_provider.py    ← DeepSeek API (active)
└── (add more...)           ← Copy from FIS when needed
```

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | `{"status":"ok","providers":["deepseek"],"models":2}` |
| GET | `/v1/models?provider=X` | Model catalog |
| GET | `/v1/virtual-models` | Virtual model fallback chains |
| POST | `/v1/chat/completions` | Chat completion (3 routing modes) |

## Routing Modes

```bash
# Mode 1: Auto-resolve from model catalog
curl -X POST localhost:8005/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"Hello"}]}'

# Mode 2: Explicit provider via header
curl -X POST localhost:8005/v1/chat/completions \
  -H "x-provider: deepseek" \
  -d '{"model":"any-model","messages":[...]}'

# Mode 3: Virtual model with cascading fallback
curl -X POST localhost:8005/v1/chat/completions \
  -d '{"model":"virtual/reasoning","messages":[...]}'
```

## Current Model
`deepseek-chat` → resolves to `deepseek-v4-flash` on DeepSeek's platform (2026-05-12).  
Pricing: $0.27/M input, $1.10/M output. 50 RPM.

## Adding Providers
See [Adding a Provider](../development/adding-a-provider.md) and [ADR 003](../decisions/003-provider-pattern.md).

## Docker
```bash
# Standalone
cd services/inference-gateway && docker compose up -d

# Via core compose
make up core
```
