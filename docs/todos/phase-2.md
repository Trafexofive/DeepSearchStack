# Phase 2 — Motherboard Wiring

> Status: **Current** · Priority order below

## Immediate (pick up in next session)

- [ ] **Build remaining Docker images** — api_gateway, workflow_engine, llm_gateway, event_bus
  ```bash
  make build core  # builds all 6 services
  ```
- [ ] **Full stack boot test** — `make up core` → all containers healthy
- [ ] **Wire blog_generator into workflow_engine** — trigger blog gen from a DAG step
- [ ] **Wire inference_gateway into workflow_engine** — agents use LLM via inference gateway
- [ ] **Connect event_bus** — emit events on blog generation, workflow step completion
- [ ] **Wire api_gateway → workflow_engine** — forward `/api/workflows/trigger`

## Soon After

- [ ] **Port more FIS providers to inference-gateway** — Groq, NVIDIA, Gemini, GitHub
  ```bash
  # Copy from ~/repos/free-inference-stack/services/llm_gateway/providers/
  # Add to main.py specs list
  ```
- [ ] **Implement JWT auth in api_gateway**
- [ ] **Implement OpenAI provider in llm_gateway** (or merge into inference-gateway)
- [ ] **Write a real workflow execution** — run seo_content_loop end-to-end with real blog gen

## Backlog

- [ ] Implement agent runner — reads agent.yml manifests, dispatches tools
- [ ] Implement relic provisioner — spins up DBs from relic.yml manifests
- [ ] Add Redis-backed rate limiting to api_gateway
- [ ] WebSocket fan-out from event_bus to connected clients
- [ ] Production docker-compose variant with Traefik/Caddy
