# DeepSearchStack

> **Multi-stage search pipeline.** Search → scrape → embed → retrieve → synthesize.
> Self-hosted, FOSS-first, Docker-native.

---

## Services

| Service | Port | What it does |
|---------|:----:|--------------|
| search-gateway | 8002 | SearXNG router — multi-source search |
| crawler | 8000 | crawl4ai full-page extraction |
| knowledge-warehouse | 8009 | FTS5 search, 13.6K entries |
| web-api | 8014 | REST API + web UI |
| search-agent | 8013 | LLM-powered search agent |
| postgres | 5432 | Metadata store |
| redis | 6379 | Cache + pub/sub |

---

## Pipeline

```
Query → search-gateway (SearXNG) → crawler (crawl4ai) → embed → warehouse → search-agent (LLM synthesis)
```

---

## Quick start

```bash
cp .env.example .env
# Edit .env — add your DEEPSEEK_API_KEY

make up core       # Boot DSS stack
make status        # Container health
make logs core     # Tail all logs
```

### Common commands

```bash
make up core/search_gateway   # Boot one service
make build core               # Build all images
make rebuild core             # Rebuild without cache
make down                     # Stop all
make fclean                   # Stop + remove volumes
```

---

## Development

```bash
make boiler-lab NAME=new_service   # Scaffold a Python/FastAPI service
```

Services are language-agnostic at the boundary (HTTP/JSON). Internally: Python/FastAPI by default.

---

## Documentation

- [Architecture overview](docs/architecture/overview.md)
- [Port map](docs/architecture/port-map.md)
- [Network topology](docs/architecture/network-topology.md)
- [Session pickup](docs/SESSION_PICKUP.md)

---

## License

MIT
