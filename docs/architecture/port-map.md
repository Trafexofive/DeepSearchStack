# Service Port Registry

> Updated: 2026-05-17 · Session: DSS POC→production, core reboot

## Port Philosophy
Only the edge gateway (nginx) is exposed to the host. All internal services communicate via Docker DNS on their internal networks. No direct host port access to internal services — requests route through nginx → api_gateway.

## Core Stack (`infra_` Docker network)

| Service | Internal Port | Status | Notes |
|---|---|---|---|
| `nginx` | 80 | ⚠ port conflict | Edge gateway — needs host port 80 fix |
| `api_gateway` | 8000 | ✅ running | Route orchestration |
| `workflow_engine` | 8001 | ✅ running | Workflow execution |
| `llm_gateway` | 8002 | ✅ running | LLM provider abstraction |
| `event_bus` | 8003 | ✅ running | Redis-backed messaging |
| `inference_gateway` | 8005 | ✅ running | DeepSeek API (openai-compat) |
| `blog_generator` | 8006 | ✅ running | Content generation + research |
| `ingest` | 8008 | ✅ running | Feed ingestion |
| `knowledge_bridge` | 8010 | ✅ running | Core→DSS bridge |
| `geo_audit` | 8011 | ✅ running | Location-aware content audit |
| `sub_mq` | 8012 | ✅ running | Message queue |
| `redis` | 6379 | ✅ running | Cache and event bus backend |

## DSS Stack (`infra_` Docker network)

| Service | Internal Port | Host Port | Status | Notes |
|---|---|---|---|---|
| `*_warehouse` | 8009 | 8009 | ✅ healthy | SQLite FTS5, 13.6K entries |
| `crawler` | 8000 | 8000 | ✅ healthy | crawl4ai + retry queue |
| `web-api` | 8014 | 8014 | ✅ healthy | Aggregate + proxies + /ui |
| `search-gateway` | 8002 | 8002 | ✅ healthy | Provider routing |
| `search-agent` | 8013 | 8013 | ✅ healthy | LLM synthesis |
| `postgres` | 5432 | 5432 | ✅ healthy | DSS database |
| `redis` | 6379 | 6379 | ✅ healthy | Aggregate cache |

### Stopped (not needed for ingest/search)
| Service | Port | Reason |
|---|---|---|
| `deepsearch` | 8001 | Deprecated — proxied to web-api |
| `vector-store` | 8004 | Stopped — in-memory, restart-reset |
| `searxng` | 8888 | Stopped — not needed for warehouse-only flow |
| `whoogle` | 5000 | Stopped |
| `yacy` | 8090 | Stopped |

## Cross-Stack Connectivity

DSS and Core share the `infra_substrate-net` bridge network. Key connections:

```
blog_generator → web-api:8014    (research via aggregate)
blog_generator → warehouse:8009  (context search)
knowledge_bridge → web-api:8014  (DSS queries from core)
inference_gateway ← web-api:8014  (LLM reconciliation)
```

## Host-Accessible Ports (for dev + phone access)

| Port | Service | Access |
|---|---|---|
| 8009 | Warehouse | `curl localhost:8009/stats` |
| 8014 | Web API | `http://localhost:8014/ui` |
| 8000 | Crawler | `curl localhost:8000/health` |
| 8002 | Search Gateway | `curl localhost:8002/health` |
| 8013 | Search Agent | `curl localhost:8013/health` |
| 5432 | Postgres | DSS database |
