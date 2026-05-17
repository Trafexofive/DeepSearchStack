# Knowledge Warehouse (port 8009)

> **Status**: ✅ Working · **Dependencies**: PostgreSQL

## Purpose
Persistent cross-domain content store with full-text search. Stores crawled web content, extracted knowledge, and documents. PostgreSQL tsvector for text search with optional pgvector for semantic search.

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | `{"status":"ok","documents":N}` |
| POST | `/documents` | Store a document |
| GET | `/documents/{id}` | Retrieve by ID |
| GET | `/search` | Full-text search (`?q=term`) |
| DELETE | `/documents/{id}` | Remove a document |

## Document Model
```json
{
  "url": "https://example.com/article",
  "title": "Article Title",
  "content": "Full extracted content...",
  "source": "crawler",
  "tags": ["rust", "async"],
  "fetched_at": "2026-05-13T12:00:00Z"
}
```

## Storage
- **PostgreSQL** — primary store with tsvector FTS index
- **SQLite FTS5** — lightweight fallback/alternative
- **pgvector** — optional semantic embeddings (if enabled)

## Search
```bash
# Full-text search
curl -s "http://localhost:8009/search?q=rust+async+runtime" | python3 -m json.tool

# By tag
curl -s "http://localhost:8009/search?tags=rust,performance" | python3 -m json.tool
```

## Docker
```bash
make up core/knowledge_warehouse
```
