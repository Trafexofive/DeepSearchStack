# Architecture Overview

## System Design

```
┌─────────────────────────────────────────────────────────┐
│                      CLIENTS                            │
│   TUI (pi-agent)  ·  WebUI (Next.js)  ·  Android        │
└──────────────────────┬──────────────────────────────────┘
                       │ HTTP / WebSocket
┌──────────────────────▼──────────────────────────────────┐
│                   API GATEWAY (:8000)                    │
│   Auth (JWT)  ·  Rate Limiting  ·  Route Forwarding     │
└──┬───────────┬──────────┬──────────┬────────────────────┘
   │           │          │          │
   ▼           ▼          ▼          ▼
┌──────┐ ┌──────────┐ ┌─────────┐ ┌──────────┐
│BLOG  │ │WORKFLOW  │ │LLM      │ │INFERENCE │
│GEN   │ │ENGINE    │ │GATEWAY  │ │GATEWAY   │
│:8006 │ │:8001     │ │:8002    │ │:8005     │
│ ✅   │ │ STUB     │ │ STUB    │ │ ✅        │
└──────┘ └────┬─────┘ └─────────┘ └──────────┘
              │
       ┌──────▼──────────┐
       │   EVENT BUS      │
       │   :8003 (Redis)  │
       └──────────────────┘
              │
    ┌─────────┼─────────┐
    ▼         ▼         ▼
┌───────┐ ┌──────┐ ┌─────────┐
│REDIS  │ │NGINX │ │ RELICS  │
│:6379  │ │:80   │ │(DBs)    │
└───────┘ └──────┘ └─────────┘
```

## Design Principles

1. **Agnostic core**: Services don't know about clients; clients don't know about agents
2. **Provider pattern for LLM**: Any provider can be added by dropping a class into `providers/` — same interface, swap at will
3. **Declarative manifests**: Agents, workflows, relics are YAML files — git-diffable, version-controlled
4. **Docker Compose orchestration**: Single network (`substrate-net`), one command to boot everything
5. **Structured logging**: JSON with request correlation IDs across all services

## Key Patterns

### Provider Pattern (LLM Routing)
```
providers/
├── provider_base.py       ← Token bucket + retry
├── deepseek_provider.py   ← DeepSeek (OpenAI-compatible)
├── groq_provider.py       ← (copy from FIS when needed)
└── ...
```
Every provider implements: `chat()`, `chat_stream()`, `default_headers`

### Service Scaffolding
```
services/{name}/
├── Dockerfile             ← FROM python:3.12-slim
├── docker-compose.yml     ← Standalone or via core compose
├── requirements.txt
├── app/main.py            ← FastAPI entrypoint
├── config/                ← Mounted read-only
└── volumes/data/          ← Persistent data
```

### Manifests → Runtime
```
manifests/workflows/seo_content_loop.workflow.yml
  → workflow_engine parses YAML into DAG
    → dispatches agents
      → agents call inference-gateway for LLM
        → results persisted to relics
```

## Current Focus: Phase 2 — Wiring

What needs connecting:
1. `blog_generator` ↔ `workflow_engine` (trigger blog gen from a DAG step)
2. `workflow_engine` ↔ `inference_gateway` (agents use LLM)
3. `event_bus` ↔ all services (real-time updates)
4. `api_gateway` ↔ all services (unified entrypoint)
