# DeepSearch Architecture & Integration Guide

## Overview

The **DeepSearch** service is the core engine of DeepSearchStack. It replaces the previous `search-agent` and `web-api` services with a single, powerful, highly-configurable orchestration layer.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        DeepSearch Service                        │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │              DeepSearch Engine (core/engine.py)            │ │
│  │                                                            │ │
│  │  Stage 1: Search     → Parallel multi-provider queries    │ │
│  │  Stage 2: Scrape     → Concurrent content extraction      │ │
│  │  Stage 3: Embed      → Vector database storage            │ │
│  │  Stage 4: Retrieve   → RAG semantic search                │ │
│  │  Stage 5: Synthesize → LLM answer generation              │ │
│  └────────────────────────────────────────────────────────────┘ │
│                                                                  │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐               │
│  │ Session    │  │ Cache      │  │ Metrics    │               │
│  │ Storage    │  │ Manager    │  │ Collector  │               │
│  └────────────┘  └────────────┘  └────────────┘               │
└──────────────────────────────────────────────────────────────────┘
           │              │              │              │
           ▼              ▼              ▼              ▼
    ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐
    │  Search    │ │    LLM     │ │   Vector   │ │  Crawler   │
    │  Gateway   │ │  Gateway   │ │   Store    │ │  Service   │
    └────────────┘ └────────────┘ └────────────┘ └────────────┘
```

## Key Features

### 1. Configurable Pipeline via `settings.yml`

Every aspect of the search pipeline is controlled through `settings.yml`:

```yaml
search:
  max_results: 100              # Scale to 100+ results
  parallel_search: true         # All providers at once
  
scraping:
  max_scrape_urls: 50          # Scrape up to 50 URLs
  concurrency: 10               # 10 parallel scrapes
  
rag:
  enabled: true                 # Use vector store
  top_k: 10                     # Retrieve 10 best chunks
  
synthesis:
  default_provider: "ollama"    # LLM provider
  temperature: 0.3              # Generation creativity
  streaming: true               # Stream responses
```

### 2. Multiple API Modes

**Streaming (for UIs):**
```bash
POST /deepsearch
# Returns: Server-Sent Events with progress + content
```

**Quick (for scripts/tools):**
```bash
POST /deepsearch/quick
# Returns: Complete JSON response
```

### 3. Session Management

Built-in conversation history with Postgres/Redis backend:

```python
# Create session
session = await client.post("/sessions")

# Search with context
response = await client.post("/deepsearch/quick", json={
    "query": "What is RAG?",
    "session_id": session["session_id"]
})

# Get history
history = await client.get(f"/sessions/{session_id}")
```

### 4. Agent-Ready Output

Structured, machine-readable responses perfect for automation:

```json
{
  "query": "string",
  "answer": "string",
  "sources": [...],
  "scraped_content": [...],
  "rag_chunks": [...],
  "execution_time": 12.5,
  "total_results": 50,
  "results_scraped": 30,
  "chunks_retrieved": 10
}
```

## Integration Patterns

### CLI Tools

```python
#!/usr/bin/env python3
import httpx, sys

response = httpx.post("http://localhost:8001/deepsearch/quick", json={
    "query": sys.argv[1],
    "max_results": 30
})
print(response.json()["answer"])
```

### Agent Workflows

```python
async def research_agent(topics: List[str]):
    results = []
    async with httpx.AsyncClient() as client:
        for topic in topics:
            resp = await client.post("http://localhost:8001/deepsearch/quick", json={
                "query": f"Research: {topic}",
                "max_results": 100,
                "enable_scraping": True,
                "enable_rag": True
            })
            results.append(resp.json())
    return results
```

### Next.js Frontend

```typescript
// app/api/search/route.ts
export async function POST(request: Request) {
  const { query, sessionId } = await request.json();
  
  const response = await fetch('http://deepsearch:8001/deepsearch', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query,
      session_id: sessionId,
      stream: true
    })
  });
  
  return new Response(response.body, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive'
    }
  });
}
```

```typescript
// components/SearchInterface.tsx
const eventSource = new EventSource(`/api/search?query=${query}`);

eventSource.onmessage = (event) => {
  const chunk = JSON.parse(event.data);
  
  if (chunk.type === 'progress') {
    setProgress(chunk.data);
  } else if (chunk.type === 'content') {
    setAnswer(prev => prev + chunk.data.content);
  } else if (chunk.type === 'sources') {
    setSources(chunk.data.sources);
  }
};
```

## Configuration Deep Dive

### Environment Variable Overrides

Any setting can be overridden via environment variables:

```bash
# In .env or docker-compose.yml
DEEPSEARCH_SEARCH_MAX_RESULTS=200
DEEPSEARCH_SCRAPING_CONCURRENCY=20
DEEPSEARCH_RAG_TOP_K=15
DEEPSEARCH_SYNTHESIS_TEMPERATURE=0.5
```

Pattern: `DEEPSEARCH_<SECTION>_<KEY>` (uppercase, dot notation → underscores)

### Per-Request Configuration

Override defaults in each request:

```json
{
  "query": "your query",
  "max_results": 150,                    // Override search.max_results
  "max_scrape_urls": 100,                // Override scraping.max_scrape_urls
  "rag_top_k": 20,                       // Override rag.top_k
  "temperature": 0.7,                    // Override synthesis.temperature
  "llm_provider": "groq",                // Override synthesis.default_provider
  "enable_scraping": true,               // Toggle scraping
  "enable_rag": true,                    // Toggle RAG
  "enable_synthesis": true               // Toggle synthesis
}
```

### Tuning for Different Use Cases

**Fast, Low-Cost:**
```yaml
search:
  max_results: 10
scraping:
  enabled: false
rag:
  enabled: false
synthesis:
  temperature: 0.1
```

**Deep Research:**
```yaml
search:
  max_results: 200
scraping:
  max_scrape_urls: 100
  concurrency: 20
rag:
  top_k: 20
synthesis:
  temperature: 0.5
  max_context_tokens: 16000
```

**Real-time Streaming:**
```yaml
search:
  max_results: 30
scraping:
  concurrency: 15
  timeout: 10.0
synthesis:
  streaming: true
  timeout: 60.0
```

## Service Dependencies

```yaml
deepsearch:
  depends_on:
    - search-gateway    # Required: Multi-provider search
    - llm-gateway       # Required: LLM synthesis
    - postgres          # Required: Session storage
    - redis             # Required: Caching
    - vector-store      # Optional: RAG functionality
    - crawler           # Optional: Content scraping
```

## Migration from Old Architecture

### Before (search-agent + web-api)

```python
# Old flow
response = await client.post("http://web-api/api/search/stream", json={
    "query": "test",
    "llm_provider": "ollama"
})
```

### After (deepsearch)

```python
# New flow - same result, more control
response = await client.post("http://deepsearch:8001/deepsearch", json={
    "query": "test",
    "llm_provider": "ollama",
    "max_results": 50,
    "enable_scraping": True,
    "enable_rag": True
})
```

## Performance Characteristics

| Operation | Parallel | Async | Configurable |
|-----------|----------|-------|--------------|
| Search providers | ✅ | ✅ | max_results, timeout |
| Content scraping | ✅ | ✅ | concurrency, max_urls |
| Vector embedding | ✅ | ✅ | chunk_size, overlap |
| LLM synthesis | ❌ | ✅ | temperature, provider |

**Typical Performance:**
- 10 results, no scraping: ~2-5 seconds
- 50 results, with scraping: ~10-15 seconds
- 100 results, full RAG: ~20-30 seconds

## Advanced Features

### Multi-Hop Reasoning (Planned)

```yaml
advanced:
  multi_hop_enabled: true
  max_hops: 3
```

Enables iterative searches where the LLM can request additional searches based on initial results.

### Query Expansion

```yaml
advanced:
  query_expansion: true
```

Uses LLM to generate related queries and combine results.

### Credibility Scoring

```yaml
advanced:
  credibility_scoring: true
```

Ranks sources by domain authority and trustworthiness.

## Monitoring & Observability

```bash
# Health check
curl http://localhost:8001/health

# Current config
curl http://localhost:8001/config

# Metrics (if enabled)
curl http://localhost:8001/metrics
```

## Best Practices

### For Production

1. **Enable caching**: Set `cache.enabled: true` with Redis
2. **Tune concurrency**: Balance `scraping.concurrency` with available resources
3. **Set timeouts**: Adjust `search.timeout`, `scraping.timeout`, `synthesis.timeout`
4. **Use sessions**: Enable `sessions.enabled: true` for conversation continuity
5. **Monitor performance**: Track `execution_time` and adjust settings

### For Development

1. **Reduce scale**: Lower `max_results` for faster iteration
2. **Disable scraping**: Speed up tests with `enable_scraping: false`
3. **Use local LLM**: Set `synthesis.default_provider: "ollama"`
4. **Stream responses**: Better debugging with `stream: true`

## Troubleshooting

**Slow responses:**
- Reduce `max_results`
- Decrease `scraping.concurrency`
- Disable RAG: `enable_rag: false`

**Empty results:**
- Check search-gateway logs
- Verify providers are healthy
- Test with fewer providers

**Synthesis errors:**
- Check llm-gateway connectivity
- Try different provider: `llm_provider: "groq"`
- Reduce context size: Lower `max_results`

## Future Enhancements

- [ ] Redis-based result caching
- [ ] Multi-hop iterative search
- [ ] Query expansion with LLM
- [ ] Fact-checking pipeline
- [ ] Source credibility scoring
- [ ] WebSocket support for streaming
- [ ] GraphQL API
- [ ] Built-in rate limiting
- [ ] Metrics export (Prometheus)
