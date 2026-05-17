# Web API — DeepSearchStack Unified Gateway

> Status: healthy · Port: 8014 (host-accessible) · Updated: 2026-05-17

## Purpose
Unified entry point for all DeepSearchStack operations. Aggregates search across warehouse, vector store, and external providers. Proxies warehouse content for single-port access. Serves the web frontend.

## Endpoints

### Search
| Method | Path | Description |
|---|---|---|
| POST | `/api/aggregate` | Full search — warehouse → external → reconcile |
| POST | `/api/aggregate/stream` | SSE streaming — warehouse hits in ~40ms |
| POST | `/api/search` | Alias for aggregate |
| POST | `/api/search/stream` | Streaming search → synthesis |

### Warehouse (proxied from port 8009)
| Method | Path | Description |
|---|---|---|
| GET | `/api/warehouse/search?q=&limit=` | FTS5 search |
| GET | `/api/warehouse/list?sort=&order=&domain=` | Paginated listing with sort/filter |
| GET | `/api/warehouse/content/{id}` | Full entry by ID |
| GET | `/api/warehouse/stats` | Entry count, domains, size |

### Facts
| Method | Path | Description |
|---|---|---|
| GET | `/api/facts?q=` | Query consensus fact database |

### Ingestion
| Method | Path | Description |
|---|---|---|
| POST | `/api/ingest/urls` | Bulk URL crawl + warehouse store |
| POST | `/api/ingest/feed` | RSS/Atom feed ingestion |

### System
| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health + dependency check |
| GET | `/api/metrics` | Request counters, latency timers |
| GET | `/ui` | Mobile-friendly web frontend |
| GET | `/` | Service info |
| GET | `/api/providers` | Active search providers |

## Progressive Cascade
1. Fact DB (0ms cached) → Warehouse (FTS5, ~40ms) → External providers (3-5s) → LLM reconcile (15-20s)

## Dependencies
- `knowledge-warehouse:8009` — content storage
- `search-gateway:8002` — external provider routing
- `search-agent:8013` — LLM synthesis (optional)
- `inference_gateway:8005` — LLM reconciliation
- `crawler:8000` — page crawling for ingest
