# DeepSearchStack

> Multi-stage search pipeline: search → scrape → embed → retrieve → synthesize.
> Self-hosted, Docker-native, FOSS.

---

## Services

| Service | Port | What it does |
|---------|:----:|--------------|
| search-gateway | 8002 | SearXNG router — multi-source search |
| crawler | 8000 | crawl4ai full-page extraction, SQLite cache |
| vector-store | 8004 | ChromaDB semantic retrieval (all-MiniLM-L6-v2) |
| knowledge-warehouse | 8009 | SQLite FTS5 content repository |
| web-api | 8014 | REST API + streaming search/synthesize |
| search-agent | 8013 | LLM-powered search agent |
| deepsearch | 8001 | Deprecated — proxies to web-api |
| postgres | 5432 | Metadata store |
| redis | 6379 | Cache + pub/sub |

---

## Pipeline

```
Query → search-gateway (SearXNG) → crawler (crawl4ai) → vector-store (ChromaDB) → knowledge-warehouse (SQLite FTS5) → search-agent (LLM synthesis)
```

---

## Quick start

```bash
cp .env.example .env
# Add DEEPSEEK_API_KEY

make up        # Boot all services
make status    # Container health
curl -s localhost:8014/api/search -H "Content-Type: application/json" -d '{"query":"test"}' | python3 -m json.tool
```

---

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DEEPSEEK_API_KEY` | — | LLM provider key |
| `POSTGRES_DB` | `searchdb` | PostgreSQL database |
| `POSTGRES_USER` | `searchuser` | PostgreSQL user |
| `POSTGRES_PASSWORD` | `searchpass` | PostgreSQL password |

---

## License

MIT
