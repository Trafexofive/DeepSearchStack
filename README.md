# DeepSearchStack

> Multi-stage search pipeline: search → scrape → embed → retrieve → synthesize.
> Self-hosted, Docker-native, FOSS.

---

## Architecture

```
Query → search-gateway (SearXNG) → crawler (crawl4ai) → vector-store (ChromaDB) → knowledge-warehouse (SQLite FTS5) → search-agent (LLM synthesis)
                                                                                              ↑
                                                                                         web-api (REST + streaming)
```

### Services

| Service | Port | What it does |
|---------|:----:|--------------|
| search-gateway | 8002 | SearXNG-based multi-source search with provider manager + result ranking |
| crawler | 8000 | crawl4ai full-page extraction, SQLite domain-TTL cache |
| vector-store | 8004 | ChromaDB semantic retrieval (all-MiniLM-L6-v2, 384-dim) |
| knowledge-warehouse | 8009 | SQLite FTS5 content repository — persistent crawled page store |
| web-api | 8014 | REST API — cross-domain search/synthesize orchestrator with streaming |
| search-agent | 8013 | LLM-powered agent — federated search, context stuffing, citation tracking |
| searxng | — | Self-hosted meta-search engine (privacy-preserving) |
| postgres | 5432 | Metadata store |
| redis | 6379 | Cache + pub/sub |

---

## Project Structure

```
.
├── infra/                    # Docker Compose stacks
│   ├── docker-compose.dss.yml        # Full DSS stack
│   ├── docker-compose.light.yml      # Minimal stack (no crawl/embed)
│   └── docker-compose.test.yml       # Test-only stack
├── services/                 # Microservices
│   ├── search-gateway/       # Multi-SearXNG routing + provider abstraction
│   ├── crawler/              # crawl4ai extraction with cache
│   ├── vector-store/         # ChromaDB embedding + retrieval
│   ├── knowledge-warehouse/  # SQLite FTS5 content store
│   ├── web-api/              # REST orchestrator + Web UI
│   ├── search-agent/         # LLM search synthesis agent
│   └── searxng/              # SearXNG instance config
├── sdk/                      # Client SDKs
│   ├── client.py             # Async REST client
│   └── python/               # Python SDK (deepsearch pip package)
├── scripts/                  # CLI tools
│   ├── dss.py                # Main DSS CLI
│   ├── dss-*.py              # Sub-commands (docs, yt, repo, backup...)
│   └── test_*.sh             # Test runners
├── examples/                 # Usage examples
│   ├── deepsearch_example.py
│   ├── query_search_agent.py
│   ├── query_llm.py
│   ├── crawler_example.py
│   ├── chain_search.py
│   └── reporter_agent.py
├── libs/common/              # Shared Python library (models, config, utils)
├── workflows/                # Reusable pipeline scripts
│   └── documentation-aggregator/
├── benchmarks/               # Load tests + business intelligence benchmarks
├── testing/                  # Integration test suite
├── tests/e2e/                # End-to-end test scripts
├── templates/                # cpp-microservice scaffold
├── firefox-extension/        # Browser extension manifest
├── docker-compose.yml        # Root compose (docker-compose.yml symlink)
├── Makefile                  # Master Control Program
└── .env.example              # Environment template
```

---

## Quick Start

```bash
cp .env.example .env
# Add DEEPSEEK_API_KEY

make up STACK=dss        # Boot DSS stack
make status STACK=dss    # Container health

# Test search
curl -s -X POST http://localhost:8014/api/search \
  -H "Content-Type: application/json" \
  -d '{"query":"what is attention mechanism"}' | python3 -m json.tool

# Run example
python3 examples/query_search_agent.py
```

---

## Makefile Commands

```bash
make up STACK=dss          # Start DSS stack
make down STACK=dss        # Stop stack
make build STACK=dss       # Build images (cached)
make rebuild STACK=dss     # Rebuild images (no cache)
make logs STACK=dss        # Tail all logs
make logs STACK=dss service=crawler  # Tail specific service
make status STACK=dss      # Container status
make health STACK=dss      # Health check report
make shell STACK=dss service=crawler  # Interactive shell in container
make list-stacks           # Dashboard of all stacks
make clean STACK=dss       # Stop + remove containers
make fclean STACK=dss      # Stop + remove containers + volumes
```

Available stacks: `dss`, `light`, `test`, `full`

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DEEPSEEK_API_KEY` | — | LLM provider key |
| `POSTGRES_DB` | `searchdb` | PostgreSQL database |
| `POSTGRES_USER` | `searchuser` | PostgreSQL user |
| `POSTGRES_PASSWORD` | `searchpass` | PostgreSQL password |

---

## CLI Tools

```bash
python3 scripts/dss.py --help             # Main CLI
python3 scripts/dss-docs.py --help        # Documentation aggregator
python3 scripts/dss-yt.py --help          # YouTube ingestion
python3 scripts/dss-repo.py --help        # Repository management
python3 scripts/dss-backup.py             # Backup data
python3 scripts/dss-health.sh             # Quick health check
python3 scripts/dss-monitor.sh            # Live monitoring
```

---

## Python SDK

```python
from deepsearch import DeepSearchClient

async with DeepSearchClient(base_url="http://localhost:8014") as client:
    result = await client.search("What is a transformer?")
    print(result.text)
```

```bash
cd sdk/python && pip install -e .
```

---

## Benchmarks

```bash
# Base load tests
cd benchmarks/base && python3 run_benchmarks.py

# Business intelligence benchmarks (70-question suite)
cd benchmarks/realistic && python3 business_intelligence_bench.py
```

Results in JSON at `benchmarks/realistic/intelligence_benchmark_*.json`.

---

## Documentation

- [Architecture](docs/deepsearch-architecture.md)
- [Implementation Summary](docs/deepsearch-implementation-summary.md)
- [Crawler Guide](docs/crawler-guide.md)
- [Quickstart](docs/QUICKSTART-DEEPSEARCH.md)
- [Changelog](docs/CHANGELOG.md)
- [TODO / Sprint Plan](docs/TODO.md)

---

## License

MIT
