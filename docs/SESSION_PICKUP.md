# SESSION_PICKUP.md — Substrate State

> Last updated: 2026-05-17 · Session: proxy stack + yt-lab + content pipeline

## Current Status

**Everything healthy — 30/30 tests green, git clean.**

### DSS (DeepSearchStack)
- 7 services running (lean subset)
- Warehouse: 13.6K entries, 240MB
- SDK: 10/10 smoke test, 11 CLI commands
- dss-enrich.py: quality scoring, entities, dedup

### Core
- 11 services running + yt-lab + proxy-rotator
- nginx on :8080 — routes /api/dss/*, /api/blog/*, /api/yt-lab/*
- Blog generator: /topics, /generate/from-warehouse
- Knowledge bridge: deepsearch→web-api migration complete

### New Services (this session)
- **yt-lab** (:8020) — YouTube automation, host networking
  - Channel ingest, video summarize (3 styles), crossref, channel watcher
  - yt-dlp in Docker, transcription interface abstracted
- **proxy-rotator** (:8888 proxy, :8030 API) — free proxy aggregation
  - 10 sources, 32 working pool, auto-rotates tinyproxy upstream
  - Bundles tinyproxy in-container
- **content pipeline** — dss-enrich.py
  - Quality scoring (0-100), entity extraction, near-duplicate detection

### Running Containers
- DSS: warehouse, crawler, web-api, search-gateway, search-agent, postgres, redis
- Core: nginx, api_gateway, inference_gateway, llm_gateway, blog_generator, event_bus, workflow_engine, knowledge_bridge, geo_audit, sub_mq, ingest, redis
- New: yt-lab, proxy-rotator
- External: searxng + redis

## Ports

| Port | Service | Access |
|------|---------|--------|
| 8080 | nginx → all | Gateway: /api/dss/*, /api/blog/*, /api/yt-lab/* |
| 8009 | warehouse | Direct + proxy via :8080 |
| 8014 | web-api | Direct + proxy via :8080 |
| 8020 | yt-lab | Direct (host network) |
| 8030 | proxy-rotator | API (internal) |
| 8005 | inference | Direct (LLM) |
| 8000 | crawler | Direct |

## Key Endpoints

```
# Gateway (single port)
http://localhost:8080/health              # Core health (8 services)
http://localhost:8080/api/dss/health      # DSS health
http://localhost:8080/api/dss/ui          # Web UI
http://localhost:8080/api/blog/topics     # Discover topics
http://localhost:8080/api/yt-lab/health   # yt-lab health

# Direct
http://localhost:8014/ui                  # Web UI
http://localhost:8020/health              # yt-lab
http://localhost:8009/stats               # Warehouse stats
http://localhost:8030/pool                # Proxy pool (internal)
```

## CLI Tools (services/DeepSearchStack/scripts/)

| Script | Purpose |
|--------|---------|
| dss.py | 11 commands (list, content, facts, search, stream, etc.) |
| dss-smoke.py | SDK smoke test (10/10) |
| dss-enrich.py | Content quality + entities + dedup |
| dss-yt.py | Host-side YouTube ingest (now superseded by yt-lab) |
| dss-view.py | Vim-style warehouse browser |
| dss-docs.py | Universal document ingestion (9 formats) |
| dss-repo.py | Git repo source extraction |
| dss-overnight.py | Batch awesome-list crawl |
| dss-backup.py | Warehouse nightly backup |
| dss-cleanup.py | Garbage content removal |

## Documented

- ✅ port-map.md — full service topology
- ✅ services/proxy.md — proxy architecture
- ✅ services/web-api.md — endpoint catalog
- ✅ services/knowledge-bridge.md — core↔DSS bridge
- ✅ yt-lab/README.md — YouTube service
- ✅ proxy-rotator/README.md — proxy rotation

## Git
- 20+ clean commits on main
- No dirty files

## Known Issues
- DSS crawler (crawl4ai) does not respect HTTP_PROXY — Reddit still blocked
- YouTube ingest requires host networking (blocked from Docker NAT)
- Warehouse FTS5 chokes on parens in search queries
