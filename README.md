# Substrate — Omni Indie Hacker Control Plane

A Cortex-Prime-MK1 architecture for orchestrating indie-hacker services: content generation, competitor recon, uptime monitoring, and financial webhooks.

## Architecture

```
substrate/
├── manifests/          # Declarative Config Plane
│   ├── agents/         # Autonomous agents
│   ├── relics/         # Persistence stores
│   ├── workflows/      # DAG pipelines
│   └── monuments/      # Complete sub-systems
├── services/           # Runtime "Motherboard"
│   ├── api_gateway/    # Omni-entrypoint (port 8000)
│   ├── workflow_engine/# DAG executor (port 8001)
│   ├── llm_gateway/    # LLM router (port 8002)
│   └── event_bus/      # Pub/sub (port 8003)
├── std/                # Reusable manifest library
├── clients/            # Frontends
├── infra/              # Docker, nginx, env
└── scripts/            # Boot & deploy
```

## Quick Start

```bash
# 1. Copy environment
cp .env.example .env
# Edit .env with your API keys

# 2. Boot everything
make up

# 3. Check health
curl http://localhost:8000/health
```

## Development

```bash
# Scaffold a new service
make boiler-lab NAME=my_service

# View status
make ps

# Tail logs
make logs

# Shut down
make down
```

See [AGENDA.md](AGENDA.md) for the full roadmap.

## License

MIT
