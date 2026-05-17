# LLM Gateway (port 8002)

> **Status**: ✅ Working · **Dependencies**: Ollama (local), Groq API

## Purpose
Provider-agnostic LLM router. Routes requests to configured providers (Ollama, Groq, OpenAI-compatible) with fallback logic. No client code knows which provider is serving.

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | `{"status":"ok","providers":["ollama","groq"]}` |
| POST | `/chat` | Chat completion with optional provider override |

## Request
```json
{
  "model": "llama3.1",
  "provider": "ollama",
  "system_prompt": "You are helpful.",
  "messages": [{"role": "user", "content": "Hello"}],
  "temperature": 0.7,
  "max_tokens": 2048
}
```

## Providers

| Provider | Type | Notes |
|---|---|---|
| Ollama | Local | `llama3.1`, `mistral`, `phi4` on host GPU |
| Groq | Cloud | `llama-3.3-70b`, `mixtral-8x7b` (free tier) |

> **Note:** Most LLM traffic now routes through `inference-gateway (:8005)` for cost-aware DeepSeek routing. This gateway serves Ollama/Groq fallback and local-only workloads.

## Docker
```bash
make up core/llm_gateway
```

## E2E Test
```bash
curl -s -X POST http://localhost:8002/chat \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "ollama",
    "model": "llama3.1",
    "messages": [{"role":"user","content":"Say hi in one word"}],
    "max_tokens": 10
  }' | python3 -m json.tool
```
