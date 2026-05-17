# Search Agent — LLM Synthesis (port 8013)

> **Status**: ✅ Working (deployed 2026-05-13) · **Dependencies**: inference-gateway (8005)

## Purpose
LLM-powered search result synthesizer. Takes ranked search results + a user query, feeds context to inference-gateway, and streams a synthesized answer with source citations.

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | `{"status":"healthy","version":"9.0.0"}` |
| POST | `/synthesize/stream` | Synthesize search results → streaming answer (SSE) |

## Synthesize Request
```json
{
  "query": "What is Rust ownership?",
  "sources": [{"title": "...", "url": "...", "description": "..."}],
  "llm_provider": "deepseek-chat",
  "temperature": 0.7
}
```

## Streaming Response (SSE)
```
data: {"content": "Rust ownership is ", "finished": false}
data: {"content": "a memory management...", "finished": false}
data: {"content": "", "finished": true, "sources": [...]}
```

## Architecture
```
web-api → search-agent → inference_gateway → DeepSeek v4-flash
              ↑
         search-gateway results fed as context
```

## Docker
```bash
make up dss/search-agent
```

## E2E Test
```bash
curl -s -N -X POST http://localhost:8013/synthesize/stream \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is Rust ownership?",
    "sources": [
      {"title":"Ownership","url":"https://doc.rust-lang.org/book/ch04-01.html","description":"Ownership is Rusts most unique feature..."}
    ]
  }'
```
