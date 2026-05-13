# SESSION_PICKUP.md — Substrate State

> Last updated: 2026-05-13 · Session: deepsearch hardening

## Running Services (DeepSearchStack)

```
dss-crawler             :8000  ✅ healthy — v2 with SQLite cache, auto-warehousing
dss-deepsearch          :8001  ✅ healthy — 5-stage pipeline, boilerplate stripping
dss-search-gateway      :8002  ✅ live    — multi-provider: SearXNG/Wikipedia/Whoogle/DDG
dss-vector-store        :8004  ✅ healthy — ChromaDB, 195 docs, delete_all endpoint
dss-knowledge-warehouse :8009  ✅ healthy — SQLite FTS5, auto-ingest from crawler
dss-searxng             :8080  ✅ live    — 14 engines, fixed language=en param
dss-whoogle             :5000  ✅ live    — unreliable (0 results on specific queries)
dss-yacy                :8090  🔴 disabled — P2P search, config disabled
dss-postgres            :5432  ✅ healthy — sessions
dss-redis               :6379  ✅ healthy — circuit breaker + cache
```

Also running (infra compose):
```
inference_gateway       :8005  ✅ — DeepSeek v4-flash
blog_generator          :8006  ✅ — AI blog gen
```

## What Changed This Session

1. **Crawler v2 deployed** — replaced v1 (no cache) with v2 (SQLite cache, 24h TTL, rate limiting, /cache/stats, /cache/clear). Auto-forwards to warehouse.
2. **SearXNG fixed** — was returning 400 on every call. Added `language=en` param to provider_manager. Now returning 72K results aggregating 14 engines.
3. **Provider diversity** — ranker uses round-robin interleaving across sources. DDG parser filters category-page URLs.
4. **Boilerplate stripping** — `scraper.py` strips nav chrome, sidebars, footers, cookie banners, "See also"/"References" sections from crawled markdown before embedding.
5. **Knowledge warehouse** — new service at :8009. SQLite FTS5 with full-text search. Crawler auto-ingests on each crawl. Endpoints: POST /ingest, GET /search?q=, GET /content/{id}, GET /stats.
6. **Healthchecks** — replaced curl-based probes with python-based (`urllib.request`) in crawler, vector-store, deepsearch. All now healthy.
7. **Vector store** — added `delete_all` endpoint, wiped 7.8K polluted docs, repopulating.
8. **TODOs added** — SubMQ/research article, AI-SEO/GEO microservice audit.

## What's Next

- [ ] Pipeline optimization — 20s per query, dominated by search + crawl + LLM. Parallelize stages, Redis query cache.
- [ ] Whoogle fix or replace — unreliable provider (0 results on specific queries).
- [ ] DeepSearch from POC to production — better error recovery, retry logic, monitoring.
- [ ] AI-SEO/GEO microservice (phase-2 todo).
- [ ] SubMQ + sub-agent research architecture article (phase-1 todo).
- [ ] Dockerfile base audit — multiple services use python:3.11-slim, could share base image.
- [ ] Vector store re-index — trigger more diverse queries to rebuild clean index (currently 195 docs).
- [ ] YaCy — either fix healthcheck/config or remove from compose.

## Quick Test

```bash
# DeepSearch
curl -X POST localhost:8001/deepsearch/quick \
  -H 'Content-Type: application/json' \
  -d '{"query":"Rust programming language features","max_results":3}'

# Warehouse search
curl 'localhost:8009/search?q=rust+ownership'

# Crawler cache
curl localhost:8000/cache/stats
```
