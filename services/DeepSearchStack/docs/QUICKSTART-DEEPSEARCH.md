# Quick Start: DeepSearch Service

## Prerequisites

- Docker & Docker Compose
- Git

## Step 1: Start the Stack

```bash
cd infra
docker-compose up -d
```

This will start:
- ✅ Core infrastructure (Postgres, Redis)
- ✅ AI services (Ollama, LLM Gateway)
- ✅ Search backends (Whoogle, SearXNG, YaCy)
- ✅ Utility services (Vector Store, Crawler, Search Gateway)
- ✅ **DeepSearch** (main service)

## Step 2: Wait for Services to be Healthy

```bash
# Check health
docker-compose ps

# Watch logs
docker-compose logs -f deepsearch
```

Wait for: `✓ DeepSearch service ready`

## Step 3: Test the Service

```bash
# Quick health check
curl http://localhost:8001/health | jq

# Run integration tests
cd ..
./scripts/test_deepsearch.sh
```

## Step 4: Try Examples

### Quick Search (CLI)

```bash
python3 examples/deepsearch_example.py quick "What is quantum computing?"
```

### Streaming Search (Real-time)

```bash
python3 examples/deepsearch_example.py stream "Explain machine learning"
```

### With Sessions

```bash
python3 examples/deepsearch_example.py session "What is AI?"
```

## API Usage

### Simple Query

```bash
curl -X POST http://localhost:8001/deepsearch/quick \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Latest developments in AI",
    "max_results": 20
  }' | jq
```

### Advanced Query

```bash
curl -X POST http://localhost:8001/deepsearch/quick \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Deep dive into RAG architecture",
    "max_results": 100,
    "enable_scraping": true,
    "max_scrape_urls": 50,
    "enable_rag": true,
    "rag_top_k": 15,
    "llm_provider": "ollama",
    "temperature": 0.3
  }' | jq
```

### Streaming (SSE)

```bash
curl -X POST http://localhost:8001/deepsearch \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is Python?",
    "stream": true
  }'
```

## Configuration

### Default Settings

The service uses `services/deepsearch/settings.yml` with sensible defaults:

- **Max results**: 100 (can scale to 200+)
- **Scraping**: Up to 50 URLs with 10 concurrent workers
- **RAG**: Enabled with top-10 chunk retrieval
- **LLM**: Ollama (local) with fallback to Groq/Gemini
- **Sessions**: Enabled with Postgres storage

### Override via Environment

```bash
# In .env or export
export DEEPSEARCH_SEARCH_MAX_RESULTS=200
export DEEPSEARCH_SCRAPING_CONCURRENCY=20
export DEEPSEARCH_RAG_TOP_K=15
export DEEPSEARCH_SYNTHESIS_TEMPERATURE=0.5

# Restart service
docker-compose restart deepsearch
```

### Override per Request

Every setting can be overridden in the API request - see examples above.

## Troubleshooting

### Service won't start

```bash
# Check dependencies
docker-compose ps

# View logs
docker-compose logs deepsearch

# Common issues:
# - Postgres not ready: wait 30s
# - LLM Gateway timeout: wait for Ollama to download models
# - Port conflict: change 8001 in docker-compose.yml
```

### Slow responses

```yaml
# Edit services/deepsearch/settings.yml
search:
  max_results: 20  # Reduce from 100
scraping:
  enabled: false   # Disable for faster results
rag:
  enabled: false   # Disable for simpler pipeline
```

### Empty results

```bash
# Test search gateway
curl http://localhost:8002/health

# Test with single provider
curl -X POST http://localhost:8001/deepsearch/quick \
  -d '{"query": "test", "providers": ["wikipedia"], "max_results": 5}'
```

## Next Steps

### For CLI/Automation

Use the `/deepsearch/quick` endpoint - it returns complete JSON responses perfect for scripts.

### For Next.js Frontend

1. Create an API route that proxies to DeepSearch
2. Use `/deepsearch` endpoint for SSE streaming
3. Implement session management with `/sessions/*` endpoints

See `docs/deepsearch-architecture.md` for detailed integration patterns.

### For Agents

The structured JSON output includes:
- `answer`: Synthesized response
- `sources`: All search results with metadata
- `scraped_content`: Full text content
- `rag_chunks`: Retrieved semantic chunks
- `execution_time`: Performance metrics

Perfect for multi-agent workflows and automation.

## Architecture

```
Request → DeepSearch Engine
  ↓
  ├─ Stage 1: Parallel Search (100+ results)
  ├─ Stage 2: Concurrent Scraping (50 URLs)
  ├─ Stage 3: Vector Embedding
  ├─ Stage 4: RAG Retrieval (top-k)
  └─ Stage 5: LLM Synthesis (streaming)
  ↓
Response (JSON or SSE)
```

## Documentation

- **Full API**: `services/deepsearch/README.md`
- **Architecture**: `docs/deepsearch-architecture.md`
- **Implementation**: `docs/deepsearch-implementation-summary.md`
- **OpenAPI**: http://localhost:8001/docs (when running)

## Support

The service exposes:
- `/health` - Service health and dependencies
- `/config` - Current configuration
- `/docs` - Interactive API documentation
- `/` - API endpoints list

## Performance Tips

**For speed**: Disable scraping and RAG
**For accuracy**: Enable all features with high max_results
**For cost**: Use local Ollama provider, lower max_results
**For scale**: Increase concurrency, use Redis caching

Default settings balance all four.
