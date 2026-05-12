# Vector Store (port 8004 POC / 8005 test)

> **Status**: POC port — minimal working prototype · **Source**: `services/DeepSearchStack/services/vector-store/`

## Purpose
ChromaDB-backed embedding storage with sentence-transformers for semantic search.
Feeds the RAG pipeline in DeepSearch.

## Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/embed` | Embed documents into ChromaDB |
| POST | `/query` | Semantic search (query_text, n_results) |
| GET | `/health` | Health check |

## Embedding Model

`all-MiniLM-L6-v2` (384-dim, lightweight, good for English text)

## Limitations (POC)

- In-memory ChromaDB (no persistence across restarts)
- No authentication
- Single collection (`documents`)
- No document deletion endpoint
- Embedding model is loaded but not used (FastAPI endpoint passes raw text to ChromaDB's default embedding)

## Quick test

```bash
# Embed
curl -X POST http://localhost:8004/embed \
  -H "Content-Type: application/json" \
  -d '{"documents": [{"id": "1", "text": "Rust is a systems programming language"}]}'

# Query
curl -X POST "http://localhost:8004/query?query_text=systems+language&n_results=3"
```

## Files

```
services/DeepSearchStack/services/vector-store/
├── main.py       # FastAPI + ChromaDB (in-memory)
└── Dockerfile
```
