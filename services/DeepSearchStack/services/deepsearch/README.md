# DeepSearch Service

The core DeepSearch engine - a powerful, configurable search service that orchestrates the full pipeline: **Search → Scrape → Embed → Retrieve → Synthesize**.

## Features

- **Massive Scale**: Search 100+ results, scrape them all in parallel
- **RAG Pipeline**: Automatic embedding, vector storage, and semantic retrieval
- **LLM Synthesis**: Comprehensive answers with proper citations
- **Session Management**: Persistent conversation history in Postgres/Redis
- **Streaming Responses**: Real-time progress updates and content streaming
- **Highly Configurable**: `settings.yml` controls every aspect of behavior

## Architecture

```
┌─────────────┐
│   Request   │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────┐
│      DeepSearch Engine              │
├─────────────────────────────────────┤
│  1. Search (parallel providers)     │
│  2. Scrape (concurrent crawling)    │
│  3. Embed (vector storage)          │
│  4. Retrieve (RAG top-k)            │
│  5. Synthesize (LLM streaming)      │
└─────────────────────────────────────┘
       │
       ▼
┌─────────────┐
│  Response   │
└─────────────┘
```

## Quick Start

### Basic Search

```bash
curl -X POST http://localhost:8001/deepsearch/quick \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What are the latest developments in quantum computing?",
    "max_results": 20
  }'
```

### Streaming Search

```bash
curl -X POST http://localhost:8001/deepsearch \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Explain RAG architecture",
    "max_results": 50,
    "enable_scraping": true,
    "enable_rag": true,
    "enable_synthesis": true,
    "stream": true
  }'
```

### With Session

```bash
# Create session
SESSION_ID=$(curl -X POST http://localhost:8001/sessions \
  -H "Content-Type: application/json" \
  -d '{"metadata": {"user": "researcher"}}' | jq -r '.session_id')

# Search with session
curl -X POST http://localhost:8001/deepsearch/quick \
  -H "Content-Type: application/json" \
  -d "{
    \"query\": \"What is machine learning?\",
    \"session_id\": \"$SESSION_ID\"
  }"

# Get session history
curl http://localhost:8001/sessions/$SESSION_ID
```

## Configuration

All settings are in `settings.yml`. Key sections:

### Search Configuration

```yaml
search:
  max_results: 100           # Maximum results to fetch
  default_results: 20        # Default if not specified
  timeout: 30.0              # Provider timeout
  parallel_search: true      # Search all providers in parallel
  default_providers:
    - whoogle
    - searxng
    - duckduckgo
```

### Scraping Configuration

```yaml
scraping:
  enabled: true
  max_scrape_urls: 50        # Max URLs to scrape per search
  timeout: 15.0              # Timeout per URL
  concurrency: 10            # Parallel scraping tasks
  extraction_strategy: "markdown"
```

### RAG Configuration

```yaml
rag:
  enabled: true
  top_k: 10                  # Chunks to retrieve
  chunk_size: 1000           # Characters per chunk
  chunk_overlap: 200         # Overlap between chunks
  store_scraped_content: true
```

### Synthesis Configuration

```yaml
synthesis:
  default_provider: "ollama"
  temperature: 0.3
  max_context_tokens: 8000
  streaming: true
  timeout: 120.0
```

## API Reference

### POST `/deepsearch`

Full pipeline with streaming responses.

**Request:**
```json
{
  "query": "string",
  "max_results": 100,
  "providers": ["whoogle", "searxng"],
  "enable_scraping": true,
  "max_scrape_urls": 50,
  "enable_rag": true,
  "rag_top_k": 10,
  "enable_synthesis": true,
  "llm_provider": "ollama",
  "temperature": 0.3,
  "stream": true,
  "session_id": "uuid",
  "use_cache": true
}
```

**Response:** Server-Sent Events stream

```
data: {"type": "progress", "data": {"stage": "searching", "progress": 0.1}}
data: {"type": "progress", "data": {"stage": "scraping", "progress": 0.3}}
data: {"type": "content", "data": {"content": "Based on the search results..."}}
data: {"type": "sources", "data": {"sources": [...]}}
data: {"type": "complete", "data": {...}}
```

### POST `/deepsearch/quick`

Non-streaming, simplified response for scripts.

**Request:**
```json
{
  "query": "string",
  "max_results": 10,
  "session_id": "uuid"
}
```

**Response:**
```json
{
  "query": "string",
  "answer": "string",
  "sources": [...],
  "execution_time": 12.5,
  "total_results": 50
}
```

### Session Endpoints

- `POST /sessions` - Create session
- `GET /sessions/{id}` - Get session
- `GET /sessions` - List sessions
- `DELETE /sessions/{id}` - Delete session

### Monitoring

- `GET /health` - Health check
- `GET /config` - Current configuration
- `GET /` - API info

## Environment Variables

Override `settings.yml` with environment variables:

```bash
DEEPSEARCH_SEARCH_MAX_RESULTS=200
DEEPSEARCH_SCRAPING_ENABLED=true
DEEPSEARCH_RAG_ENABLED=true
DEEPSEARCH_SYNTHESIS_DEFAULT_PROVIDER=groq
```

Pattern: `DEEPSEARCH_<SECTION>_<KEY>` (uppercase, underscores)

## Use Cases

### CLI Tool
```python
import httpx

response = httpx.post("http://localhost:8001/deepsearch/quick", json={
    "query": "Latest AI research papers",
    "max_results": 30
})
print(response.json()["answer"])
```

### Agent Automation
```python
async def research_agent(topic):
    async with httpx.AsyncClient() as client:
        async with client.stream("POST", "http://localhost:8001/deepsearch", json={
            "query": f"Research {topic}",
            "max_results": 100,
            "enable_scraping": True,
            "enable_rag": True
        }) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    chunk = json.loads(line[6:])
                    if chunk["type"] == "content":
                        print(chunk["data"]["content"], end="", flush=True)
```

### Next.js Integration
```typescript
const response = await fetch('/api/deepsearch', {
  method: 'POST',
  body: JSON.stringify({
    query: searchQuery,
    session_id: sessionId,
    stream: true
  })
});

const reader = response.body.getReader();
const decoder = new TextDecoder();

while (true) {
  const { done, value } = await reader.read();
  if (done) break;
  
  const chunk = decoder.decode(value);
  // Process SSE chunks
}
```

## Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally
python main.py

# Run with custom config
DEEPSEARCH_CONFIG=custom-settings.yml python main.py
```

## Performance

- **Parallel Search**: All providers queried simultaneously
- **Concurrent Scraping**: 10 URLs in parallel (configurable)
- **Async Everything**: Non-blocking I/O throughout
- **Streaming**: Low latency, immediate progress feedback
- **Caching**: Redis-backed result caching (optional)

## License

MIT
