# Service Port Registry

| Service | Port | Network | Status | Notes |
|---|---|---|---|---|
| `nginx` | 80 | substrate-net | stub | Reverse proxy to api_gateway |
| `api_gateway` | 8000 | substrate-net | stub | FastAPI, JWT/CORS stubs |
| `workflow_engine` | 8001 | substrate-net | stub | YAML DAG parser stub |
| `llm_gateway` | 8002 | substrate-net | stub | Ollama/Groq route stubs |
| `event_bus` | 8003 | substrate-net | stub | Redis pub/sub + WebSocket |
| `inference_gateway` | 8005 | substrate-net | **✅ live** | DeepSeek v4-flash, provider pattern |
| `blog_generator` | 8006 | substrate-net | **✅ live** | AI blog gen, structured logging, SQLite tracker |
| `deepsearch` | 8001 | deepsearch_net + substrate-net | ✅ live | 5-stage research pipeline for blog gen |
| `search-gateway` | 8002 | deepsearch_net | ✅ live | Multi-provider search aggregator |
| `crawler` | 8000 | deepsearch_net | ✅ live | crawl4ai web scraper + SQLite cache v2 |
| `knowledge-warehouse` | 8009 | deepsearch_net | ✅ live | SQLite FTS5 content repository |
| `vector-store` | 8004 | deepsearch_net | ✅ live | ChromaDB persistent RAG storage |
| `redis` | 6379 | substrate-net | infrastructure | Redis 7 Alpine |

## How to check

```bash
# All running containers
docker ps --filter "network=infra_substrate-net"

# Health checks
curl localhost:8005/health  # → {"status":"ok","providers":["deepseek"],"models":2}
curl localhost:8006/health  # → {"status":"ok","generations":N}

# Dashboard
make list-stacks
```

## Adding a new port

1. Choose next available port (currently 8006 max)
2. Create `services/{name}/docker-compose.yml`
3. Add service to `infra/docker-compose.core.yml`
4. Add entry in `settings.yml` under `services:`
5. Update this file
