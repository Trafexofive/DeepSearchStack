# SESSION_PICKUP.md — Substrate State

> Last updated: 2026-05-13 · Session: Phase 2 wiring complete + SDKs

## Stack Topology

Two decoupled stacks on separate networks, cross-connected via `infra_substrate-net` bridge.

```
┌─ CORE (substrate-core_substrate-net) ─────────────────────┐
│  api_gateway :8000  ·  workflow_engine :8001               │
│  llm_gateway :8002  ·  event_bus :8003                     │
│  inference_gateway :8005  ·  blog_generator :8006           │
│  redis :6379                                                │
│  knowledge_bridge :8010  ·  geo_audit :8011                 │
│  sub_mq :8012  ·  ingest :8008                              │
│  nginx :80  ←── gateway (sole host-exposed port)            │
└─────────────────────────────────────────────────────────────┘
         │
    infra_substrate-net (shared bridge)
         │
┌─ DSS (deepsearch_net) ────────────────────────────────────┐
│  deepsearch :8001  ·  crawler :8000                        │
│  search-gateway :8002  ·  vector-store :8004               │
│  knowledge-warehouse :8009  ·  postgres :5432               │
│  redis :6379  ·  searxng :8080                              │
│  whoogle :5000  ·  yacy :8090 (unhealthy)                   │
└─────────────────────────────────────────────────────────────┘
```

## Running Services

### Core Stack (12/12 OPERATIONAL)
```
api_gateway          :8000  ✅ — 9-service reverse proxy, aggregate health
workflow_engine      :8001  ✅ — networkx DAG executor, 5-step pipeline
llm_gateway          :8002  ✅ — Ollama/Groq router
event_bus            :8003  ✅ — Redis pub/sub + WebSocket, 30+ events
inference_gateway    :8005  ✅ — DeepSeek v4-flash, 2 models
blog_generator       :8006  ✅ — AI blog gen, SQLite tracker, 17 gens
ingest               :8008  ✅ — RSS/Atom feed polling → blog gen, 4 drafts
redis                :6379  ✅ — Redis 7 Alpine
nginx                :80    ✅ — Edge gateway (only exposed port)
knowledge_bridge     :8010  ✅ — DSS research → blog gen bridge
geo_audit            :8011  ✅ — AI-SEO/GEO content scorer
sub_mq               :8012  ✅ — Sub-agent message queue (Redis)
```

### DSS Stack (8/8 RUNNING, yacy unhealthy)
```
deepsearch           :8001  ✅ — 5-stage research pipeline
search-gateway       :8002  ✅ — Multi-provider search aggr.
crawler              :8000  ✅ — crawl4ai + SQLite cache v2
vector-store         :8004  ✅ — ChromaDB
knowledge-warehouse  :8009  ✅ — SQLite FTS5 content store
searxng              :8080  ✅ — 14 engines
whoogle              :5000  ✅ — Google proxy (unreliable)
postgres             :5432  ✅ — Internal DB
redis                :6379  ✅ — Cache + circuit breaker
yacy                 :8090  🔴 — P2P search (slow start, always unhealthy)
```

## What Changed This Session

### Phase 2 Wiring (3/4 complete)
1. **api_gateway v0.2.0** — Full reverse proxy. 9 services routed through `/api/{service}/*` with per-service prefix mapping. Aggregate health probes all 9 services. 120s timeout.
2. **Event publishing fixed** — blog_generator emits `post_generated`, workflow_engine emits `step.{started,completed,failed,skipped}` and `workflow.{started,completed,failed}`. Orphan `infra-*` DNS conflict resolved.
3. **workflow_engine v0.2.0** — Real DAG execution via networkx (cycle detection, topological sort). Variable resolution (`$params.x`, `$steps.id.output`). Step dispatch table maps agent+task → HTTP endpoints. Full 5-step `seo_content_loop` runs e2e in 76s.
4. **JWT auth** — Not done (skipped for Content Command Center). Placeholder routes exist.

### Ingest Service
5. **ingest (:8008)** — RSS/Atom feed polling → dss-crawler content extraction → blog_generator researched post → MDX draft storage. 3 arXiv feeds configured. 4 papers auto-blogged. Fixed `.mdx` glob bug, structured logger kwargs support.

### Stubs Filled (8 files → working)
10. System prompts for recon, broker, sentinel agents
11. Monument manifests for content_engine, devops_monitor, financial_hub
12. Workflow manifests for incident_response, weekly_recon_sweep
13. Scribe tool script (writer.py) — MDX generation, audit, publish

### AI Slop Index
14. Slop inventory artifact created — 30+ empty/stub files catalogued. 8 filled this session. 13 doc files + 2 phase todos remain empty.

### Fixes Applied
15. **HIGH**: knowledge-bridge research context was silently dropped. Added `context` field to blog_generator's GenerateRequest, threaded through to LLM prompt.
16. MEDIUM: Ingest compose stale container name fixed.
17. MEDIUM: Warehouse error handling wrapped in try/except.
18. MEDIUM: knowledge_bridge + geo_audit added to substrate-net for service-name DNS.
19. MEDIUM: nginx proxy headers fixed.

## What's Next (by priority)

### Content Command Center (post-wiring)
- [ ] subctl CLI — Go/Rust binary that talks to api_gateway
- [ ] TUI dashboard (Textual) — real-time control plane
- [ ] Web dashboard — lightweight status/post browser
- [ ] CI/CD blog pipeline — git-based MDX → geo-audit → auto-publish

### Phase 2 — Remaining
- [ ] JWT auth in api_gateway (placeholder routes exist)
- [ ] Agent runner — reads agent.yml manifests, dispatches tools
- [ ] Relic provisioner — spins up DBs from relic.yml manifests

### Hardening
- [ ] Port more providers to inference-gateway (Groq, NVIDIA, Gemini)
- [ ] Proxy/VPN stack for DSS crawler privacy
- [ ] Reddit/HN forum monitoring for content ideation

## Quick Test

```bash
# make all (boot everything)
make all
make health core
make health dss

# knowledge-bridge: research
curl -X POST localhost:80/bridge/research \
  -H 'Content-Type: application/json' \
  -d '{"topic":"Rust async runtimes","max_sources":2}'

# geo-audit: score content
curl -X POST localhost:80/audit/content \
  -H 'Content-Type: application/json' \
  -d '{"content":"# My Article\n\nContent here...","keyword":"keyword"}'

# sub-mq: publish and consume
curl -X POST localhost:80/queue/publish \
  -H 'Content-Type: application/json' \
  -d '{"channel":"research","payload":{"query":"test"}}'
```
