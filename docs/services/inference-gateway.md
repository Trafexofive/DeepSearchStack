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

## Python SDK (`sdk/client.py`)

Typed async client with cost estimation. Usable as library or CLI.

```python
from sdk.client import InferenceGatewayClient

async with InferenceGatewayClient() as gw:
    # Health + model discovery
    health = await gw.health()
    models = await gw.list_models()

    # Chat
    reply = await gw.chat("Explain Rust ownership.", max_tokens=100)
    print(f"{reply.content}  ({reply.usage.total_tokens}t, ${cost})")

    # Streaming
    async for chunk in gw.chat_stream("Tell a joke"):
        print(chunk, end="")

    # Provider routing
    reply = await gw.chat("Hello", provider="deepseek")

    # Virtual model cascade
    reply = await gw.chat("Write a function", model="virtual/coder")

    # Batch (concurrent)
    results = await gw.chat_batch(["hi", "hey", "hello"], concurrency=3)
```

### CLI
```bash
python sdk/client.py health
python sdk/client.py models
python sdk/client.py models --provider deepseek
python sdk/client.py chat "Explain monads" --temp 0.3 --max-tokens 200
python sdk/client.py virtual
python sdk/client.py ping
```
