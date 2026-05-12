# DeepSearch (port 8001)

> **Status**: POC port — working prototype · **Source**: `services/DeepSearchStack/services/deepsearch/`

## Purpose
5-stage search orchestration engine: Search → Scrape → Embed → Retrieve → Synthesize.
Highly configurable via `settings.yml` with env var overrides.

## Architecture

```
POST /deepsearch       → SSE streaming (progress + content + sources)
POST /deepsearch/quick → JSON (scripts/automation)
```

Pipeline stages:
1. **Search** — parallel queries across multiple providers (Whoogle, SearXNG, DuckDuckGo, Wikipedia, YaCy)
2. **Scrape** — concurrent content extraction via crawler service (crawl4ai)
3. **Embed** — vector embedding via ChromaDB + sentence-transformers
4. **Retrieve** — RAG semantic search, top-k chunks
5. **Synthesize** — LLM answer generation with citations

## Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/deepsearch` | Full pipeline, SSE streaming |
| POST | `/deepsearch/quick` | Full pipeline, JSON response |
| POST | `/sessions` | Create conversation session |
| GET | `/sessions/{id}` | Get session history |
| GET | `/sessions` | List all sessions |
| DELETE | `/sessions/{id}` | Delete session |
| GET | `/health` | Health check + dependency status |
| GET | `/config` | Current configuration (sanitized) |

## Dependencies

| Service | Required | Purpose |
|---|---|---|
| search-gateway | ✅ | Multi-provider search |
| llm-gateway / inference-gateway | ✅ | LLM synthesis |
| postgres | ✅ | Session storage |
| redis | ✅ | Caching |
| vector-store | Optional | RAG functionality |
| crawler | Optional | Content scraping |

## Configuration

All settings in `services/deepsearch/settings.yml`. Env var overrides via `DEEPSEARCH_<SECTION>_<KEY>` pattern.

### Tuning presets

**Fast / low-cost:**
```yaml
search.max_results: 10
scraping.enabled: false
rag.enabled: false
synthesis.temperature: 0.1
```

**Deep research:**
```yaml
search.max_results: 200
scraping.max_scrape_urls: 100
scraping.concurrency: 20
rag.top_k: 20
synthesis.max_context_tokens: 16000
```

## Quick test

```bash
curl -X POST http://localhost:8001/deepsearch/quick \
  -H "Content-Type: application/json" \
  -d '{"query": "What is RAG?", "max_results": 10}'
```

## Files

```
services/DeepSearchStack/services/deepsearch/
├── main.py           # FastAPI app (8 endpoints, SSE streaming)
├── settings.yml      # 60+ configurable parameters
├── core/engine.py    # 5-stage orchestration engine
├── config/           # Config loader with env var overrides
├── models/           # 17 Pydantic models
├── storage/sessions.py  # Postgres/Redis session persistence
└── README.md
```
