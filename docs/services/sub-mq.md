# Sub-MQ (port 8012)

> **Status**: ✅ Working · **Dependencies**: Redis

## Purpose
Lightweight Redis-backed message queue for sub-agent research pipelines. Supports pub/sub channels, blocking consumption, WebSocket streaming, and message acknowledgment.

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/queue/status` | Queue depths, consumer counts, throughput |
| POST | `/queue/publish` | Publish message to channel |
| GET | `/queue/consume/{channel}` | Blocking read (BLPOP with timeout) |
| GET | `/ws/{channel}` | WebSocket subscription |
| DELETE | `/queue/{channel}/{message_id}` | Acknowledge/delete message |

## Publish
```bash
curl -s -X POST http://localhost:8012/queue/publish \
  -H "Content-Type: application/json" \
  -d '{"channel":"research","payload":{"query":"Rust actors"}}'
```

## Consume
```bash
# Blocking read (30s timeout)
curl -s "http://localhost:8012/queue/consume/research?timeout=30"

# WebSocket streaming
websocat ws://localhost:8012/ws/research
```

## Status
```bash
curl -s http://localhost:8012/queue/status | python3 -m json.tool
```
```json
{
  "queues": {
    "research": {"depth": 3, "consumers": 1},
    "crawl": {"depth": 0, "consumers": 2}
  },
  "throughput": {"messages_per_minute": 12.5}
}
```

## Use Case: Sub-Agent Research Pipeline
```
Parent agent → publish("research", {query})
  → sub-agent consumes → processes → publishes("research.results", {...})
  → parent agent subscribes → receives results
```

## Docker
```bash
make up core/sub_mq
```

## Proxy Access (via API Gateway)
```bash
curl -s -X POST http://localhost:8000/api/queue/publish \
  -H "Content-Type: application/json" \
  -d '{"channel":"research","payload":{"query":"test"}}'
```
