# Service Port Registry

## Port Philosophy
Only the edge gateway (nginx) is exposed to the host. All internal services communicate via Docker DNS on their internal networks. No direct host port access to internal services — requests route through nginx → api_gateway.

## Core Stack (`substrate-core_`)

| Service | Internal Port | Host Port | Network | Status | Notes |
|---|---|---|---|---|---|
| `nginx` | 80 | **80** | substrate-net | **✅ live** | Edge gateway — single entry point |
| `api_gateway` | 8000 | — | substrate-net | **✅ live** | 9-service reverse proxy, aggregate health |
| `workflow_engine` | 8001 | — | substrate-net | **✅ live** | networkx DAG executor, 5-step pipeline |
| `llm_gateway` | 8002 | — | substrate-net | **✅ live** | Ollama/Groq router |
| `event_bus` | 8003 | — | substrate-net | **✅ live** | Redis pub/sub + WebSocket, 30+ events |
| `inference_gateway` | 8005 | — | substrate-net | **✅ live** | DeepSeek v4-flash, 2 models |
| `blog_generator` | 8006 | — | substrate-net | **✅ live** | AI blog gen + SQLite tracker, 17 gens |
| `ingest` | 8008 | — | substrate-net | **✅ live** | RSS/Atom feed polling → blog gen, 4 drafts |
| `knowledge-bridge` | 8010 | — | substrate-net | **✅ live** | DSS research → blog gen bridge |
| `geo-audit` | 8011 | — | substrate-net | **✅ live** | AI-SEO/GEO content scorer |
| `sub-mq` | 8012 | — | substrate-net | **✅ live** | Sub-agent message queue (Redis-backed) |
| `redis` | 6379 | — | substrate-net | infra | Redis 7 Alpine |

## DSS Stack (`substrate-dss_`)

| Service | Internal Port | Host Port | Network | Status | Notes |
|---|---|---|---|---|---|
| `deepsearch` | 8001 | 8001 | deepsearch_net, bridge-net | **✅ live** | 5-stage research pipeline |
| `search-gateway` | 8002 | 8002 | deepsearch_net | **✅ live** | Multi-provider search aggregator |
| `crawler` | 8000 | 8000 | deepsearch_net | **✅ live** | crawl4ai + SQLite cache v2 |
| `vector-store` | 8004 | 8004 | deepsearch_net | **✅ live** | ChromaDB persistent RAG |
| `knowledge-warehouse` | 8009 | 8009 | deepsearch_net | **✅ live** | SQLite FTS5 content store |
| `searxng` | 8080 | — | deepsearch_net | **✅ live** | 14-engine meta search |
| `whoogle` | 5000 | — | deepsearch_net | ✅ live | Google proxy (unreliable) |
| `postgres` | 5432 | — | deepsearch_net | **✅ live** | Internal DB |

## How to check

```bash
# Core stack health
curl localhost:8005/health   # inference_gateway
curl localhost:8006/health   # blog_generator
curl localhost:8003/health   # event_bus

# DSS stack health
curl localhost:8001/health   # deepsearch
curl localhost:8004/health   # vector-store
curl localhost:8009/health   # knowledge-warehouse

# Dashboard
make list-stacks
make list-services core
make list-services dss
```

## Adding a new port

1. Choose next available port (currently 8013+ for core, 8010+ for new)
2. Decide which stack the service belongs to
3. Create `services/{name}/docker-compose.yml`
4. Add service to the appropriate compose file
5. Add entry in `settings.yml` under `services:`
6. Update this file
