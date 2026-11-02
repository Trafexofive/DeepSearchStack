# DeepSearchStack (DSS)

> **Autonomous Omni-Domain Search & Synthesis Engine.**  
> Self-hosted, Docker-native, polyglot microservice architecture. Federated multi-source retrieval, reciprocal rank fusion, and verifiable grounding.

---

## The System Architecture

```
                               ┌──────────────────────────────────────────────────────────┐
                               │                    CLIENT ECOSYSTEM                      │
                               │   dss Go CLI  ·  dss-tui Go TUI  ·  Python SDK  ·  REST  │
                               └────────────────────────────┬─────────────────────────────┘
                                                            │ HTTP / SSE / WebSocket (:8083 Ingress)
                                                            ▼
┌─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│                                                   REVERSE PROXY (NGINX :8083)                                               │
└──────┬──────────────────────┬──────────────────────┬──────────────────────┬──────────────────────┬───────────────────┬──────┘
       │ /dss/gateway         │ /dss/crawl           │ /dss/warehouse       │ /dss/api             │ /dss/agent        │ /dss/llm
       ▼                      ▼                      ▼                      ▼                      ▼                   ▼
┌──────────────┐       ┌──────────────┐       ┌──────────────┐       ┌──────────────┐       ┌──────────────┐    ┌──────────────┐
│search-gateway│       │   crawler    │       │  knowledge-  │       │   web-api    │       │ search-agent │    │  inference-  │
│   (:8002)    │       │   (:8000)    │       │  warehouse   │       │   (:8014)    │       │   (:8013)    │    │   gateway    │
│ RRF + Fusion │       │ Playwright + │       │   (:8009)    │       │ Hybrid Search│       │ Synthesis &  │    │   (:8005)    │
│  Consensus   │       │ Domain APIs  │       │ SQLite FTS5  │       │ Cross-Encoder│       │ Grounding    │    │ Provider Bus │
└──────┬───────┘       └──────┬───────┘       └──────┬───────┘       └──────┬───────┘       └──────┬───────┘    └──────┬───────┘
       │                      │                      │                      │                      │                   │
 ┌─────┴─────┐          ┌─────┴─────┐          ┌─────┴─────┐          ┌─────┴─────┐          ┌─────┴─────┐       ┌─────┴─────┐
 │ 13 Search │          │ Chromium  │          │ Outbox &  │          │ Sentence  │          │ Citation  │       │ DeepSeek  │
 │ Providers │          │ Renderer  │          │ Revisions │          │ Reranker  │          │ Validator │       │ Groq/Nim  │
 └───────────┘          └───────────┘          └───────────┘          └───────────┘          └───────────┘       └───────────┘
```

---

## Core Capabilities

### 1. Omni-Domain Search & Reciprocal Rank Fusion (RRF)
The `search-gateway` aggregates **13 free, multi-domain search providers** without requiring proprietary search APIs:
- **Web & Meta:** SearXNG, DuckDuckGo, YaCy
- **Academic & Papers:** arXiv API, PubMed (NCBI e-utilities), CrossRef
- **Code & Specs:** GitHub Search API, RFC / Standard specifications
- **Community & Q&A:** StackExchange network, Hacker News (Algolia API), Reddit
- **Archival:** Internet Archive

#### Positional RRF & Multi-Engine Consensus
Rather than relying on brittle snippet TF-IDF, results are fused using **Reciprocal Rank Fusion**:
$$RRF(d) = \sum_{p \in \text{providers}} w_p \cdot \frac{1}{60 + \text{rank}_p(d) + 1}$$
- **Consensus Multiplier:** If $M > 1$ independent engines surface the same canonical URL, its score receives a $(1.0 + 0.35 \times (M - 1))$ boost.
- **BM25F Field-Weighted Lexical Coverage:** Title term overlap (60%) is prioritized over snippet overlap (40%) with core entity anchor bonuses and navigation page demotion (`(disambiguation)`, `List of ...`).
- **Epistemic Artifact Classification:** Surfaces whether each result is a `paper`, `code`, `spec`, `qna`, `discussion`, or `reference`.

### 2. Specialized Web & Domain Extraction Pipeline (`crawler`)
- **Domain API Shortcuts:** Automatic bypass of fragile HTML scraping for known sources (direct arXiv metadata/abstract API, GitHub Issue/Repo API).
- **Direct Format Decoders:** Built-in PDF parsing (PyMuPDF), Markdown conversion, and readability extraction (`trafilatura`).
- **Resilience:** HEAD 404 short-circuiting, SQLite domain-TTL caching, and asynchronous job queuing (`/ingest/urls/async` with job status polling).

### 3. Knowledge Warehouse & Outbox Storage (`knowledge-warehouse`)
- **SQLite FTS5 + Vector Embeddings:** Hybrid search combining lexical BM25 rank with dense vector similarity.
- **Transactional Outbox Pattern:** Ensures embedding failures are stored to an outbox and retried in the background without losing raw ingested text.
- **Revision Tracking:** Tracks content updates, superseded revisions, and URL alias mappings.

---

## Client Ecosystem

### 1. High-Performance Go CLI (`clients/cli-go/dss`)
A Unix-native, pipeable command-line client built in Go:
```bash
# Health check
./clients/cli-go/dss health

# Federated multi-domain query
./clients/cli-go/dss search "raft consensus algorithm"

# Hybrid warehouse search
./clients/cli-go/dss warehouse hybrid "byzantine fault tolerance"

# Queue bulk ingest jobs
./clients/cli-go/dss jobs queue-urls --concurrency 2 "https://arxiv.org/abs/1706.03762"
./clients/cli-go/dss jobs --status done
```

### 2. Streaming Go TUI (`clients/tui-go/dss-tui`)
An interactive terminal dashboard featuring:
- **Agent Tab:** Live streaming synthesis and reasoning steps.
- **Search Tab:** Federated search with provider filters and confidence scores.
- **Warehouse Tab:** Interactive content explorer and category browser.
- **Crawl Tab:** Real-time URL and batch ingestion inspector.

---

## Verification & Testing

The stack includes a non-mocked, end-to-end integration test suite (`scripts/e2e_smoke.sh`) validating all 10 pipeline stages:

```bash
bash scripts/e2e_smoke.sh
```

| Section | Target | Coverage |
|---------|--------|----------|
| **1. Health** | Stack & Microservices | Ingress reverse proxy (:8083) and 7 microservice health endpoints |
| **2. Warehouse CRUD** | Data Integrity | Category filtering, URL lookups, ID fetching, 404 guards |
| **3. Hybrid Search** | Retrieval Quality | Postgres/SQLite FTS rank + vector rank verification |
| **4. Crawler Generic** | Extraction Engine | Static HTML crawling, HEAD 404 short-circuiting |
| **5. Domain Shortcuts** | Specialized Extractors | arXiv API, GitHub API, and native PDF extraction |
| **6. Async Ingest Queue**| Concurrency | Job submission, async worker processing, status polling |
| **7. Watcher Engine** | RSS/Atom Ingest | Feed validation, duplicate collision guards |
| **8. Aggregation** | Web API | Multi-provider aggregation, provider metadata catalogs |
| **9. Go CLI** | Client Interface | Formatted console output, JSON streaming, colored error states |
| **10. Full Pipeline** | End-to-End | Queue URL → Crawl → Warehouse ingest → Hybrid search retrieval |

---

## Quick Start

### 1. Prerequisites & Boot
```bash
# Clone and enter repo
cd deepsearch

# Boot the full Docker stack
make up STACK=full

# Verify all 14 containers are healthy
make list-stacks
```

### 2. Run E2E Verification
```bash
bash scripts/e2e_smoke.sh
```

### 3. Query the Engine
```bash
# Via Go CLI
./clients/cli-go/dss search "paxos consensus"

# Via HTTP API directly
curl -X POST http://localhost:8083/dss/gateway/search \
  -H "content-type: application/json" \
  -d '{"query": "distributed systems consensus", "max_results": 10}'
```

---

## Service Map & Ports

All services are accessible through the **Ingress Reverse Proxy** at `:8083`:

| Service | Internal Port | Ingress Path | Responsibility |
|---------|:-------------:|--------------|----------------|
| **nginx** | `80` (Host `8083`) | `/` | Ingress router, dynamic upstream resolution |
| **search-gateway** | `8002` | `/dss/gateway/*` | 13-provider query broker, RRF ranking, circuit breakers |
| **crawler** | `8000` | `/dss/crawl/*` | crawl4ai, Playwright, arXiv/GitHub/PDF extractors |
| **knowledge-warehouse** | `8009` | `/dss/warehouse/*` | FTS5 content store, revision tracking, embedding outbox |
| **web-api** | `8014` | `/dss/api/*` | Hybrid search, cross-encoder reranker, SSE streaming |
| **search-agent** | `8013` | `/dss/agent/*` | Synthesis orchestration, sentence-level citation audit |
| **inference-gateway** | `8005` | `/dss/llm/*` | Multi-provider LLM routing (DeepSeek, Groq, local) |
| **searxng** | `8080` | Internal | Meta-search engine upstream |
| **postgres** | `5432` | Internal | Relational metadata store |
| **redis** | `6379` | Internal | Response caching & circuit breaker state |

---

## License
MIT
