# Substrate — Omni Indie Hacker Control Plane

> A Cortex-Prime-MK1 architecture for orchestrating indie-hacker services: content generation, competitor recon, uptime monitoring, and financial webhooks.

---

## Architecture Overview

```
substrate/
├── manifests/          # Declarative Config Plane (Cortex-Prime style)
│   ├── agents/         # Autonomous agents: scribe, recon, sentinel, broker
│   ├── relics/         # Decoupled persistence stores
│   ├── workflows/      # Cross-agent DAG pipelines
│   └── monuments/      # Complete sub-systems (cartridges)
├── services/           # Runtime/Service Plane ("Motherboard")
│   ├── api_gateway/    # Omni-entrypoint (TUI, WebUI, Android)
│   ├── workflow_engine/# Executes .workflow.yml DAGs
│   ├── llm_gateway/    # Provider-agnostic LLM router
│   └── event_bus/      # Internal pub/sub (Redis)
├── std/                # Standard library (reusable manifests)
├── clients/            # Frontend clients
├── infra/              # Docker Compose, nginx, environment
└── scripts/            # Bootstrapping & deployment
```

---

## Phase 1 — Foundation (Current)

### 1.1 Repository Skeleton
- [x] Create AGENDA.md (this file)
- [x] Create Makefile with `boiler-lab` target for scaffolding isolated services
- [x] Create directory structure: `manifests/`, `services/`, `std/`, `clients/`, `infra/`, `scripts/`
- [x] Create global config: `settings.yml`, `.env.example`, `infra/docker-compose.core.yml`, `infra/nginx/nginx.conf`

### 1.2 Core Services (via `make boiler-lab`)
- [x] Scaffold `services/api_gateway/` — FastAPI (routes, models, JWT/auth stubs, CORS, WebSocket)
- [x] Scaffold `services/workflow_engine/` — YAML DAG parser, executor stubs, retry logic stubs
- [x] Scaffold `services/llm_gateway/` — Provider router (Ollama, Groq), fallback logic
- [x] Scaffold `services/event_bus/` — Redis pub/sub + WebSocket fan-out (EventBus class)

### 1.3 Agent Manifests
- [x] `manifests/agents/scribe/` — Content generation (agent.yml, system prompt, tool stubs)
- [x] `manifests/agents/recon/` — Competitor scraping (agent.yml)
- [x] `manifests/agents/sentinel/` — Uptime monitoring (agent.yml)
- [x] `manifests/agents/broker/` — Finance & webhooks / Stripe (agent.yml)

### 1.4 Relics (Persistence)
- [x] `manifests/relics/content_vault/` — MDX + asset storage (relic.yml)
- [x] `manifests/relics/ledger_db/` — Stripe events & financials / Postgres (relic.yml)
- [x] `manifests/relics/recon_graph/` — Competitor entity graph / Neo4j (relic.yml)
- [x] `manifests/relics/metrics_store/` — Time-series uptime/latency / SQLite-Redis (relic.yml)

### 1.5 Workflows
- [x] `manifests/workflows/seo_content_loop.workflow.yml` — The GEO content pipeline
- [x] `manifests/workflows/weekly_recon_sweep.workflow.yml` — placeholder
- [x] `manifests/workflows/incident_response.workflow.yml` — placeholder

### 1.6 Monuments (Cartridges)
- [x] `manifests/monuments/content_engine/` — monument.yml stub
- [x] `manifests/monuments/devops_monitor/` — monument.yml stub
- [x] `manifests/monuments/financial_hub/` — monument.yml stub

---

## Phase 2 — Motherboard Wiring

- [ ] Implement `api_gateway` routes for workflow triggers, relic queries
- [ ] Implement `workflow_engine` DAG parser (YAML → directed graph → executor)
- [ ] Wire `llm_gateway` with provider fallback (Ollama ↔ Groq ↔ OpenAI)
- [ ] Connect `event_bus` for real-time agent status updates
- [ ] Write `infra/docker-compose.core.yml` to boot all services
- [ ] Write `scripts/boot_substrate.sh` — one-command startup

## Phase 3 — Agent Implementation

- [ ] **Scribe agent**: web search → outline → MDX generation → publish to content_vault
- [ ] **Recon agent**: Playwright scraper → entity extraction → recon_graph (Neo4j)
- [ ] **Sentinel agent**: Health ping → metrics_store → alert on failure
- [ ] **Broker agent**: Stripe webhook → ledger_db → event_bus notification

## Phase 4 — Clients & Polish

- [ ] `clients/tui_lab/` — Textual/Ratatui control plane
- [ ] `clients/webui/` — Dashboard (Next.js/Astro)
- [ ] `clients/android_app/` — Remote control (React Native/Flutter)
- [ ] End-to-end workflow integration tests
- [ ] Production docker-compose with Traefik/Caddy reverse proxy

---

## How It Works (Data Flow)

1. **Any client** (TUI, web, Android) hits `services/api_gateway/`
2. **Workflow trigger**: client sends `POST /api/workflows/trigger` with payload like `seo_content_loop`
3. **Workflow engine** parses the `.workflow.yml` DAG, spins up the appropriate agent(s)
4. **Agent** uses `std/` library tools (web_search, fs_read, json_parser) and LLM via `llm_gateway`
5. **Result** is persisted to the appropriate relic (content_vault, ledger_db, etc.)
6. **Event** is emitted on `event_bus` — clients see real-time updates via WebSocket

---

## Key Principles

- **Agnostic core**: Services don't know about clients; clients don't know about agents
- **Modular payloads**: Each workflow is a self-contained YAML manifest
- **Decoupled data**: Relics are independently deployable (Docker, SQLite, Neo4j)
- **Provider-agnostic LLM**: Swap Ollama ↔ Groq ↔ OpenAI via config, not code
- **Drop-in monuments**: New business models = new directory under `manifests/monuments/`
