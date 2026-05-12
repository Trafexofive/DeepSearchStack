# AGENTS.md — Substrate Operating Rules

> Loaded by pi agents working in `~/repos/substrate/`.
> These rules encode patterns discovered during bootstrap. Follow them unless the operator overrides in-session.

## 0. Turn Start Protocol

At the start of every turn:
1. `agent_inbox` once.
2. `agent_status_log` with the specific action for this turn.
3. Decide: concrete task, exploration, or alignment check.

No real task (empty prompt, greeting only) → log `no task assigned — halting cleanly` and stop.

## 1. Working Alongside the Operator

### Operator Profile (CleverLord)
- Systems programmer, Arch Linux, FOSS maximalist, bare metal.
- Languages: C/C++/Python/Bash primary. Uses what fits.
- Prefers: direct communication, production-grade code, technical vocabulary without explanation.
- Dislikes: fluff, preamble, "Great question!", "I hope this helps!", tutorial-level explanations.

### Communication Rules

| Rule | Requirement |
|---|---|
| Be direct | Skip preamble. Get to the answer. |
| Use code blocks | Show the actual thing — code, not prose about code. |
| Push back once | If the operator is wrong, say so clearly with a reason. Don't repeat. |
| Production-grade | Working code, not tutorial stubs. Proper error handling or nothing. |
| Short over long | Correct and concise beats thorough and fluffy. |
| No service pushing | Don't suggest cloud/SaaS when self-hosted is viable. Don't suggest Docker for bare-metal problems. |
| No re-explaining | Don't explain the operator's stack back to them. In-session context wins over USER.md. |

## 2. Repository Topology

```
substrate/
├── docs/              ← All documentation. Read first, write often.
│   ├── README.md      ← Doc index — start here each session
│   ├── SESSION_PICKUP.md ← How to resume work
│   ├── architecture/  ← Overview, data flow, port map, provider pattern
│   ├── decisions/     ← Architecture Decision Records (ADRs)
│   ├── services/      ← Per-service docs
│   ├── development/   ← Guides: setup, Makefile, Docker, adding providers
│   ├── operations/    ← Deployment, monitoring, backup
│   └── todos/         ← Phase-by-phase task tracking
├── services/          ← Each service is an isolated Docker container
│   └── {name}/
│       ├── Dockerfile
│       ├── docker-compose.yml
│       ├── requirements.txt / Cargo.toml / package.json
│       ├── app/       ← Application code
│       ├── config/    ← Mounted read-only
│       └── volumes/   ← Persistent data (gitignored .db files)
├── infra/             ← Core compose, nginx, env
├── manifests/         ← Declarative YAML: agents, relics, workflows, monuments
├── Makefile           ← v2 Master Control Program
├── settings.yml       ← Global config
└── .env.example       ← Template — .env is gitignored
```

## 3. Git Workflow

| Rule | Requirement |
|---|---|
| Atomic commits | One logical change per commit. Don't batch unrelated changes. |
| Descriptive messages | Format: `area: what changed — why`. The commit body explains context. |
| No blind staging | Never `git add -A` without reviewing `git diff --cached --stat` first. Stage explicitly. |
| No secrets | `.env` is gitignored. API keys, tokens, passwords never enter the repo. |
| No runtime data | `*.db`, `__pycache__/`, `*.pyc`, `node_modules/`, `.make.cache` are gitignored. Verify before committing. |
| Commit after milestones | After a service builds, after a feature works e2e, after docs are written — commit immediately. |
| Checkpoint often | Multi-step work gets checkpoint commits at each step. |

### Commit message format
```
area: brief description

Optional body with context — why this change, what was learned,
alternatives considered.
```

Examples:
```
feat: inference-gateway — DeepSeek-powered LLM router
fix: jiti inline template literal parse error
docs: full documentation tree — ADRs, diagrams, session master prompt
```

## 4. Service Architecture

### Pattern
Every service follows the same skeleton:

```
services/{name}/
├── Dockerfile              ← FROM python:3.12-slim, COPY . , pip install, CMD uvicorn
├── docker-compose.yml      ← Standalone run (build: ., ports, env_file: ../../.env)
├── requirements.txt        ← Minimal: fastapi, uvicorn, pydantic, httpx (+ domain deps)
├── app/
│   ├── __init__.py
│   ├── main.py             ← FastAPI app with /health, lifespan, routes
│   ├── logger.py           ← Structured JSON logging with request IDs
│   └── [domain modules]    ← Service-specific logic
├── config/.gitkeep         ← Mounted read-only config
└── volumes/data/.gitkeep   ← Persistent runtime data
```

### Rules

| Rule | Requirement |
|---|---|
| One service, one container | Each service is independently buildable and runnable. |
| FastAPI + uvicorn | Consistent Python stack. Use type hints. Use Pydantic models. |
| Structured logging | JSON with request correlation IDs (rid). Use the `app/logger.py` pattern. |
| /health endpoint | Every service exposes `GET /health` returning status JSON. |
| Service-to-service via HTTP | Services on substrate-net resolve each other by name: `http://inference_gateway:8005`. |
| Docker Compose for orchestration | `infra/docker-compose.core.yml` boots everything. Per-service compose files for standalone dev. |
| Makefile for operations | `make up core`, `make logs core/blog_generator`, etc. Prefer `make` over raw docker commands. |
| Language-agnostic at boundary | Services speak HTTP/JSON. Internal implementation can be Python, Rust, Go, TypeScript — whatever fits. |

### When adding a new service
```bash
make boiler-lab NAME=new_service
# → generates Dockerfile, docker-compose.yml, requirements.txt, app/main.py
# Then: add to infra/docker-compose.core.yml, settings.yml, docs/services/, docs/architecture/port-map.md
```

## 5. LLM Provider Pattern

Adding a provider to inference-gateway:
1. Drop file into `services/inference-gateway/providers/`
2. Import in `main.py`, add to `specs` list
3. Optionally add static models in `discover_models()`

Any OpenAI-compatible API works unchanged — just set `base_url` and `default_headers`.

### Cost awareness
- DeepSeek v4-flash: ~$0.27/M input, ~$1.10/M output
- Token tracking is built into blog_generator — use the same pattern for new services
- Never burn tokens on test calls that don't need them — reduce `max_tokens` for smoke tests

## 6. Testing & Verification

| Rule | Requirement |
|---|---|
| Build before claiming success | `docker compose build` must succeed before saying something works. |
| E2E test for new endpoints | After adding a route, curl it. After wiring services, test the full chain. |
| Health check after boot | `curl localhost:{port}/health` after `make up core/{service}`. |
| Config validation | `docker compose -f infra/docker-compose.core.yml config --quiet` before committing compose changes. |
| Python imports | `python3 -c "import app.main"` in the service directory after file changes. |
| TypeScript/jiti | `node -e "const {createJiti}=require('@mariozechner/jiti'); createJiti('file.ts')('file.ts')"` for pi-agent extensions. |
| No live quota probes | Don't test API rate limits. Use safe/offline checks unless the operator approves. |
| Smoke test syntax | Use minimal tokens: `max_tokens: 10, temperature: 0.0` for ping tests. |

### Verification checklist
```bash
# 1. Config valid?
docker compose -f infra/docker-compose.core.yml config --quiet

# 2. Image builds?
make build core/{service}

# 3. Service starts?
make up core/{service} && sleep 2

# 4. Health responds?
curl -s localhost:{port}/health | python3 -m json.tool

# 5. E2E works?
curl -s -X POST localhost:{port}/endpoint -H "Content-Type: application/json" -d '{...}' | python3 -m json.tool
```

## 7. Documentation

| Rule | Requirement |
|---|---|
| Docs live in `docs/` | Not README sprawl. Not comment blocks. Structured, navigable documentation tree. |
| Write as you code | After a feature works, document it immediately. Don't batch docs at the end. |
| Update SESSION_PICKUP.md | Before ending a session, update with new state — what changed, what works, what's next. |
| ADRs for decisions | Any architectural choice that takes >2 minutes of discussion gets an ADR in `docs/decisions/`. |
| Diagrams in Mermaid | Embed mermaid blocks in markdown. Render with the mermaid CLI or GitHub's native renderer. |
| Per-service docs | When a service graduates from stub to working, fill its `docs/services/{name}.md`. |
| Todo tracking | Update `docs/todos/phase-{N}.md` checkboxes. Don't let AGENDA.md and reality drift. |
| No stale TODOs | Either do it or remove it. Don't leave `# TODO` comments in code without a tracking issue. |

### Documentation template for new features
```markdown
# Feature Name

> Status: [stub | working | deprecated] · Dependencies: [list]

## Purpose
One sentence.

## Endpoints / API
| Method | Path | Description |
|---|---|---|

## How to test
```bash
curl ...
```
```

## 8. Environment & Secrets

| Rule | Requirement |
|---|---|
| `.env` is gitignored | Never commit `.env`. Template is `.env.example`. |
| API keys from host env | `export DEEPSEEK_API_KEY=$(grep ... ~/.zshrc)` — pull from shell, inject into `.env`. |
| Docker env_file | Services load `../../.env` — one source of truth. |
| No in-code secrets | API keys, passwords, tokens in code = instant revert. |
| Self-hosted first | SearXNG on :8888, local PostgreSQL/Redis, Gitea. Only use external APIs when self-hosting isn't viable. |

## 9. Makefile v2 Usage

```bash
# Core operations
make up core                  # Boot entire substrate
make up core/api_gateway      # Boot specific service in core context
make up api_gateway           # Boot standalone (per-service compose)

# Monitoring
make status core              # Container status
make logs core/blog_generator # Follow logs
make health core              # Health report
make list-stacks              # Full dashboard
make list-services core       # Deep per-service detail

# Build
make build core               # Build all images (cached)
make rebuild core             # Build all images (no cache)

# Cleanup
make down core                # Stop all
make fclean core              # Stop + remove volumes
```

The cache file `.make.cache` remembers the last-used stack — subsequent `make` commands without a stack argument reuse it.

## 10. Session Close Protocol

Before ending a session:
1. Commit all working changes with descriptive messages.
2. Verify nothing dirty remains: `git status --short` should be clean (runtime state stashed).
3. Update `docs/SESSION_PICKUP.md` with:
   - Services running (ports, status)
   - What was built this session
   - What's next
4. Update `docs/todos/phase-{N}.md` checkboxes.
5. If major architecture changed, add an ADR or update existing ones.
6. Log: `session closed — state saved in docs/SESSION_PICKUP.md`

---

*The Great Work Continues. — GODSPEED.*
