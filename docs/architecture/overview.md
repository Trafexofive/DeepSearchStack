# Architecture Overview

## System Design

```
                              CLIENTS
               TUI (pi-agent) · CLI (subctl) · SDK
                              │
                         nginx :80
                              │
┌─────────────────── API GATEWAY :8000 ───────────────────┐
│         9-service reverse proxy + aggregate health       │
└──┬────────┬────────┬────────┬────────┬────────┬─────────┘
   │        │        │        │        │        │
   ▼        ▼        ▼        ▼        ▼        ▼
┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐
│WORKFL│ │LLM   │ │EVENT │ │INFER │ │BLOG  │ │INGEST│
│ENGINE│ │GATEWY│ │BUS   │ │GATEWY│ │GEN   │ │      │
│:8001 │ │:8002 │ │:8003 │ │:8005 │ │:8006 │ │:8008 │
│  ✅  │ │  ✅  │ │  ✅  │ │  ✅  │ │  ✅  │ │  ✅  │
└──────┘ └──────┘ └──┬───┘ └──────┘ └──────┘ └──────┘
                     │
    ┌────────────────┼────────────────┐
    ▼                ▼                ▼
┌──────────┐ ┌────────────┐ ┌──────────────┐
│KNOWLEDGE │ │ GEO-AUDIT  │ │   SUB-MQ     │
│BRIDGE    │ │            │ │              │
│:8010 ✅  │ │ :8011 ✅   │ │ :8012 ✅     │
└────┬─────┘ └────────────┘ └──────────────┘
     │
     │  DSS Bridge (deepsearch_net)
     ▼
┌─────────────────────────────────────────────────────────┐
│                    DSS STACK                             │
│  deepsearch :8001  ·  crawler :8000                      │
│  search-gateway :8002  ·  vector-store :8004             │
│  knowledge-warehouse :8009  ·  searxng :8080             │
│  whoogle :5000  ·  postgres :5432                        │
└─────────────────────────────────────────────────────────┘
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

## Current Status

**Phase 2 Wiring — Complete (2026-05-13)**
- 12/12 core services operational
- 8/9 DSS services operational (yacy unhealthy)
- Full e2e: api_gateway → workflow_engine → deepsearch → blog_generator → event_bus
- `seo_content_loop` 5-step pipeline executes in ~76s

**Next: Content Command Center**
- subctl CLI, TUI dashboard, web dashboard
- CI/CD blog pipeline
- Relic provisioner (declarative DBs from YAML)
