# Substrate

> **FOSS-first AI publication + indie-hacker infrastructure.**  
> A blog at [substrate.pub](https://substrate.pub) powered by a self-hosted research pipeline.
> Deep technical guides, reproducible benchmarks, paper breakdowns. No hype, no ads, no JS bloat.

---

## What's running

### Core (12 services on `substrate-net`)
| Service | Port | What it does |
|---------|:----:|--------------|
| nginx | 8080 | Reverse proxy → all services |
| api-gateway | 8000 | Unified API entrypoint |
| inference-gateway | 8005 | LLM provider routing (DeepSeek) |
| llm-gateway | 8002 | Provider-agnostic LLM router |
| blog-generator | 8006 | AI-powered research → blog pipeline |
| geo-audit | 8011 | AI-SEO content scoring + competitor audit |
| workflow-engine | 8001 | YAML DAG executor |
| event-bus | 8003 | Redis pub/sub |
| ingest | 8008 | Content ingestion pipeline |
| knowledge-bridge | 8010 | Core ↔ DSS bridge |
| sub-mq | 8012 | Message queue |
| proxy-rotator | 8030 | Free proxy aggregation + rotation |

### DeepSearchStack (7 services on `deepsearch_net`)
| Service | Port | What it does |
|---------|:----:|--------------|
| knowledge-warehouse | 8009 | 13.6K entries, FTS5 search |
| web-api | 8014 | REST API + web UI |
| search-agent | 8013 | LLM-powered search agent |
| search-gateway | 8002 | SearXNG router |
| crawler | 8000 | crawl4ai full-page extraction |
| postgres | 5432 | DSS metadata |
| redis | 6379 | DSS cache |

### Labs & Clients
| Component | What it is |
|-----------|------------|
| yt-lab | YouTube automation — channel ingest, summarization, crossref |
| proxy-rotator | 10-source proxy aggregation + auto-rotation |
| subctl | Go CLI binary (6MB, stdlib only) |
| Python SDK | Async SDK for `services/DeepSearchStack/` |
| C++ SDK | Header-only (`substrate.hpp`) |
| webui | Dashboard (Next.js/Astro) |
| tui_lab | Terminal control plane (Textual) |

---

## The blog — [substrate.pub](https://substrate.pub)

11 posts across 5 categories — news, guides, benchmarks, research, opinion.  
Content is hand-written MDX or generated via the research pipeline (DeepSearch → crawl → embed → DeepSeek synthesis). Every generated post is human-reviewed.

**Stack:** Astro + MDX + nginx. Zero client-side JavaScript. Full RSS. No tracking.

**AI-SEO optimized:** FAQPage schema, comparison tables, author credentials, unique excerpts per article. All AI crawlers allowed (GPTBot, ClaudeBot, PerplexityBot, Google-Extended).

---

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    CLIENTS                                │
│  subctl (Go) · Python SDK · C++ SDK · WebUI · TUI        │
└─────────────────────┬────────────────────────────────────┘
                      │
┌─────────────────────▼────────────────────────────────────┐
│                 API GATEWAY (:8000)                        │
│         Routes → Services · Auth · WebSocket              │
└──────┬──────────┬──────────┬──────────┬──────────────────┘
       │          │          │          │
┌──────▼──┐ ┌─────▼────┐ ┌───▼────┐ ┌──▼──────────┐
│Workflow │ │Inference │ │  LLM   │ │  Event Bus  │
│ Engine  │ │ Gateway  │ │Gateway │ │  (Redis)    │
│ :8001   │ │ :8005    │ │ :8002  │ │  :8003      │
└────┬────┘ └────┬─────┘ └───┬────┘ └──────┬──────┘
     │           │            │             │
┌────▼───────────▼────────────▼─────────────▼──────────────┐
│              CONTENT PIPELINE                             │
│  blog-generator (:8006) · geo-audit (:8011)               │
│  ingest (:8008) · knowledge-bridge (:8010)                │
└──────────────────────┬───────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────┐
│              DEEPSEARCHSTACK (bridge-connected)            │
│  SearXNG → crawler → embed → warehouse → search agent    │
│  13.6K entries · 240MB vector store · FTS5 search         │
└──────────────────────────────────────────────────────────┘
```

---

## Quick start

```bash
cp .env.example .env
# Edit .env — add your DEEPSEEK_API_KEY

make up        # Boot everything
make status    # Container health
curl localhost:8080/health
```

### Common commands

```bash
make up core/inference_gateway   # Boot one service
make logs core/blog_generator    # Tail logs
make build core                  # Build all images
make rebuild core                # Rebuild without cache
make down                        # Stop all
make fclean                      # Stop + remove volumes
```

---

## Development

```bash
make boiler-lab NAME=new_service   # Scaffold a Python/FastAPI service
```

Services are language-agnostic at the boundary (HTTP/JSON). Internally: Python/FastAPI by default, Rust/Go/TypeScript where it fits.

LLM providers plug in via a provider pattern — drop a file into `services/inference-gateway/providers/`, import in `main.py`, done. Any OpenAI-compatible API works unchanged.

---

## Documentation

Full docs in [`docs/`](docs/):
- [Architecture overview](docs/architecture/overview.md)
- [Port map](docs/architecture/port-map.md)
- [Network topology](docs/architecture/network-topology.md)
- [Provider pattern](docs/architecture/provider-pattern.md)
- [Development setup](docs/development/setup.md)
- [ADR index](docs/decisions/)
- [Phase roadmap](docs/planning/AGENDA.md)

---

## License

MIT — use it however you want.
