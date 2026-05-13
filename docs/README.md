# Substrate — Documentation

## Session Pickup
→ **[SESSION_PICKUP.md](SESSION_PICKUP.md)** — Resume work in a new pi session. Start here.

## Clients
| Path | Language | Type |
|---|---|---|
| [subctl](../../clients/subctl/) | Go (stdlib only) | CLI binary (6MB) |
| [sdk/python/substrate/](../../sdk/python/substrate/) | Python 3.12+ | Async SDK |
| [sdk/cpp/substrate.hpp](../../sdk/cpp/substrate.hpp) | C++17 | Header-only |

## Architecture
| File | Purpose |
|---|---|
| [overview.md](architecture/overview.md) | System architecture & design |
| [data-flow.md](architecture/data-flow.md) | How data moves between services |
| [port-map.md](architecture/port-map.md) | Service port registry |
| [network-topology.md](architecture/network-topology.md) | Docker network design |
| [provider-pattern.md](architecture/provider-pattern.md) | How LLM providers plug in |
| [language-agnostic.md](architecture/language-agnostic.md) | Language-agnostic microservices + SDKs |

## Services
| File | Port | Status |
|---|---|---|
| [api-gateway.md](services/api-gateway.md) | 8000 | ✅ working |
| [workflow-engine.md](services/workflow-engine.md) | 8001 | ✅ working |
| [llm-gateway.md](services/llm-gateway.md) | 8002 | stub |
| [event-bus.md](services/event-bus.md) | 8003 | ✅ working |
| [inference-gateway.md](services/inference-gateway.md) | 8005 | ✅ working |
| [blog-generator.md](services/blog-generator.md) | 8006 | ✅ working |
| [ingest.md](services/ingest.md) | 8008 | ✅ working |
| [deepsearch.md](services/deepsearch.md) | 8001 | POC |
| [search-gateway.md](services/search-gateway.md) | 8002 | POC |
| [crawler.md](services/crawler.md) | 8000 | POC |
| [vector-store.md](services/vector-store.md) | 8004 | POC |

## Manifests
| File | Purpose |
|---|---|
| [agent-format.md](manifests/agent-format.md) | Agent YAML schema |
| [relic-format.md](manifests/relic-format.md) | Relic YAML schema |
| [workflow-format.md](manifests/workflow-format.md) | Workflow DAG schema |
| [monument-format.md](manifests/monument-format.md) | Monument cartridge schema |

## Development
| File | Purpose |
|---|---|
| [setup.md](development/setup.md) | Getting started, prerequisites |
| [makefile-guide.md](development/makefile-guide.md) | Makefile v2 usage |
| [docker-guide.md](development/docker-guide.md) | Docker compose patterns |
| [adding-a-provider.md](development/adding-a-provider.md) | Adding a new LLM provider |

## Operations
| File | Purpose |
|---|---|
| [deployment.md](operations/deployment.md) | Production deployment |
| [monitoring.md](operations/monitoring.md) | Logs, metrics, health checks |
| [backup-restore.md](operations/backup-restore.md) | Makefile backup targets |

## Decisions (ADRs)
| File | Decision |
|---|---|
| [001](decisions/001-python-fastapi.md) | Python/FastAPI as backend runtime |
| [002](decisions/002-docker-compose-orchestration.md) | Docker Compose for orchestration |
| [003](decisions/003-provider-pattern.md) | Provider pattern for LLM routing |
| [004](decisions/004-deepseek-primary.md) | DeepSeek v4-flash as primary model |

## Prototyping
| File | Purpose |
|---|---|
| [experiments.md](prototyping/experiments.md) | Log of prototypes and spikes |
| [fis-migration.md](prototyping/fis-migration.md) | Free Inference Stack → Substrate notes |

## Planning & Todos
| File | Purpose |
|---|---|
| [AGENDA.md](planning/AGENDA.md) | 4-phase roadmap |
| [BOOTSTRAP_SNAPSHOT.md](planning/BOOTSTRAP_SNAPSHOT.md) | Full state snapshot |
| [phase-1.md](todos/phase-1.md) | Foundation — mostly done |
| [phase-2.md](todos/phase-2.md) | Wiring — current focus |
| [phase-3.md](todos/phase-3.md) | Agent implementation |
| [phase-4.md](todos/phase-4.md) | Clients & polish |

## Diagrams
→ `diagrams/` — Mermaid sources, excalidraw exports, architecture diagrams.
