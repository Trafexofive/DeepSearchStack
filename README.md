# DeepSearchStack

> **Multi-stage search & synthesis pipeline.** Search → scrape → embed → retrieve → synthesize.
> Self-hosted, Docker-native, FOSS. 159 files, 11,408 lines of Python.

---

## Pipeline

```
User Query
  │
  ▼
search-gateway (13 providers across 8 domains)
  │
  ├─► whoogle, searxng, yacy, duckduckgo (web)
  ├─► wikipedia (encyclopedia)
  ├─► stackexchange (Q&A)
  ├─► arxiv, pubmed, crossref (academic)
  ├─► github (code)
  ├─► hackernews (social news)
  └─► reddit, internetarchive (social + archive)
  │
  ▼
ResultRanker (TF-IDF cosine similarity + domain authority scoring)
  │
  ▼
crawler (crawl4ai full-page extraction, SQLite domain-TTL cache)
  │
  ├─► knowledge-warehouse (SQLite FTS5, persistent content store)
  └─► vector-store (ChromaDB, all-MiniLM-L6-v2, 384-dim embeddings)
  │
  ▼
search-agent / web-api (LLM context-stuffing + streaming synthesis)
  │
  ▼
Cited answer with source URLs
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                         CLIENTS                                   │
│  dss.py CLI  ·  Python SDK (deepsearch)  ·  REST API  ·  Web UI  │
└─────────────────────────────┬────────────────────────────────────┘
                              │
┌─────────────────────────────▼────────────────────────────────────┐
│                    SEARCH GATEWAY (:8002)                          │
│  13 providers · TF-IDF ranking · circuit breakers · rate limits   │
└──┬──────────┬──────────┬──────────┬──────────┬───────────────────┘
   │          │          │          │          │
┌──▼────┐ ┌──▼────┐ ┌──▼────┐ ┌──▼────┐ ┌───▼──────┐
│Whoogle│ │SearXNG│ │ YaCy  │ │DuckGo │ │Wikipedia │
└───────┘ └───────┘ └───────┘ └───────┘ └──────────┘
┌───────┐ ┌───────┐ ┌──────┐ ┌──────┐ ┌──────────┐
│StackEx│ │ arXiv │ │PubMed│ │GitHub│ │HackerNews│
└───────┘ └───────┘ └──────┘ └──────┘ └──────────┘
┌───────┐ ┌───────┐ ┌──────────────┐
│Reddit │ │CrossRef│ │InternetArchive│
└───────┘ └────────┘ └──────────────┘
                              │
┌─────────────────────────────▼────────────────────────────────────┐
│                      CRAWLER (:8000)                               │
│  crawl4ai · SQLite domain-TTL cache · batch crawl · async queue   │
└──┬──────────────────────────┬─────────────────────────────────────┘
   │                          │
┌──▼──────────────────┐ ┌─────▼──────────────────────────────┐
│ KNOWLEDGE WAREHOUSE │ │        VECTOR STORE (:8004)          │
│ (:8009)              │ │  ChromaDB · all-MiniLM-L6-v2        │
│ SQLite FTS5          │ │  384-dim embeddings                 │
│ 13.6K+ entries       │ │  cosine similarity search           │
└──────────┬───────────┘ └────────────────────────────────────┘
           │
┌──────────▼───────────────────────────────────────────────────┐
│                     WEB API (:8014)                            │
│  /api/search/stream     · SSE streaming search → synthesis    │
│  /api/aggregate         · multi-provider aggregation          │
│  /api/warehouse/*       · FTS5 listing, search, content       │
│  /api/ingest/*          · URL + RSS/Atom feed ingestion       │
│  /api/facts             · consensus fact DB query             │
│  /api/metrics           · request counters, latency, gauges   │
│  /api/providers         · provider health listing             │
└──────────────────┬───────────────────────────────────────────┘
                   │
┌──────────────────▼───────────────────────────────────────────┐
│                 SEARCH AGENT (:8013)                           │
│  SynthesizerAgent v9.0.0                                      │
│  context-stuffing · source citation [1][2] · streaming chunks │
│  fallback provider routing · multi-provider resilience        │
└──────────────────────────────────────────────────────────────┘

Data Stores:
┌──────────┐ ┌──────────┐
│PostgreSQL│ │  Redis   │
│ :5432    │ │  :6379   │
│ metadata │ │ cache +  │
│          │ │ pub/sub  │
└──────────┘ └──────────┘
```

---

## Services

| Service | Port | Lines | Description |
|---------|:----:|:-----:|-------------|
| **web-api** | 8014 | 1,226 | REST orchestrator — cross-domain aggregation, streaming SSE, warehouse proxy, ingest, facts, metrics |
| **crawler** | 8000 | 583 | crawl4ai full-page extraction — SQLite domain-TTL cache, batch crawl, async retry queue |
| **search-gateway** | 8002 | 71+ | 13-provider routing — Whoogle, SearXNG, YaCy, DuckDuckGo, Wikipedia, StackExchange, arXiv, PubMed, GitHub, HackerNews, Reddit, CrossRef, InternetArchive |
| **knowledge-warehouse** | 8009 | 418 | SQLite FTS5 content repository — 13.6K+ entries, paginated listing, full-text search |
| **deepsearch** | 8001 | 302 | Deprecated shim — proxies to web-api:8014, preserves session management |
| **vector-store** | 8004 | 153 | ChromaDB — all-MiniLM-L6-v2 (384-dim), ONNX-bundled, no model download needed |
| **search-agent** | 8013 | 112 | SynthesizerAgent v9 — context-stuffing, bracket citations, streaming synthesis |
| **searxng** | — | — | Self-hosted privacy meta-search engine instance |
| **postgres** | 5432 | — | Metadata store (searchdb/searchuser) |
| **redis** | 6379 | — | Response cache + pub/sub |

---

## Search Providers (13 across 8 domains)

| Domain | Provider | Type | Rate Limit |
|--------|---------|------|:----------:|
| Web | Whoogle | Self-hosted meta-search | — |
| Web | SearXNG | Self-hosted meta-search | — |
| Web | YaCy | P2P search engine | — |
| Web | DuckDuckGo | Direct API (free, no key) | — |
| Encyclopedia | Wikipedia | Direct API | — |
| Q&A | StackExchange | Direct API | — |
| Academic | arXiv | Direct API (free) | 1 req / 3s |
| Academic | PubMed | Direct API (free) | — |
| Academic | CrossRef | Direct API (free) | — |
| Code | GitHub | Direct API (free) | — |
| Social News | HackerNews | Direct API (free) | — |
| Social | Reddit | Direct API (free) | custom UA required |
| Archive | InternetArchive | Direct API (free) | — |

### TF-IDF Ranking
Uses scikit-learn TF-IDF vectorization with cosine similarity against the query + domain authority weights (Wikipedia 0.95, arXiv/StackExchange 0.85-0.9, GitHub 0.9, Medium 0.7).

---

## Project Structure

```
DeepSearchStack/                      # 159 files, 11,408 LoC Python
│
├── infra/                            # Docker Compose stacks
│   ├── docker-compose.dss.yml        # Full stack — all services
│   ├── docker-compose.light.yml      # Minimal — API + crawler + vector-store
│   ├── docker-compose.test.yml       # Test stack — gateway + crawler + vector
│   ├── config/
│   │   ├── prom/config.yml           # Prometheus scrape configs
│   │   ├── grafana/config.yml        # Grafana datasources + dashboards
│   │   └── traefik/config.yml        # Traefik reverse proxy routes
│   └── nginx/nginx.conf              # Nginx reverse proxy fallback
│
├── services/                         # Microservices (48 Python files)
│   ├── search-gateway/
│   │   ├── main.py                   # FastAPI app — /providers, /search, /health
│   │   ├── common/models.py          # SearchProvider, SearchResult, SortMethod enums
│   │   ├── providers/
│   │   │   └── provider_manager.py   # 13 providers, circuit breakers, rate limiter
│   │   ├── ranking/
│   │   │   └── result_ranker.py      # TF-IDF, domain authority, cosine similarity
│   │   └── utils/
│   │       └── system_components.py  # MetricsCollector, CircuitBreaker
│   │
│   ├── crawler/
│   │   └── main.py                   # crawl4ai extraction + SQLite cache + forward to warehouse
│   │
│   ├── web-api/
│   │   ├── main.py                   # 1,226 lines — aggregate, stream, warehouse proxy, ingest, facts, metrics
│   │   └── app/static/index.html     # Web UI
│   │
│   ├── search-agent/
│   │   ├── main.py                   # SynthesizerAgent — context-stuffing, citations, streaming
│   │   └── common/
│   │       ├── llm_client.py          # Multi-provider LLM client with fallback
│   │       └── models.py             # Message, SearchResult, SynthesizeRequest
│   │
│   ├── vector-store/
│   │   └── main.py                   # ChromaDB — /embed, /query endpoints
│   │
│   ├── knowledge-warehouse/
│   │   └── main.py                   # SQLite FTS5 — store, search, list, stats
│   │
│   ├── deepsearch/                   # DEPRECATED — session management preserved
│   │   ├── main.py                   # Proxy to web-api:8014
│   │   ├── core/                     # Legacy search, scrape, RAG, synthesis modules
│   │   ├── storage/sessions.py       # Session persistence
│   │   ├── config/__init__.py        # Settings loader
│   │   └── settings.yml              # Service configuration
│   │
│   └── searxng/
│       └── settings.yml              # SearXNG instance configuration
│
├── sdk/                              # Client SDKs
│   ├── client.py                     # Async httpx REST client
│   ├── __init__.py                   # Package init
│   └── python/
│       ├── deepsearch.py             # DeepSearchClient — async + sync, crawl/search/completion
│       ├── __init__.py
│       ├── setup.py                  # pip install deepsearch-sdk
│       ├── requirements.txt          # aiohttp, requests, pydantic
│       ├── example.py                # Usage examples
│       └── README.md                 # SDK documentation
│
├── libs/common/                      # Shared Python library
│   ├── models.py                     # 13 providers, SortMethod, SearchResult, CrawlResult
│   ├── config.py                     # Environment config loader
│   ├── utils.py                      # Shared utilities
│   ├── __init__.py
│   ├── setup.py
│   └── requirements.txt
│
├── scripts/                          # CLI tools (22 scripts)
│   ├── dss.py                        # Main CLI — health, search, stream, ingest, facts, metrics
│   ├── dss-docs.py                   # Universal document ingestion (9+ formats → warehouse)
│   ├── dss-yt.py                     # YouTube ingest via yt-dlp (transcript + metadata)
│   ├── dss-repo.py                   # GitHub repo → warehouse (structured source files)
│   ├── dss-awesome.py                # Awesome-list ingestion (curated links → warehouse)
│   ├── dss-overnight.py              # Bulk repo cloning + code extraction
│   ├── dss-overnight-books.py        # Bulk PDF/paper ingestion (29 repos, 200 links each)
│   ├── dss-backup.py                 # Warehouse DB backup via docker cp
│   ├── dss-cleanup.py                # Warehouse garbage collection (word count filter)
│   ├── dss-enrich.py                 # Content enrichment pipeline (quality, entities, dedup)
│   ├── dss-smoke.py                  # SDK smoke test — warehouse, crawl, search
│   ├── dss-view.py                   # Interactive warehouse content viewer
│   ├── dss-health.sh                 # Quick health check script
│   ├── dss-monitor.sh                # Live monitoring dashboard
│   ├── test.sh                       # Full test suite runner
│   ├── test_suite.sh                 # Integration test suite
│   ├── test_deepsearch.sh            # DeepSearch-specific tests
│   ├── test_gateway.sh               # Gateway integration tests
│   ├── test_gateways.sh              # Multi-gateway tests
│   ├── chain_test_client.sh          # Pipeline chain test
│   ├── client.py / client.sh         # Debug CLI clients
│   └── init_cpp_service.sh           # C++ microservice scaffold generator
│
├── examples/                         # Usage examples
│   ├── query_search_agent.py         # End-to-end search + synthesis
│   ├── deepsearch_example.py         # DeepSearch API usage
│   ├── query_llm.py                  # Direct LLM gateway query
│   ├── crawler_example.py            # Crawler service usage
│   ├── chain_search.py               # Multi-step pipeline chain
│   ├── case_study_agent.py           # Case study generation
│   └── reporter_agent.py             # Research report generation
│
├── benchmarks/
│   ├── base/
│   │   ├── run_benchmarks.py         # Load test runner
│   │   ├── load_test.py              # Concurrent request load testing
│   │   ├── stress_test.sh            # Stress test script
│   │   └── BENCHMARK-REPORT.md       # Baseline performance report
│   └── realistic/
│       ├── business_intelligence_bench.py  # 70-query BI pipeline benchmark
│       ├── SUMMARY.md                     # Results: 77.3% success, 32 ops/min, 1.81s avg
│       └── intelligence_benchmark_*.json  # Raw benchmark results (5 runs)
│
├── testing/                          # Integration test suite
│   ├── test_integration.py           # Full pipeline integration tests
│   ├── test_gateways.py              # Gateway provider tests
│   ├── test_api.py                   # API endpoint tests
│   ├── test_crawler.py               # Crawler service tests
│   ├── test_openwebui.py             # Web UI tests
│   ├── health_check.sh               # Service health verification
│   ├── wait-for-it.sh                # Service readiness check
│   ├── Dockerfile                    # Test container image
│   ├── pytest.ini                    # Pytest configuration
│   └── requirements.txt              # Test dependencies (pytest, httpx, pytest-httpx)
│
├── tests/e2e/                        # End-to-end test scripts
│   ├── health_check.sh               # Full stack health check
│   ├── starter.sh                    # Stack bootstrap + verify
│   └── pytest.ini                    # Pytest config for E2E
│
├── workflows/                        # Reusable pipeline scripts
│   └── documentation-aggregator/
│       ├── main.py                   # Documentation ingestion workflow
│       ├── requirements.txt
│       └── README.md
│
├── templates/cpp-microservice/       # C++ microservice scaffold
│   ├── CMakeLists.txt
│   ├── Dockerfile
│   ├── Makefile
│   ├── README.md
│   ├── src/                          # http_server, config_manager, microservice, user_model, database
│   ├── include/                      # Header files for all modules
│   ├── tests/                        # test_microservice.cpp
│   └── examples/                     # custom_endpoint, user_service examples
│
├── firefox-extension/
│   └── manifest.json                 # Browser extension manifest
│
├── docker-compose.yml                # Root compose (full stack)
├── Makefile                          # Master Control Program (318 lines)
├── .env.example                      # Environment template
└── README.md                         # This file
```

---

## Makefile — Master Control Program

### Stacks
| Stack | Compose file | Services |
|-------|-------------|----------|
| `dss` | `infra/docker-compose.dss.yml` | Full — nginx, postgres, redis, searxng, whoogle, yacy, search-gateway, deepsearch, vector-store, crawler, knowledge-warehouse, search-agent, web-api |
| `light` | `infra/docker-compose.light.yml` | Minimal — nginx, postgres, redis, deepsearch, vector-store, crawler |
| `test` | `infra/docker-compose.test.yml` | Testing — nginx, postgres, redis, searxng, whoogle, yacy, search-gateway, deepsearch, vector-store, crawler |
| `full` | `docker-compose.yml` | Root compose |

### Commands
```bash
# Lifecycle
make up STACK=dss              # Boot stack
make down STACK=dss            # Stop + remove containers
make restart STACK=dss         # Restart all
make stop STACK=dss            # Stop without removing
make start STACK=dss           # Start stopped containers

# Build
make build STACK=dss           # Build images (Docker layer cache)
make rebuild STACK=dss         # Rebuild from scratch (no cache)
make re STACK=dss              # Build + restart
make rere STACK=dss            # Rebuild (no cache) + restart

# Monitoring
make status STACK=dss          # Container status table
make logs STACK=dss            # Tail logs (all services)
make logs STACK=dss service=crawler  # Tail specific service
make health STACK=dss          # Health status JSON
make list-stacks               # Full dashboard — all stacks, service health trees

# Debug
make shell STACK=dss service=crawler  # Interactive shell in container
make exec STACK=dss service=crawler cmd="env"  # Run command in container

# Cleanup
make clean STACK=dss           # Down + remove orphans
make fclean STACK=dss          # Down + remove volumes
make prune                     # Full system prune (interactive confirmation)

# Shortcuts
make core                      # = up STACK=dss
make core-down                 # = down STACK=dss
make core-restart              # = restart STACK=dss
```

---

## Quick Start

```bash
# 1. Configure
cp .env.example .env
# Add DEEPSEEK_API_KEY

# 2. Boot
make up STACK=dss
make status STACK=dss              # Wait for all healthy

# 3. Test
curl -s http://localhost:8014/health | python3 -m json.tool
python3 examples/query_search_agent.py
```

---

## CLI — `dss.py`

```bash
python3 scripts/dss.py health              # Health check all services
python3 scripts/dss.py search "query"       # Aggregate search
python3 scripts/dss.py stream "query"       # Streaming search (SSE)
python3 scripts/dss.py list [--domain x]    # Warehouse listing (newest first)
python3 scripts/dss.py content <id>         # View warehouse entry
python3 scripts/dss.py facts [query]        # Query consensus fact DB
python3 scripts/dss.py ingest url1 url2...  # Bulk URL ingestion
python3 scripts/dss.py crawl <url>          # Single URL crawl
python3 scripts/dss.py warehouse [query]    # Warehouse stats or search
python3 scripts/dss.py feed <rss_url>       # Ingest RSS/Atom feed
python3 scripts/dss.py metrics             # Service metrics snapshot

# Specialized tools
python3 scripts/dss-docs.py ...             # Document ingestion (PDF, DOCX, MD, HTML, etc.)
python3 scripts/dss-yt.py ...               # YouTube video/playlist ingest
python3 scripts/dss-repo.py ...             # GitHub repo → warehouse
python3 scripts/dss-awesome.py ...          # Awesome-list ingestion
python3 scripts/dss-overnight.py ...        # Bulk code repos
python3 scripts/dss-overnight-books.py ...  # Bulk PDF/paper repos
python3 scripts/dss-backup.py               # Warehouse DB backup
python3 scripts/dss-cleanup.py              # Warehouse garbage collection
python3 scripts/dss-enrich.py               # Content quality enrichment
python3 scripts/dss-smoke.py               # SDK integration smoke test
python3 scripts/dss-view.py                # Interactive warehouse browser
```

---

## Python SDK

```python
from deepsearch import DeepSearchClient, SyncDeepSearchClient

# Async (recommended)
async with DeepSearchClient(base_url="http://localhost:8014") as client:
    # Crawl
    result = await client.crawl("https://example.com", formats=["markdown"])
    print(result.content)

    # Search
    results = await client.search("What is attention mechanism?", max_results=10)
    for r in results:
        print(f"[{r.source}] {r.title}")

    # LLM completion
    answer = await client.llm_complete([
        {"role": "user", "content": "Explain quantum computing in 2 paragraphs."}
    ])

# Sync (simple scripts)
from deepsearch import crawl_sync, search_sync, llm_complete_sync
content = crawl_sync("https://example.com")
results = search_sync("AI research")
answer = llm_complete_sync([{"role": "user", "content": "Hello"}])
```

Install: `cd sdk/python && pip install -e .` or `pip install deepsearch-sdk`

---

## API Reference — web-api (:8014)

### Aggregation

```bash
# Aggregate search across providers
POST /api/aggregate
{
  "query": "attention mechanism",
  "max_results": 10,
  "include_warehouse": true,
  "reconcile": true
}

# Streaming aggregate (SSE)
POST /api/aggregate/stream
{"query": "transformer architecture"}
→ event: result, event: done
```

### Search + Synthesis

```bash
# Streaming search with LLM synthesis (SSE)
POST /api/search/stream
{
  "query": "what is RAG",
  "max_results": 5,
  "synthesis_provider": "deepseek"
}
→ event: chunk (text), event: source (url + title), event: done

# Direct LLM completion stream
POST /api/completion/stream
{
  "messages": [{"role": "user", "content": "Explain...")}],
  "provider": "deepseek"
}
→ event: chunk, event: done
```

### Warehouse

```bash
GET /api/warehouse/list?limit=20&domain=arxiv.org       # Paginated listing
GET /api/warehouse/stats                                  # Entry count, domains
GET /api/warehouse/search?q=transformers&limit=10        # FTS5 full-text search
GET /api/warehouse/content/42                             # Single entry by ID
```

### Ingestion

```bash
POST /api/ingest/urls
{
  "urls": ["https://example.com/article1", "https://example.com/article2"],
  "crawl": true
}

POST /api/ingest/feed
{
  "feed_url": "https://blog.example.com/rss",
  "limit": 20
}
```

### Operational

```bash
GET /health                               # Service health
GET /api/metrics                          # Request counts, latency, gauges
GET /api/providers                        # Provider health listing
GET /api/facts?q=bitcoin                   # Consensus fact DB query
GET /ui                                    # Web UI
```

---

## Benchmarks

### Business Intelligence Pipeline
70-query realistic benchmark suite against the full pipeline:

| Metric | Value |
|--------|-------|
| Success rate | 77.3% (17/22 operations) |
| Total duration | 41.12s |
| Throughput | 32.10 ops/min |
| Avg response time | 1.81s |
| Crawler reliability | 100% (10/10) |
| Search gateway | 100% (5/5) |
| LLM completion | 57% (3/7) — provider config dependent |

```bash
cd benchmarks/realistic
python3 business_intelligence_bench.py    # Run 70-query suite
# Results: intelligence_benchmark_*.json
```

### Base Load Tests
```bash
cd benchmarks/base
python3 run_benchmarks.py                 # Concurrent load testing
bash stress_test.sh                       # Shell-based stress test
```

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DEEPSEEK_API_KEY` | — | LLM provider key (inference-gateway) |
| `POSTGRES_DB` | `searchdb` | PostgreSQL database name |
| `POSTGRES_USER` | `searchuser` | PostgreSQL user |
| `POSTGRES_PASSWORD` | `searchpass` | PostgreSQL password |

---

## Documentation

| File | Content |
|------|---------|
| [docs/deepsearch-architecture.md](docs/deepsearch-architecture.md) | Architecture deep-dive |
| [docs/deepsearch-implementation-summary.md](docs/deepsearch-implementation-summary.md) | Implementation details |
| [docs/QUICKSTART-DEEPSEARCH.md](docs/QUICKSTART-DEEPSEARCH.md) | Getting started guide |
| [docs/crawler-guide.md](docs/crawler-guide.md) | Crawler service guide |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | Version history |
| [docs/TODO.md](docs/TODO.md) | Sprint plan & roadmap |

---

## License

MIT
