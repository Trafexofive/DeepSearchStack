# Search Gateway (port 8002 POC / 8003 test)

> **Status**: POC port — working prototype · **Source**: `services/DeepSearchStack/services/search-gateway/`

## Purpose
Multi-provider search aggregator. Queries Whoogle, SearXNG, DuckDuckGo, Wikipedia, and YaCy in parallel.
Fuses, deduplicates, and ranks results.

## Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/search` | Query multiple providers |
| GET | `/health` | Health check |
| GET | `/providers` | Provider status list |

## Providers

| Provider | Type | Notes |
|---|---|---|
| whoogle | Self-hosted meta-search | Privacy-respecting Google proxy |
| searxng | Self-hosted meta-search | Configurable multi-engine |
| duckduckgo | API | Free, rate-limited |
| wikipedia | API | Encyclopedia |
| yacy | P2P search | Slower, decentralized (default: disabled) |

## Architecture

```
POST /search
  → ProviderManager.query_provider() × N (parallel via asyncio.gather)
  → fuse_and_deduplicate (by URL)
  → ResultRanker (scoring)
  → limit to max_results
```

Features: Redis-backed circuit breaker, provider weighting, metrics collection.

## Quick test

```bash
curl -X POST http://localhost:8002/search \
  -H "Content-Type: application/json" \
  -d '{"query": "Rust programming language", "max_results": 10, "providers": ["whoogle", "duckduckgo"]}'
```

## Files

```
services/DeepSearchStack/services/search-gateway/
├── main.py              # FastAPI app
├── common/models.py     # SearchGatewayRequest, SearchResult
├── providers/           # SearchProviderManager + individual providers
├── ranking/             # ResultRanker (relevance scoring)
├── utils/               # CircuitBreaker, MetricsCollector
└── requirements.txt
```
