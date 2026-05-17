# API Gateway (port 8000)

> **Status**: ✅ Working · **Dependencies**: All internal services

## Purpose
Omni-entrypoint reverse proxy. Routes external requests to internal services via Docker DNS. Aggregates health, proxies WebSocket connections, and handles JWT auth (placeholder).

## Route Map

| External Path | Internal Target |
|---|---|
| `/api/workflows/*` | `workflow_engine:8001` |
| `/api/llm/*` | `llm_gateway:8002` |
| `/api/events/*` | `event_bus:8003` |
| `/api/inference/*` | `inference_gateway:8005` |
| `/api/blog/*` | `blog_generator:8006` |
| `/api/ingest/*` | `ingest:8008` |
| `/api/bridge/*` | `knowledge_bridge:8010` |
| `/api/audit/*` | `geo_audit:8011` |
| `/api/queue/*` | `sub_mq:8012` |
| `/ws/events/*` | `event_bus:8003` (WebSocket) |
| `/ws/queue/*` | `sub_mq:8012` (WebSocket) |

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Aggregate health — probes all 9 services |
| GET | `/api/{service}/*` | Proxied to internal service |
| GET | `/ws/{service}/*` | WebSocket proxy |

## Health Response
```json
{
  "status": "healthy",
  "services": {
    "workflow_engine": "ok",
    "llm_gateway": "ok",
    "event_bus": "ok",
    "inference_gateway": "ok",
    "blog_generator": "ok",
    "ingest": "ok",
    "knowledge_bridge": "ok",
    "geo_audit": "ok",
    "sub_mq": "ok"
  }
}
```

## Auth
JWT placeholder routes exist (`/auth/login`, `/auth/refresh`). Not yet implemented — skipped for Content Command Center.

## Docker
```bash
make up core/api_gateway
```

## E2E Test
```bash
# Aggregate health
curl -s http://localhost:8000/health | python3 -m json.tool

# Proxy to any service
curl -s http://localhost:8000/api/blog/stats | python3 -m json.tool

# WebSocket proxy
websocat ws://localhost:8000/ws/events/health
```
