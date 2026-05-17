# Web API — Cross-Domain Aggregation (port 8014)

> **Status**: ✅ Working (deployed 2026-05-13) · **Dependencies**: search-gateway, search-agent, inference-gateway, warehouse

## Purpose
Cross-domain aggregation orchestrator. Queries ALL search sources + knowledge warehouse in parallel, domain-tags results, reconciles facts across domains via LLM, extracts consensus "sources of truth" with citations.

## Pipeline
```
Query
  ├── search-gateway → (searxng|whoogle|wikipedia|ddg|stackexchange|arxiv|yacy)
  ├── knowledge-warehouse → FTS5 content store
  ↓
  Domain Classify → encyclopedia | academic | q_and_a | web | code | internal
  ↓
  Deduplicate → Merge → Sort by confidence
  ↓
  LLM Reconciliation (inference-gateway)
    → Extract consensus facts
    → Identify conflicting claims
    → Synthesize narrative
```

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health + 4 dependency checks |
| POST | `/api/aggregate` | Cross-domain aggregation + source-of-truth extraction |
| POST | `/api/search/stream` | Search → synthesize (SSE streaming) |
| POST | `/api/completion/stream` | Direct LLM completion proxy |
| GET | `/api/providers` | Available LLM models |

## Aggregate Request
```json
{
  "query": "quantum computing breakthroughs 2025",
  "max_results": 10,
  "include_warehouse": true,
  "reconcile": true
}
```

## Aggregate Response
```json
{
  "query": "quantum computing breakthroughs 2025",
  "domains_queried": ["encyclopedia", "web", "q_and_a"],
  "total_sources": 8,
  "sources": [
    {"title": "...", "url": "...", "source": "searxng", "domain": "web", "confidence": 0.6}
  ],
  "consensus": [
    {
      "claim": "IBM announced a 1,121-qubit processor in 2025",
      "confidence": 0.95,
      "supporting_sources": ["[1]", "[4]"],
      "conflicting_sources": []
    }
  ],
  "synthesis": "2-3 paragraph narrative of what we know with high confidence...",
  "execution_time_ms": 8194
}
```

## Domain Taxonomy
| Source | Domain |
|---|---|
| searxng, whoogle, yacy, duckduckgo | web |
| wikipedia | encyclopedia |
| stackexchange | q_and_a |
| arxiv | academic |
| github | code |
| warehouse | internal |

## Proxy Access (via API Gateway)
```bash
POST /api/dss/aggregate   → web-api:8014/api/aggregate
POST /api/dss/search/stream → web-api:8014/api/search/stream
```

## Docker
```bash
make up dss/web-api
```

## E2E Test
```bash
# Cross-domain aggregation
curl -s -X POST http://localhost:80/api/dss/aggregate \
  -H "Content-Type: application/json" \
  -d '{"query":"Rust async trait stabilization","max_results":10,"reconcile":true}' \
  | python3 -m json.tool

# Streaming search → answer
curl -s -N -X POST http://localhost:8014/api/search/stream \
  -H "Content-Type: application/json" \
  -d '{"query":"What is Rust ownership"}'
```
