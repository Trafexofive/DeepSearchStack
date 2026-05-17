# Event Bus (port 8003)

> **Status**: ✅ Working · **Dependencies**: Redis

## Purpose
Internal pub/sub backbone. Thin FastAPI wrapper around Redis pub/sub for inter-service communication. Agents emit events; services subscribe to channels. Also exposes WebSocket for real-time client updates.

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | `{"status":"ok","channels":["..."]}` |
| POST | `/publish` | Publish event to a channel |
| GET | `/subscribe/{channel}` | SSE stream of events |
| WS | `/ws/{channel}` | WebSocket subscription |

## Event Model
```json
{
  "channel": "workflow.step.completed",
  "data": {"workflow_id": "abc", "step": "research", "output": "..."},
  "source": "workflow_engine"
}
```

## Channels (30+ registered)
| Channel | Publisher |
|---|---|
| `post_generated` | blog_generator |
| `step.{started,completed,failed,skipped}` | workflow_engine |
| `workflow.{started,completed,failed}` | workflow_engine |
| `draft.created` | ingest |

## Docker
```bash
make up core/event_bus
```

## E2E Test
```bash
# Publish
curl -s -X POST http://localhost:8003/publish \
  -H "Content-Type: application/json" \
  -d '{"channel":"test","data":{"msg":"hello"}}'

# Subscribe (SSE)
curl -s http://localhost:8003/subscribe/test
```
