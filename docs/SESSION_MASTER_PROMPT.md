# Substrate — New Session Master Prompt

> Paste this into a fresh pi session to resume work.
> Last handoff: 2026-05-12 · Session author: CleverLord

---

## PROJECT: Substrate — Omni Indie Hacker Control Plane

**Repo**: `~/repos/substrate/`  
**Docs root**: `~/repos/substrate/docs/` — start by reading `README.md` and `SESSION_PICKUP.md`

```
substrate/
├── docs/                 ← All architecture, ADRs, todos, diagrams
├── services/             ← 6 services, 2 working (inference-gateway, blog-generator)
├── infra/                ← docker-compose.core.yml, nginx
├── manifests/            ← Declarative agent/relic/workflow YAML specs
├── Makefile              ← v2 Master Control Program
├── settings.yml          ← Global config
└── .env                  ← API keys (gitignored)
```

---

## WHAT'S WORKING (verified e2e)

| Service | Port | What it does |
|---|---|---|
| inference-gateway | 8005 | LLM router: DeepSeek v4-flash, provider pattern, 3 routing modes |
| blog-generator | 8006 | AI blog gen, structured JSON logging, SQLite token/cost tracker |

Services run on `substrate-net` Docker bridge network. Start with:
```bash
cd ~/repos/substrate
export DEEPSEEK_API_KEY=$(grep DEEPSEEK_API_KEY ~/.zshrc | cut -d= -f2 | tr -d '"' | tr -d "'")
echo "DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY" >> .env
make up core
# or just the working ones:
docker compose -f infra/docker-compose.core.yml up -d inference_gateway blog_generator
```

Verify:
```bash
curl localhost:8005/health  # → providers: ["deepseek"], models: 2
curl localhost:8006/health  # → {"status":"ok","generations":N}
```

---

## WHAT NEEDS WORK (Phase 2 — Wiring)

Priority order:

1. **Build all Docker images** — `make build core`
2. **Full stack boot** — `make up core` → all 6 services on substrate-net
3. **Wire blog_generator → workflow_engine** — trigger blog gen from a `workflow.yml` DAG step
4. **Wire inference_gateway into workflow_engine** — agents call LLM via inference gateway
5. **Connect event_bus** — emit events on generation, publish via WebSocket
6. **Wire api_gateway → workflow_engine** — forward triggers through the entrypoint

See `docs/todos/phase-2.md` for the full list.

---

## PATTERNS TO FOLLOW

### Service scaffold (when creating new services)
```
services/{name}/
├── Dockerfile            ← FROM python:3.12-slim, COPY + pip install + uvicorn CMD
├── docker-compose.yml    ← build: ., ports, env_file: ../../.env
├── requirements.txt      ← fastapi uvicorn pydantic httpx (minimal)
├── app/main.py           ← FastAPI with /health, lifespan, structured logging
├── config/.gitkeep       ← Mounted read-only
└── volumes/data/.gitkeep ← Persistent data
```

### Adding an LLM provider
1. Copy provider from `~/repos/free-inference-stack/services/llm_gateway/providers/`
2. Drop into `services/inference-gateway/providers/`
3. Import in `main.py`, add to `specs` list
4. Add static models in `discover_models()`

### Structured logging
```python
from app.logger import RequestLogger, new_request_id
rlog = RequestLogger(logging.getLogger(__name__), rid)
rlog.info(f"Action: {detail}")
# Output: {"ts":"...","level":"INFO","logger":"...","msg":"...","rid":"abc123",...}
```

---

## KEY CONSTRAINTS

- **Arch Linux, bare metal** — no cloud services, no SaaS dependencies
- **Docker Compose** for orchestration — no Kubernetes
- **Python 3.12 + FastAPI** for all services — consistent stack
- **DeepSeek v4-flash** is the primary LLM (`deepseek-chat` alias) — $0.27/M input, $1.10/M output
- **Self-hosted** whenever possible — SearXNG on :8888, Gitea, PostgreSQL, Redis
- **Makefile v2** for all operations — `make [target] <stack>[/service]` syntax
- **Provider pattern** for LLM routing — drop-in, not rewrite
- **YAML manifests** for agents/relics/workflows — declarative, git-diffable

---

## OPERATOR PREFERENCES (from USER.md)

- Direct, no fluff. Skip preamble. Technical vocabulary without explanation.
- Code blocks liberally. Show the actual thing.
- Call out tradeoffs, failure modes, edge cases.
- Push back if wrong — once, clearly, with a reason.
- Production-grade, not tutorial-grade.
- Short and correct beats long and fluffy.
- FOSS preferred. Self-hosted over SaaS. CLI over GUI.
- No "Great question!" or "I hope this helps!"

---

## WORKFLOW FOR THIS SESSION

```
1. Verify state
   ├── Read docs/README.md and docs/SESSION_PICKUP.md
   ├── docker ps → confirm inference_gateway + blog_generator running
   └── curl localhost:8005/health && curl localhost:8006/health

2. Build remaining images
   └── make build core

3. Boot full stack
   └── make up core

4. Wire workflow_engine → inference_gateway + blog_generator
   ├── workflow_engine main.py: add HTTP client to call inference-gateway
   ├── Update seo_content_loop.workflow.yml to use real endpoints
   └── Test: POST /api/execute with workflow trigger

5. Wire event_bus
   ├── blog_generator emits event on generation complete
   ├── event_bus receives via /api/publish
   └── Verify WebSocket fan-out at /ws/{channel}

6. Wire api_gateway → workflow_engine
   └── Forward POST /api/workflows/trigger → workflow_engine:8001/api/execute

7. Port more providers from FIS
   └── Copy Groq, NVIDIA, Gemini, GitHub providers into inference-gateway
```

---

## META: How to operate in this session

1. Every turn: `agent_inbox` once, then `agent_status_log` with the specific action.
2. Read docs before coding — `docs/` has architecture, ADRs, port map, todos.
3. Commit after every meaningful change — atomic commits with descriptive messages.
4. After any file change, verify it loads (jiti for .ts, Python import for .py, docker compose config for .yml).
5. Prefer `make` targets over raw docker compose commands.
6. When doing multi-step work, checkpoint with commits at each step — never batch unrelated changes.
7. If alignment is needed, use `ask_cards` — operator prefers direct communication, not hand-holding.
8. Services communicate via HTTP on `substrate-net` — service name = hostname (e.g., `http://inference_gateway:8005`).
9. Pi-agent extensions are in `~/.pi/agent/` (separate repo) — currently stable, don't touch unless asked.
10. Before ending the session, update `docs/SESSION_PICKUP.md` with the new state.

---

## KNOWN ISSUES

- `api_gateway`, `workflow_engine`, `llm_gateway`, `event_bus` have stub `main.py` files — they have routes but don't call downstream services
- `event_bus` has a working `EventBus` class but nothing publishes to it yet
- The 3 non-stub workflow YAMLs (`weekly_recon_sweep`, `incident_response`) are placeholders
- Agent manifests exist as YAML but no agent runner reads them
- Relic manifests exist but no provisioner creates the DBs

---

*The Great Work Continues. — GODSPEED.*
