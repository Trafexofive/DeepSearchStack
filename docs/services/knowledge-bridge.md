# Knowledge Bridge — Core↔DSS Integration

> Status: running · Port: 8010 (internal) · Updated: 2026-05-17

## Purpose
Bridges Substrate Core workflows with DeepSearchStack. Provides a unified research endpoint that queries both DSS web-api and the warehouse, returning synthesized context for downstream agents.

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health + dependency check (web_api, warehouse, blog_generator) |
| POST | `/bridge/research` | Research a topic via web-api aggregate + warehouse |
| GET | `/bridge/status` | Bridge statistics + recent operations |

## Dependencies (all internal Docker DNS)
- `dss-web-api:8014` — aggregate search + reconciliation
- `dss-knowledge-warehouse:8009` — local content lookup
- `blog_generator:8006` — generates content from research

## Recent Changes
- Migrated from deprecated deepsearch:8001 to web-api:8014 aggregate
- Health check uses web-api (was deepsearch)
- Added reconcile + warehouse-first search parameters
