# Session Pickup — How to Resume Work

> **Last updated**: 2026-05-12 · **Session**: pi session building Substrate + cleaning pi-agent extensions

## Quick Start (in a new pi session)

```bash
cd ~/repos/substrate

# 1. Ensure Docker is running
docker info

# 2. Set the DeepSeek key (from host env or paste it)
export DEEPSEEK_API_KEY=$(grep DEEPSEEK_API_KEY ~/.zshrc 2>/dev/null | cut -d= -f2 | tr -d '"' | tr -d "'")
echo "DEEPSEEK_API_KEY=$DEEPSEEK_API_KEY" >> .env

# 3. Start working services
make up core

# If only inference + blog needed:
docker compose -f infra/docker-compose.core.yml up -d inference_gateway blog_generator

# 4. Verify
curl http://localhost:8005/health  # inference-gateway
curl http://localhost:8006/health  # blog-generator
```

## Key Context (read these first)

| File | Why |
|---|---|
| [planning/AGENDA.md](planning/AGENDA.md) | The 4-phase roadmap |
| [planning/BOOTSTRAP_SNAPSHOT.md](planning/BOOTSTRAP_SNAPSHOT.md) | Full inventory of what exists |
| [architecture/overview.md](architecture/overview.md) | System design |
| [todos/phase-2.md](todos/phase-2.md) | Current work items |

## Current State Snapshot

### Working (verified e2e)
- **inference-gateway** (port 8005): DeepSeek v4-flash via `deepseek-chat` model, OpenAI-compatible API
- **blog-generator** (port 8006): Generates blog posts via inference-gateway, structured JSON logging, SQLite token/cost tracker

### Scaffolded (stubs, not wired)
- **api-gateway** (port 8000): FastAPI entrypoint with route stubs
- **workflow-engine** (port 8001): YAML DAG parser stub
- **llm-gateway** (port 8002): Simple Ollama/Groq route stubs
- **event-bus** (port 8003): Redis pub/sub with WebSocket fan-out (EventBus class exists)
- All manifests: agents, relics, workflows, monuments have YAML files

### Repo Layout
```
substrate/
├── docs/                  # ← YOU ARE HERE. All docs, ADRs, todos
├── services/              # 6 services, 2 working
├── infra/                 # docker-compose.core.yml, nginx
├── manifests/             # Declarative agent/relic/workflow YAML
├── Makefile               # v2 Master Control Program
├── settings.yml           # Global config
└── .env.example           # Template (copy to .env)
```

### Docker State
- Two images built: `inference-gateway-inference_gateway`, `blog_generator-blog_generator`
- Network: `substrate-net` (bridge)
- Running: inference_gateway on 8005, blog_generator on 8006
- Stop all: `docker compose -f infra/docker-compose.core.yml down`

### Pi-Agent (separate repo: `~/.pi/agent/`)
- Extensions cleaned up: 20 files, 6,854 lines (was 42 files, 13k lines, 15MB)
- Working: web-search (SearXNG :8888), relic-registry, retry-guard, ask_cards (fixed)
- See `BOOTSTRAP_SNAPSHOT.md` §4 for details

## Immediate Priorities (Phase 2 — Wiring)

1. **Wire blog_generator → workflow_engine**: trigger blog generation from a workflow manifest
2. **Wire inference-gateway into workflow_engine agent dispatch**: agents call LLM via inference-gateway
3. **Build remaining Docker images**: api_gateway, workflow_engine, llm_gateway, event_bus
4. **Connect event_bus**: emit events on blog generation, workflow completion
5. **Add more providers to inference-gateway**: copy Groq/NVIDIA/Gemini providers from `~/repos/free-inference-stack/`

## Files to `.gitignore`
- `.env` (contains API keys)
- `*.db` (SQLite runtime data)
- `__pycache__/`
