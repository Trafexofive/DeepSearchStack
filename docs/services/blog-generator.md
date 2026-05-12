# Blog Generator (port 8006)

> **Status**: ✅ Working · **Dependencies**: inference-gateway (port 8005)

## Purpose
AI-powered blog post generation with structured JSON logging and token/cost tracking.

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | `{"status":"ok","generations":N}` |
| POST | `/generate` | Generate a blog post |
| GET | `/stats` | Aggregate token/cost statistics |
| POST | `/generate-researched` | Research via DeepSearch, then generate blog with sources |

## Generate Request
```json
{
  "topic": "Building a zero-dependency async runtime in 200 lines of Rust",
  "model": "deepseek-chat",
  "style": "technical",
  "max_tokens": 2048,
  "temperature": 0.7
}
```
- `style`: `"technical"` | `"tutorial"` | `"thought"`
- `max_tokens`: 256–8192

## Tracking
- **SQLite** database at `/app/data/tracker.db` (mounted volume)
- Tracks: `id, rid, model, topic, prompt_tokens, completion_tokens, cost_usd, duration_ms, status`
- Cost calculated with DeepSeek pricing ($0.27/M input, $1.10/M output)

## Logging
Structured JSON with request correlation IDs (`rid`):
```json
{"ts":"2026-05-12T15:01:38Z","level":"INFO","logger":"blog_generator.generator",
 "msg":"Blog generated: id=2cd179e935c3 model=deepseek-v4-flash tokens=1239 cost=$0.001184 duration=19340ms",
 "rid":"40d0dc1fc69a","module":"generator","line":103}
```

## Docker
```bash
# Standalone (needs inference-gateway on same network)
cd services/blog_generator && docker compose up -d

# Via core compose (preferred — shared substrate-net)
make up core
```

## E2E Test
```bash
curl -s http://localhost:8006/generate \
  -H "Content-Type: application/json" \
  -d '{"topic":"Test post","style":"technical","max_tokens":256}' \
  | python3 -m json.tool

# Check tracking
curl -s http://localhost:8006/stats | python3 -m json.tool
```
