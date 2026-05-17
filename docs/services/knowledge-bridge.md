# Knowledge Bridge (port 8010)

> **Status**: ✅ Working · **Dependencies**: deepsearch (DSS), crawler (DSS), warehouse (DSS), blog_generator

## Purpose
Bridges the DeepSearchStack research pipeline to the blog generator. Takes a topic → runs full DSS research → enriches with context + sources → generates a researched blog post with citations.

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/bridge/status` | Health + recent bridges + cache stats |
| POST | `/bridge/research` | Topic → research context + sources |
| POST | `/bridge/generate` | Topic + context → blog generation |
| POST | `/bridge/crawl-and-bridge` | URL → crawl → research → generate (one-shot) |

## Research Pipeline
```
Topic
  → deepsearch (:8001) — multi-stage research
  → crawler (:8000) — full-page extraction
  → warehouse (:8009) — dedup + store
  → synthesis (LLM) — key findings + context
  → blog_generator (:8006) — researched post
```

## Research
```bash
curl -s -X POST http://localhost:8010/bridge/research \
  -H "Content-Type: application/json" \
  -d '{"topic":"Rust async runtimes","max_sources":2}' \
  | python3 -m json.tool
```

Response:
```json
{
  "topic": "Rust async runtimes",
  "sources": [
    {"url": "https://...", "title": "...", "snippet": "..."}
  ],
  "key_findings": ["Finding 1", "Finding 2"],
  "context": "Synthesized research context for LLM prompt enrichment",
  "duration_ms": 45230,
  "cache_hit": false
}
```

## Crawl-and-Bridge (One-Shot)
```bash
curl -s -X POST http://localhost:8010/bridge/crawl-and-bridge \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://blog.rust-lang.org/2026/05/01/async-traits-stabilized",
    "topic": "Rust async traits stabilization"
  }' | python3 -m json.tool
```

## Context Threading
> **Fix applied 2026-05-13:** Research context was silently dropped before reaching blog_generator. Added `context` field to `GenerateRequest` model in blog_generator, threaded through to LLM prompt.

## Docker
```bash
make up core/knowledge_bridge
```
