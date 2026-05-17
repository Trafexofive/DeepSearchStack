# SESSION_PICKUP.md — Substrate State

> Last updated: 2026-05-17 · Session: DSS production hardening complete

## Current Status

**DSS (DeepSearchStack) — HEALTHY, PRODUCTION-READY**
- 7 of 12 DSS services running (lean subset for ingest + search)
- Warehouse: 13,604 entries, 240MB, 13.2M words (up from ~1,100)
- github.com dominates (12,313 entries), arxiv.org (511)
- FTS5 auto-rebuild on corruption detection
- SQLite single-writer pattern (prevents concurrency corruption)
- Nightly backup: `python3 scripts/dss-backup.py`
- Health monitor: `scripts/dss-health.sh` (cron-ready)
- Streaming search: `/api/aggregate/stream` (SSE, warehouse in 40ms)
- Web UI: `http://localhost:8014/ui` — search + warehouse browser + filters
- Fact DB: GET /api/facts (consensus facts cache)

**Substrate Core — PARTIALLY BOOTED (internal only)**
- 9 core services running on Docker network only (no host port mapping)
- Nginx port 80 conflict with host → no external access
- inference_gateway, llm_gateway, blog_generator: healthy
- event_bus, workflow_engine: healthy
- api_gateway, knowledge_bridge, geo_audit, sub_mq, ingest: running
- DSS ↔ Core cross-connectivity verified (inference, blog, event bus reachable)

## Running Services

```
DSS (5 of 12):
  knowledge-warehouse :8009  ← SQLite, 13.6K entries
  crawler             :8000  ← crawl4ai + retry queue
  web-api             :8014  ← aggregate + proxies + /ui
  search-gateway      :8002  ← provider routing
  search-agent        :8013  ← LLM synthesis
  postgres            :5432  ← DB
  redis               :6379  ← cache

Stopped (not needed for ingest):
  deepsearch, vector-store, searxng, whoogle, yacy

Core (10 of 11):
  inference-gateway :8005   ← DeepSeek API
  api_gateway       :8000   ← route orchestration
  llm_gateway       :8002   ← LLM provider abstraction
  blog_generator    :8006   ← content pipeline
  event_bus         :8003   ← Redis-based messaging
  workflow_engine   :8001   ← workflow execution
  knowledge_bridge  :8010   ← core→DSS bridge
  geo_audit         :8011   ← location-aware content audit
  sub_mq            :8012   ← message queue
  ingest            :8008   ← feed ingestion
  redis             :6379   ← core Redis

Nginx :80 — FAILED (port conflict), core not externally accessible
```

## Overnight Jobs

```bash
# Currently running:
python3 scripts/dss-overnight.py --crawl 100   # awesome-list + code repos
# Completed:
python3 scripts/dss-overnight-books.py 100      # books/papers (845 md files)

# Monitor:
tail -f /tmp/dss-overnight*.log
scripts/dss-monitor.sh
```

## Tools Built This Session

```
scripts/
  dss.py          SDK CLI — 7 commands
  dss-view.py     vim-style warehouse browser
  dss-yt.py       YouTube transcript ingest
  dss-awesome.py  awesome-list link ingester
  dss-docs.py     9-format doc ingest
  dss-repo.py     git repo clone + source extraction
  dss-overnight.py     batch awesome-list crawl
  dss-overnight-books.py  books/papers batch
  dss-cleanup.py  warehouse garbage cleanup
  dss-backup.py   nightly SQLite backup
  dss-health.sh   health monitor
  dss-monitor.sh  watch-based dashboard
```

## SDK

```python
from sdk import DSSClient

async with DSSClient() as dss:
    # Search
    result = await dss.aggregate(query="Rust", max_results=10)

    # Warehouse
    entries = await dss.list(sort="ingested_at", domain="arxiv.org")
    stats = await dss.stats()
    content = await dss.content(id=168)

    # Ingest
    await dss.ingest_urls(["https://example.com"])

    # Streaming
    async for event in dss.aggregate_stream("Rust"):
        print(event["type"])  # warehouse, external, complete
```

## Next Session

- [ ] Fix nginx port 80 conflict → expose core to host
- [ ] Wire blog_generator to consume warehouse content
- [ ] Connect DSS search results into Cortex-Prime workflows
- [ ] Firefox extension (right-click save)
- [ ] Remaining dirty git files (manifests, Makefile, settings.yml)
- [ ] OCR + audio transcription (backlog — needs model selection)
- [ ] Update port-map.md with current service topology
