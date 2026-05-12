# Substrate — Bootstrap Snapshot

> **Date**: 2026-05-12 · **Phase**: 1 (Foundation) — skeleton complete, wiring pending
> **Pi session agent**: same session that wrote all the code

---

## 1. What Exists (Everything in This Repo)

### 1.1 Repository Skeleton

| File | Status | Notes |
|---|---|---|
| `Makefile` | ✅ | `boiler-lab`, `scaffold-all`, `up`/`down`/`logs`/`ps` |
| `.env.example` | ✅ | LLM keys, DB URLs, port overrides |
| `settings.yml` | ✅ | Global config with env-var interpolation (`${VAR:-default}`) |
| `infra/docker-compose.core.yml` | ✅ | 4 services + Redis + nginx |
| `infra/nginx/nginx.conf` | ✅ | Reverse proxy to api_gateway:8000 |
| `scripts/boot_substrate.sh` | ✅ | One-command bootstrap |
| `autoload.yml` | ✅ | Auto-load manifests |
| `README.md` | ✅ | Quickstart & architecture overview |

### 1.2 Core Services (`services/`)

All four services have **working `app/main.py`** — real FastAPI apps with routes, models, and lifecycle hooks. Each has a `Dockerfile`, `docker-compose.yml`, and `requirements.txt`.

| Service | Port | Status | What's real |
|---|---|---|---|
| `api_gateway` | 8000 | ✅ scaffolded | FastAPI: `/health`, `/api/workflows/trigger`, `/api/webhooks/stripe`, CORS, JWT stub |
| `workflow_engine` | 8001 | ✅ scaffolded | FastAPI + PyYAML: loads `.workflow.yml`, DAG validation stub, executes steps |
| `llm_gateway` | 8002 | ✅ scaffolded | FastAPI: Ollama + Groq providers, fallback router, `/api/chat` |
| `event_bus` | 8003 | ✅ scaffolded | FastAPI: Redis pub/sub `EventBus` class, `/api/publish`, WebSocket fan-out at `/ws/{channel}` |

### 1.3 Manifest Plane (`manifests/`)

| Directory | Contents |
|---|---|
| `agents/scribe/` | `agent.yml`, `system-prompts/scribe.md`, `tools/mdx_writer/tool.yml` + `scripts/writer.py` |
| `agents/recon/` | `agent.yml` (scraping with Playwright tool stub) |
| `agents/sentinel/` | `agent.yml` (health ping + alert tool stub) |
| `agents/broker/` | `agent.yml` (Stripe webhook client tool stub) |
| `relics/content_vault/` | `relic.yml` (+ `app/` dir) |
| `relics/ledger_db/` | `relic.yml` (+ `app/` dir) |
| `relics/recon_graph/` | `relic.yml` (+ `app/` dir) |
| `relics/metrics_store/` | `relic.yml` (+ `app/` dir) |
| `workflows/seo_content_loop.workflow.yml` | Full 6-step DAG: web research → outline → competitor gap → MDX draft → review → publish |
| `workflows/weekly_recon_sweep.workflow.yml` | Placeholder |
| `workflows/incident_response.workflow.yml` | Placeholder |
| `monuments/content_engine/` | `monument.yml` |
| `monuments/devops_monitor/` | `monument.yml` |
| `monuments/financial_hub/` | `monument.yml` |

### 1.4 Standard Library (`std/`)

| Directory | Purpose |
|---|---|
| `manifests/tools/web_search/` | Reusable tool manifest |
| `manifests/tools/fs_read/` | Reusable tool manifest |
| `manifests/tools/json_parser/` | Reusable tool manifest |
| `manifests/relics/generic_kv_store/` | Reusable relic template |

---

## 2. What Does NOT Exist Yet

### 2.1 Not running
- **No Docker images built** — `make up` will fail until `docker compose build`
- **No dependencies installed locally** — would need `docker compose build` or `pip install -r requirements.txt` in each service
- **No Docker daemon verified** — needs Docker running

### 2.2 Stubs / TODOs
| Area | What's missing |
|---|---|
| **JWT auth** | `api_gateway` has the route stubs but no actual JWT validation |
| **Workflow engine** | DAG execution is a log statement — needs topological sort, agent dispatch, retry, event bus integration |
| **LLM gateway** | OpenAI provider not implemented, no request queuing, no token counting |
| **Event bus** | `EventBus.listen()` generator exists but isn't consumed by any service |
| **Inter-service wiring** | Services talk to nothing — `api_gateway` doesn't forward to `workflow_engine`, workflow_engine doesn't dispatch agents |
| **Agent runtime** | Agent manifests exist as YAML files — no agent runner reads them |
| **Relic runtime** | Relic manifests exist — no service creates/mounts the DBs they describe |

### 2.3 Agent implementations
The agent `agent.yml` files exist but are **spec-level**, not runtime:
- No agent bootstrap code
- No tool implementations (Playwright, Stripe, health ping)
- No LLM prompt engineering beyond the system prompt stubs

### 2.4 Monuments
- All three monument directories have `monument.yml` stubs only — no actual compose files, configs, or wiring.

---

## 3. Architecture Decisions Made

| Decision | Rationale |
|---|---|
| **Python/FastAPI** as backend | Lightweight, async-native, excellent ecosystem |
| **Single Makefile** with `boiler-lab` | Discoverable scaffolding — no heavy CLI needed |
| **Docker Compose** for orchestration | Works on any machine, no Kubernetes complexity |
| **YAML manifests** for agents/relics/workflows | Declarative, human-readable, git-diffable |
| **Provider-agnostic LLM** | Swap Ollama ↔ Groq ↔ OpenAI via env vars |
| **Decoupled relics** | Each relic is independently deployable (SQLite, Postgres, Neo4j, Redis) |
| **WebSocket fan-out** in event_bus | Real-time client updates without polling |
| **Phase-gated development** | Phase 1 Foundation → Phase 2 Wiring → Phase 3 Agent Implementation → Phase 4 Clients |
| **Monuments = cartridges** | Drop-in business units; add a directory, get a new product |

---

## 4. Pi-Agent Context (Parallel Track)

Completed in the same session but in the `~/.pi/agent/` repo (separate git history):

| Change | Impact |
|---|---|
| Stripped 8,200 lines + 15MB of dead extensions | 42 files → 20 files; 50% code reduction |
| Built sovereign `web-search.ts` | SearXNG (`:8888`), arXiv, PubMed. No API keys. SSRF-safe. |
| Built `relic-registry.ts` | YAML-based service discovery — `relic_list`, `relic_status`, `relic_register`, `relic_health_check` |
| Fixed `ask_cards` ReferenceError | `agent?.name` → `agentNow?.name` |
| Inlined `resetStateDelta` | Killed 1,048-line `system-prompt.ts` |
| Removed fork-native deps | Rewrote `orchestrator-core.ts`, `agent-lifecycle.ts` |
| All extensions validated | 20 files pass jiti loading, 26/30 tools tested operational in fresh pi session |

```
~/.pi/agent/  git log (most recent first):
  488015d9 fix: jiti inline template literal parse error
  d3953347 feat: relic-registry + sovereign web-search
  83c0b34e strip: remove all extension slop (~8,200 lines + 15MB)
  b8127d02 inline resetStateDelta, drop system-prompt.ts
  a0982166 cleanup: strip AGENTS.md, remove fork deps, drop dead extensions
  388d6d4c fix: ask_cards — 'agent is not defined'
```

---

## 5. Next Steps (Phase 2 — Motherboard Wiring)

Priority order:

1. **Build & run Docker** — `docker compose -f infra/docker-compose.core.yml build && make up`
2. **Wire api_gateway → workflow_engine** — HTTP forward on `/api/workflows/trigger`
3. **Wire workflow_engine → event_bus** — emit events on step completion
4. **Wire event_bus → WebSocket** — verify fan-out works across services
5. **Implement JWT auth** in api_gateway — protect sensitive routes
6. **Implement OpenAI provider** in llm_gateway — complete the provider triad
7. **Write a real workflow execution** — run `seo_content_loop` end-to-end with mock agents
8. **Implement one agent** — start with the simplest (sentinel: health ping → metrics_store)

### Architecture Diagram (Target State)

```
Client (TUI/Web/Android)
        │
   ┌────▼─────┐
   │api_gateway│ (8000)
   └────┬─────┘
        │ POST /api/workflows/trigger
   ┌────▼────────┐
   │workflow_engine│ (8001)
   └┬─────┬──────┘
    │     │ dispatch agent
    │     ▼
    │  ┌──────────────┐    ┌──────────┐
    │  │ agent runtime │◄───│llm_gateway│ (8002)
    │  └──┬───────────┘    └──────────┘
    │     │ persist
    │     ▼
    │  ┌─────────┐
    │  │ relics  │ (Postgres, Neo4j, Redis, SQLite)
    │  └─────────┘
    │
    │ emit event
    ▼
┌──────────┐
│event_bus │ (8003) ──WebSocket──► Client
└──────────┘
```

---

## 6. Commit This

The Substrate repo has **no git commits yet**. Run:

```bash
cd ~/repos/substrate
git init  # if not already
git add -A
git commit -m "Phase 1: Substrate skeleton — 4 services, full manifest plane, config plane"
```
