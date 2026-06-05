# DeepSearchStack Viability Audit — 2026-06-05

**Branch audited:** `audit/viability-2026-06-05` (SHA `37b9ed4`, DSS standalone migration state — the same as `ai-seooo`)
**Method:** Static analysis only. No live boot. Evidence via file reads, `python -m py_compile` on all service `.py` files (all pass), `docker compose config --quiet` (passes for all 4 compose files), cross-reference of README claims against code.
**Scope:** All 11 services, nginx, Makefile, all compose files, SDK, security posture.

---

## TOP-LEVEL CRITICAL (project-wide)

### T1. CRITICAL — Real API keys in `.env`
- **Evidence:** `cat .env` shows `GEMINI_API_KEY=AIzaSyCS-CK2ZyTVCRI8O__wWzyUgtHQZjmahqg` and `GROQ_API_KEY="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"`. Both match real provider key formats. The file's own banner says "Revoke your old keys and replace these placeholders with NEW ones."
- **Status:** `.env` is correctly gitignored (not in git history per `git ls-files`), so no rotation-by-history is needed. But they are plaintext on disk.
- **FIX:** Rotate both keys at Google Cloud Console and Groq Console. Delete the file or move to a secret manager.

### T2. CRITICAL — `make up` default STACK is broken
- **Evidence:** `Makefile:23` sets `STACK ?= core`. The `ifeq ($(STACK),full)` branch picks `docker-compose.yml`; otherwise it picks `infra/docker-compose.$(STACK).yml`. So `STACK=core` resolves to `infra/docker-compose.core.yml` — which was DELETED in the migration (commit `d527f54` removed it). `make up` with no args will fail with "Stack 'core' not found."
- **FIX:** Change `STACK ?= core` to `STACK ?= full`. Or add a `core` stack file.

### T3. CRITICAL — nginx routing is broken for every API call
- **Evidence:** `infra/nginx/nginx.conf:16-17`:
  ```nginx
  location /dss/api/ { proxy_pass http://web-api:8014/; }
  ```
  The trailing `/` strips `/dss/api/` and forwards to `/`. web-api's actual routes are `/api/aggregate`, `/api/aggregate/stream`, etc. So `http://localhost:8083/dss/api/aggregate` becomes `http://web-api:8014/aggregate` → 404.
- **FIX:** Change to `proxy_pass http://web-api:8014/api/;` (preserve `/api`).

### T4. CRITICAL — README claim "13 providers across 8 domains" is false at the orchestrator
- **Evidence:** `services/web-api/main.py:234-242`:
  ```python
  _AGGREGATE_PROVIDERS = ["searxng", "wikipedia", "stackexchange", "hackernews", "github", "arxiv", "yacy"]
  ```
  That's **7** providers, hardcoded in code. The search-gateway `provider_manager.py` does support 13 (incl. whoogle, duckduckgo, pubmed, crossref, reddit, internetarchive), but web-api never asks for them. The README's "13 providers" claim describes a capability that is not exposed to end users.
- **FIX:** Move `_AGGREGATE_PROVIDERS` to a settings file or env var. Document the actual set. Restore whoogle/duckduckgo/pubmed/crossref if they are actually working.

---

## web-api (:8014) — 1,228 LoC

**VERDICT:** NEEDS WORK
**USE CASE TEST:** Cross-domain aggregate search with RAG + synthesis → ACTUALLY: works for the 7 hardcoded providers, RAG works, but multiple CRITICAL/HIGH issues.

### ISSUES
- **CRITICAL:** Hardcoded `INFERENCE_GATEWAY_URL` default is `http://inference_gateway:8005` (underscore), but the compose service is named `inference-gateway` (dash). Compose overrides save it at runtime, but the default is wrong. (`main.py:56`)
- **CRITICAL:** `_AGGREGATE_PROVIDERS` hardcoded — see T4 above. (`main.py:234`)
- **CRITICAL:** `_save_hashes()` defined (`main.py:99`) but never called. Embed-dedup hash set is in-memory only; lost on restart; causes re-embedding of all content after every restart.
- **HIGH:** `_seed_warehouse` swallows all exceptions with bare `except Exception: pass` (`main.py:415`). No log, no metric. Silent failure.
- **HIGH:** `/crawl/batch` accepts 50 URLs and returns the full response — 50 pages of markdown × ~50KB = 2.5MB response. No streaming. Will OOM the client.
- **HIGH:** No per-URL timeout in `_scrape_sources` (`main.py:323`). A single hung crawl can block `/api/aggregate` for 20s+ (the `req.timeout`).
- **MEDIUM:** No CORS middleware. `/ui` is served, but cross-origin JS calls fail.
- **MEDIUM:** If `cached := await _cache_get(ck)` returns an empty dict, the walrus treats it as falsy and refetches. Fragile.
- **LOW:** `_extract_entities` runs on every source's title+description. Fine for small N, costly at scale.

### FIXES (CRITICAL/HIGH)
1. `main.py:56` — `os.environ.get("INFERENCE_GATEWAY_URL", "http://inference_gateway:8005")` → `"http://inference-gateway:8005"`.
2. Move `_AGGREGATE_PROVIDERS` to env var or `settings.yml`; document.
3. Add a periodic background task that calls `_save_hashes()` every 60s, or save after every Nth embed.
4. Replace `except Exception: pass` in `_seed_warehouse` with `log.warning("seed_failed url=%s: %s", s.url, e); metrics.incr("seed.failures")`.
5. Stream `/crawl/batch` results via SSE; or cap response at 5MB and return a "truncated" flag.

---

## search-gateway (:8002) — 13-provider router

**VERDICT:** NEEDS WORK
**USE CASE TEST:** Fan out to 13 providers, fuse, rank, return → ACTUALLY: parser stubs exist for all 13 but several are dead in practice; the web-api consumer only asks for 7.

### ISSUES
- **HIGH:** arXiv rate limiter uses module-level globals (`_ARXIV_LAST_REQUEST`, `_ARXIV_MIN_INTERVAL`). Not thread/async-safe — two concurrent requests can both pass the check. (`provider_manager.py:39-41`)
- **HIGH:** Circuit breaker has no half-open state. After 60s reset, ALL providers get retried at full blast. Thundering herd. (`system_components.py:CircuitBreaker`)
- **HIGH:** DuckDuckGo parser targets the Instant Answer API only — returns at most 5 abstract results, not real web search. `settings.yml:51` confirms: "Instant Answer API only — no general web results." Yet it's listed in the orchestrator as a "web" provider with weight 1.1.
- **HIGH:** Reddit provider — `settings.yml:54` says "needs proxy" (IP-blocked from Docker). Provider is dead unless `with-proxy` profile is enabled.
- **HIGH:** Whoogle — `settings.yml:46` says "Tor exits often blocked by Google." Provider is dead without Tor configuration.
- **MEDIUM:** `_fuse_and_deduplicate` is exact URL match. `https://example.com` and `https://example.com/` are distinct.
- **MEDIUM:** TF-IDF computed on full corpus (O(n²)). Fine for 100 results, slow at 10K.
- **MEDIUM:** Round-robin diversification forces top-N to be 1-per-source regardless of relevance. May rank less-relevant results higher.
- **LOW:** `_calculate_relevance_score` swallows all exceptions silently.

### FIXES (CRITICAL/HIGH)
1. `provider_manager.py:39-41` — replace module-level globals with a class-level `last_request` dict + `asyncio.Lock`.
2. `system_components.py:CircuitBreaker` — add HALF_OPEN state. After 60s, allow exactly 1 probe request; on success, close; on failure, reopen.
3. Down-weight DuckDuckGo to 0.1 in `_AGGREGATE_PROVIDERS` and rename `duckduckgo` → `duckduckgo_instant_answer`. Or implement HTML scraping.
4. Gate Reddit/Whoogle behind a `with-proxy` profile check; skip them otherwise.

---

## crawler (:8000) — 583 LoC

**VERDICT:** NEEDS WORK
**USE CASE TEST:** Cache-aware full-page extraction with warehouse forwarding → ACTUALLY: works for one-off crawls, but concurrency model is fragile, no WAL on cache DB, batch endpoint has no backpressure.

### ISSUES
- **CRITICAL:** Cache DB (`CACHE_DB`) is opened fresh on every `_cache_get` / `_cache_put`. No `PRAGMA journal_mode=WAL`. Concurrent crawl4ai workers writing while `_cache_stats` reads → "database is locked" errors. The single `_cache_sem = asyncio.Semaphore(1)` limits concurrency to 1. (`main.py:97`)
- **CRITICAL:** `_retry_pending_forwards` (`main.py:209`) opens a sqlite3 connection, reads rows, then opens ANOTHER connection to update. Between read and update, another retry loop can process the same row → duplicate forwards.
- **CRITICAL:** `crawl/batch` has per-batch `asyncio.Semaphore(CRAWL_CONCURRENCY)` but no GLOBAL concurrency. 5 concurrent batch requests = 50 concurrent crawls. No 429.
- **HIGH:** `extraction_strategy == "llm"` instantiates `LLMExtractionStrategy(provider="deepseek")` with no API key wiring. Runtime failure.
- **HIGH:** No per-URL timeout enforcement inside `_do_crawl`. `asyncio.wait_for` wraps the whole call, but in batch mode one slow URL blocks its slot for `req.timeout` seconds (up to 120s).
- **MEDIUM:** `_domain_last_request` and `_domain_min_interval` are module-level — not safe under concurrent batch calls.
- **MEDIUM:** `_strip_boilerplate` is duplicated 3× — in `crawler/main.py`, `web-api/main.py`, `deepsearch/core/scraper.py`. Drift risk.
- **MEDIUM:** `crawl/batch` returns ALL results in one response. 50 URLs × 50KB markdown = 2.5MB. No streaming.

### FIXES (CRITICAL/HIGH)
1. `main.py:_init_cache` — add `PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000`.
2. `main.py:_retry_pending_forwards` — use a single `asyncio.Lock` to serialize reads+updates on the pending-forwards DB.
3. Add a module-level `asyncio.Semaphore(GLOBAL_MAX_CRAWLS, default=20)` wrapping `_do_crawl`.
4. Wire `LLMExtractionStrategy` to use the inference-gateway with `provider="deepseek"` and a proper config.
5. Wrap each URL in its own `asyncio.wait_for` inside `_do_crawl` so a slow URL doesn't tie up its concurrency slot.

---

## vector-store (:8004) — 153 LoC

**VERDICT:** NEEDS WORK
**USE CASE TEST:** Persistent ChromaDB-backed embedding + cosine similarity search → ACTUALLY: works for small corpora. README's "ONNX-bundled, no model download needed" is false.

### ISSUES
- **HIGH:** README claim contradicted by code. `embedding_functions.DefaultEmbeddingFunction()` downloads the model to `~/.cache/chroma/onnx_models/` on first call. A container with no internet at startup will pass `/health` (only calls `collection.count()`) but fail on first `/embed` or `/query`.
- **HIGH:** `query_post` accepts `req: dict` (not Pydantic). No `n_results` cap. A caller passing `n_results=1000000` will cause ChromaDB to OOM.
- **MEDIUM:** No per-namespace access control. Anyone with reach to `/embed` can read any namespace via `/query`.
- **MEDIUM:** `_sanitize_metadata` coerces non-primitive values to str — silent data loss for nested dicts.
- **LOW:** No embedding error handling — model load failure → 500 with stack trace.

### FIXES (CRITICAL/HIGH)
1. Dockerfile: pre-download the ONNX model during build: `RUN python -c "from chromadb.utils import embedding_functions; embedding_functions.DefaultEmbeddingFunction()"`.
2. Update README to remove the false "no model download needed" claim.
3. Replace `req: dict` with a Pydantic `QueryRequest(BaseModel)` with `n_results: int = Field(5, ge=1, le=100)`.

---

## knowledge-warehouse (:8009) — 482 LoC

**VERDICT:** NEEDS WORK
**USE CASE TEST:** Persistent SQLite FTS5 content repository → ACTUALLY: works for moderate scale. SQL injection risk in `/search` via `domain` filter.

### ISSUES
- **CRITICAL:** SQL injection vector in `/search` (`main.py:135-150`). The `where` clause is built via f-string interpolation of `domain` after a single-quote escape. The escape works for `'` but the f-string structure is fragile. A future change to add another field could re-introduce a real injection. Use parameterized queries throughout.
- **HIGH:** `MAX_CONTENT_LENGTH = 100000` with no chunking. A 200KB markdown page is silently truncated to 100KB on ingest.
- **HIGH:** `_read_conn` opens a fresh sqlite3 connection per request. Under high QPS (vector-store calling every 100ms), the connection storm could exhaust file descriptors.
- **MEDIUM:** No backup automation. `scripts/dss-backup.py` exists but is not in cron.
- **MEDIUM:** `/search` returns the FTS5 snippet as `snippet`, but the upstream SourceResult model expects a `description` field — there's a name/format mismatch in the web-api integration.
- **LOW:** `tags` stored as JSON in TEXT column. Should be a join table for queryability.

### FIXES (CRITICAL/HIGH)
1. `main.py:135-150` — replace the f-string `where` with parameterized SQL: `sql += " AND c.source_domain = ?"` and `params.append(domain)`.
2. Implement connection pooling — a single `sqlite3.Connection` with `check_same_thread=False` reused across reads (FTS5 is read-heavy).
3. For long markdown: chunk on ingest and store chunks separately, or store the full body and truncate only for the FTS5 indexing pass.

---

## search-agent (:8013) — 112 LoC

**VERDICT:** PROTOTYPE ONLY
**USE CASE TEST:** Streaming LLM synthesis with bracket citations → ACTUALLY: streams content, but citation enforcement is prompt-only. LLM hallucinates citations.

### ISSUES
- **HIGH:** The system prompt asks for `[1]`, `[2]` citations but there's NO post-processing step to validate the citations against the source list. The LLM will fabricate source numbers.
- **HIGH:** `llm_client.py:51-60` only adds `Authorization: Bearer` if `api_key` is set. For OpenCode free tier (no key), the request goes out unauthenticated — accepted by free tier, but fails on paid-only models.
- **HIGH:** No fallback logic. If `request.llm_provider` is set to "deepseek-chat" and the API is down, the entire synthesis fails. No retry, no fallback.
- **MEDIUM:** System prompt hardcoded in `main.py`. Operators can't tune without redeploying.
- **MEDIUM:** `error_content` in `_generate_and_handle_stream` swallows real errors with a generic message. The user can't tell what failed.

### FIXES (CRITICAL/HIGH)
1. Add post-processing in `_yield_synthesis_chunks` that:
   - Parses `[N]` citations from the streamed output
   - Validates `1 ≤ N ≤ len(request.sources)`
   - Rewrites invalid citations to `[?]`
2. Add a fallback chain in `LLMClient.get_streaming_completion`: `request.llm_provider` → `LLM_MODEL` env → `opencode/deepseek-v4-flash-free`.
3. Move the system prompt to a settings file.

---

## inference-gateway (:8005) — 276 LoC

**VERDICT:** PROTOTYPE ONLY
**USE CASE TEST:** Provider-agnostic LLM routing with cascading fallback → ACTUALLY: routing works, but cascade only retries on a narrow set of status codes, retries are excessive, no auth, two providers are dead-code.

### ISSUES
- **HIGH:** `_cascade` in `main.py:198-208` only retries on `{429, 402, 503}`. A 500, 502, 504, or timeout causes the entire request to fail. `BaseProvider._post` uses tenacity to retry 5xx internally, but the cascade does NOT.
- **HIGH:** `BaseProvider._post` uses `tenacity.stop_after_attempt(20)` with `wait_exponential(min=2, max=30)`. At 20 attempts with average 4s backoff, a single failed request can take ~80s. web-api and search-agent call this with 60–90s timeouts, so a 5xx upstream causes a timeout-induced 504 in the caller.
- **HIGH:** No auth on the gateway. Anyone who reaches `:8005` can call any model.
- **MEDIUM:** `_init_providers` (`main.py:25-35`) registers only `(deepseek, nvidia_nim, opencode)`. The `glm_provider.py` and `minimax_provider.py` files exist with full implementations but are NEVER wired in. Dead code in the registry.
- **MEDIUM:** `opencode_provider._build_payload` does `payload.setdefault("max_tokens", 128000)`. 128K tokens is excessive for most requests.
- **MEDIUM:** Model catalog is hardcoded in `discover_models`. No live discovery.
- **LOW:** No streaming metrics (TTFT, tokens/sec).

### FIXES (CRITICAL/HIGH)
1. `main.py:_cascade` — add `500, 502, 504` and `RequestError` to the retry set. Cap retries at 3 per provider.
2. `provider_base.py:_post` — change `stop_after_attempt(20)` to 3, reduce `max=30` to `max=10`. Avoid 80s+ timeouts.
3. Add `Depends(verify_api_key)` for write endpoints (chat completions). Public read access to `/v1/models` and `/v1/virtual-models` is fine.
4. Either register `GLMProvider` and `MiniMaxProvider` in `_init_providers` or delete them.

---

## deepsearch (:8001) — DEPRECATED SHIM

**VERDICT:** AI SLOP
**USE CASE TEST:** Maintain session management, preserve legacy API → ACTUALLY: a 172-line proxy to web-api. Sessions partially work. Engine code is dead-ish (the new web-api doesn't import it).

### ISSUES
- **HIGH:** Marked DEPRECATED in 5 places (`main.py:1`, `main.py:38`, `main.py:50`, `main.py:54`, `main.py:58`) but STILL IN `docker-compose.yml` and `infra/docker-compose.yml`. Confusing — two services doing the same thing.
- **HIGH:** Session storage (`storage/sessions.py`, 252 LoC) has TWO backends (Postgres, Redis). Compose `depends_on` for deepsearch only checks `service_started` for Postgres, not `service_healthy`. If Postgres takes >30s to start, the first session creation crashes.
- **MEDIUM:** `from models import (...)` uses absolute imports dependent on `PYTHONPATH=/app`. Adding `from libs.common.models import ...` would create a name collision.
- **MEDIUM:** `RecursiveResearchRequest` `max_iterations` default has no upper cap. A malicious caller can set `max_iterations=1000` and DoS the synthesis LLM.
- **LOW:** `_recursive_done` is missing `rag_chunks` field.

### FIXES
1. **DELETE THIS SERVICE.** All endpoints exist in web-api. Sessions can be a separate microservice if needed.
2. Remove from both `docker-compose.yml` and `infra/docker-compose.yml`.

---

## proxy-rotator (with-proxy profile)

**VERDICT:** PROTOTYPE ONLY
**USE CASE TEST:** Tor-backed rotating proxy for IP diversity → ACTUALLY: starts tor, privoxy, tinyproxy. But the proxy URL isn't auto-injected into the crawler.

### ISSUES
- **HIGH:** Crawler uses `HTTP_PROXY` env var. proxy-rotator doesn't auto-write that env. The user has to manually set `CRAWLER_HTTP_PROXY=http://tinyproxy:8888` in `.env`. The `.env.example` doesn't mention this.
- **HIGH:** Free proxy list URLs are unpinned GitHub raw URLs. Any of them changing format silently returns 0.
- **HIGH:** `pool_maintenance_loop` updates the module-global `free_pool` non-atomically. Concurrent `/refresh` requests race.
- **MEDIUM:** Tor config has `SOCKSPolicy accept 0.0.0.0/0`. If port 9050 is exposed, anyone can use this Tor relay. In Docker network this is fine; in production it's not.
- **MEDIUM:** tinyproxy `MaxClients 50` — fine for personal, collapses under load.
- **MEDIUM:** Free proxy list is HTTP-typed, tested via `httpbin.org` over HTTP. But crawl4ai needs HTTPS for most real targets. Mismatch.

### FIXES (CRITICAL/HIGH)
1. proxy-rotator: write the proxy URL to a shared volume like `/shared/proxy.env` on startup. Crawler auto-discovers and exports it on each request.
2. Pin proxy list URLs to specific commit SHAs.
3. Wrap `free_pool` access in an `asyncio.Lock`.

---

## wiki-indexer (:8014)

**VERDICT:** AI SLOP
**USE CASE TEST:** Bulk-import Wikipedia into warehouse + vector-store → ACTUALLY: doesn't work in any of the main compose files. Standalone compose references wrong service.

### ISSUES
- **CRITICAL:** `app/main.py:18` hardcodes `VECTOR_STORE_URL=http://dss-vector-store:8003`. Wrong service name (`vector-store`, not `dss-vector-store`) AND wrong port (8004, not 8003). The standalone `services/wiki-indexer/docker-compose.yml` overrides this with the right value, but the main `infra/docker-compose.yml` and root `docker-compose.yml` do NOT pass the env var. So in the main stacks, this service is broken — every call to the vector store will 404.
- **CRITICAL:** `Dockerfile:EXPOSE 8014` — same as web-api. In root `docker-compose.yml` both are defined; if both are started (wiki-indexer has `restart: "no"`, but a manual `up wiki-indexer` would conflict with web-api's host port 8014 mapping in the Makefile / external use).
- **HIGH:** `_index_articles` calls `client.post(f"{WAREHOUSE_URL}/store/batch"...)`. The knowledge-warehouse has no `/store/batch` endpoint — only `/ingest` (single-item). 404s for every batch.
- **HIGH:** Wikipedia dump is ~20GB compressed. No max-size cap, no resume, no integrity check. A 1% download failure = corrupt dump = indexer crashes mid-way.
- **HIGH:** Indexer is single-process, single-pass. No checkpoint beyond a `skip` parameter that's never wired up. Crash at article 5M/7M = restart from 0.
- **HIGH:** `mwparserfromhell` parse on 7M articles is days of single-threaded work. No parallelism.
- **MEDIUM:** No deduplication. Re-running the indexer creates duplicate entries.
- **LOW:** Background tasks for download/index are not cancellable mid-flight.

### FIXES (CRITICAL/HIGH)
1. `app/main.py:18` — `VECTOR_STORE_URL = os.environ.get("VECTOR_STORE_URL", "http://vector-store:8004")`.
2. Add `VECTOR_STORE_URL=http://vector-store:8004` to every compose file that includes wiki-indexer.
3. `Dockerfile:EXPOSE 8014` → `EXPOSE 8015`.
4. `app/main.py:_index_articles` — replace `/store/batch` with a concurrent loop of `/ingest` calls (semaphore 5).
5. Use a streaming-download library that supports resume, with SHA1 verification against the Wikimedia manifest.

---

## SDK (sdk/python) — 364 LoC

**VERDICT:** NEEDS WORK
**USE CASE TEST:** Async + sync Python client for the stack → ACTUALLY: works for basic operations. No retries, no streaming completion.

### ISSUES
- **MEDIUM:** `crawl_sync`, `search_sync`, `llm_complete_sync` use sync `requests`. Fine for scripts.
- **MEDIUM:** No retry logic. Network blip = exception to caller.
- **MEDIUM:** No streaming completion wrapper. Chat-agent supports SSE but the SDK doesn't.
- **LOW:** No configurable timeouts exposed.

### FIXES
1. Add `tenacity` retry decorator on the async path: 3 attempts, exponential backoff.
2. Add a streaming wrapper for `/api/search/stream` and `/api/completion/stream`.

---

## nginx (:80) — reverse proxy

**VERDICT:** BUG (see T3 above)
**USE CASE TEST:** Single entrypoint routing by URL prefix → ACTUALLY: every API call 404s because of the prefix-strip bug.

### FIXES
1. `infra/nginx/nginx.conf:16-17` — `proxy_pass http://web-api:8014/;` → `proxy_pass http://web-api:8014/api/;` for the `/dss/api/` location.

---

## docker-compose (all files)

**VERDICT:** NEEDS WORK
**USE CASE TEST:** Boot the stack with `make up` → ACTUALLY: see T2 — the default `make up` target is broken. Other issues:

### ISSUES
- **CRITICAL:** Root `docker-compose.yml` has BOTH `web-api` (port 8014 internal) AND `wiki-indexer` (port 8014 internal + host mapping). Internal port collision if both are up.
- **HIGH:** `infra/docker-compose.yml` does not include `wiki-indexer` at all. The wiki-indexer Dockerfile is referenced in the README but is never built by the main compose.
- **HIGH:** `Makefile` uses `--env-file infra/env/.dev.env`. The root `docker-compose.yml` is NOT invoked via Makefile in the README quickstart, so users who run `docker compose -f docker-compose.yml up` directly will not load the env file.
- **HIGH:** `web-api` in `infra/docker-compose.yml` doesn't have `CRAWLER_URL` env var. web-api's default `CRAWLER_URL` works, but if a future change moves crawler, web-api breaks.
- **MEDIUM:** No resource limits (`mem_limit`, `cpus`) on any service. A runaway container OOMs the host.
- **MEDIUM:** Inconsistent `restart:` policies: some services `unless-stopped`, others `no`, wiki-indexer is `no`.
- **LOW:** `proxy-rotator` and `tinyproxy` are under `profiles: ["with-proxy"]` — undocumented in the README quickstart.

### FIXES (CRITICAL/HIGH)
1. Change wiki-indexer port to 8015 in the Dockerfile AND the host mapping in root compose.
2. Either add wiki-indexer to `infra/docker-compose.yml` (with the right env vars) or remove references to it in the README.
3. Add a `--env-file infra/env/.dev.env` to the root `docker-compose.yml`'s `up` invocation in docs.

---

## Makefile

**VERDICT:** NEEDS WORK (see T2)
**USE CASE TEST:** Stack lifecycle via `make up/down/restart/logs/status` → ACTUALLY: see T2 — `make up` with no args fails.

### ISSUES
- **CRITICAL:** `STACK ?= core` is broken. See T2.
- **MEDIUM:** The shortcut targets `full`, `light`, `test` use `STACK=full|light|test` — these resolve to `infra/docker-compose.{full|light|test}.yml`, but the actual files are `infra/docker-compose.yml`, `infra/docker-compose.light.yml`, `infra/docker-compose.test.yml`. There's no `infra/docker-compose.full.yml`. So `make full` also fails.
- **MEDIUM:** `STACK` is case-sensitive. `Make` is not.
- **LOW:** No way to override the env file from CLI.

### FIXES (CRITICAL/HIGH)
1. `Makefile:23` — `STACK ?= core` → `STACK ?= full`.
2. `Makefile:28-30` — special-case `STACK=full` → `COMPOSE_FILE := $(COMPOSE_DIR)/docker-compose.yml` (the actual file name).

---

## CROSS-CUTTING OBSERVATIONS

### O1. README inaccuracies (multiple)
- **File count:** README claims `159 files, 11,408 LoC Python`. Actual: 245 files, **14,028 LoC Python**. (`find . -name "*.py" | xargs wc -l`)
- **Provider count:** "13 providers across 8 domains" — actual aggregated set is 7 (see T4).
- **Vector store:** "ONNX-bundled, no model download needed" — false. See vector-store section.
- **Versioning:** README mentions "SynthesizerAgent v9.0.0" (matches code) but the deprecated deepsearch shim still says "v2.0.0". Confusing.
- **Wiki-indexer README claim:** Not verified — no README for wiki-indexer found.

### O2. No auth anywhere
- web-api, search-gateway, search-agent, inference-gateway, knowledge-warehouse, vector-store, crawler — all open.
- nginx is the only public entrypoint and has no auth.
- Acceptable for self-hosted single-user, but the README and code comments reference "production" multiple times.

### O3. No Prometheus integration despite config
- `infra/config/prom/config.yml` exists. No service exposes Prometheus-format metrics.
- web-api has `/api/metrics` returning in-memory stats — Prometheus can't scrape this format.
- Either delete `infra/config/prom/` or implement `/metrics` Prometheus endpoint in each service.

### O4. Graceful shutdown
- crawler closes `_crawler` on shutdown. Other services don't handle shutdown.
- A 60s `aggregate` request mid-flight will be killed by SIGTERM on container restart.

### O5. Cross-service contract drift
- The deprecated deepsearch service is in 2 compose files; web-api's `INFERENCE_GATEWAY_URL` default is wrong; search-gateway's hardcoded provider list doesn't match web-api's. The codebase is mid-migration and the seams are visible.

---

## SUMMARY

| Service | Verdict | Critical | High | Medium |
|---|---|---|---|---|
| web-api | NEEDS WORK | 3 | 2 | 3 |
| search-gateway | NEEDS WORK | 0 | 4 | 3 |
| crawler | NEEDS WORK | 3 | 2 | 3 |
| vector-store | NEEDS WORK | 0 | 2 | 2 |
| knowledge-warehouse | NEEDS WORK | 1 | 2 | 2 |
| search-agent | PROTOTYPE ONLY | 0 | 3 | 2 |
| inference-gateway | PROTOTYPE ONLY | 0 | 3 | 3 |
| deepsearch | AI SLOP | 0 | 2 | 2 |
| proxy-rotator | PROTOTYPE ONLY | 0 | 3 | 3 |
| wiki-indexer | AI SLOP | 2 | 3 | 1 |
| SDK | NEEDS WORK | 0 | 0 | 3 |
| nginx | BUG | 1 | 0 | 0 |
| docker-compose | NEEDS WORK | 1 | 3 | 2 |
| Makefile | NEEDS WORK | 1 | 0 | 2 |
| **TOTALS** | | **12** | **30** | **31** |

**Bottom line:** The system is mid-migration with visible seams. The most impactful single change is fixing the Makefile default (`STACK ?= core` → `STACK ?= full`) so `make up` works at all. The most dangerous issue is the `INFERENCE_GATEWAY_URL` default mismatch combined with the `make up` bug — a user doing a clean clone will get a stack that doesn't boot, then if they fix the Makefile, the inference-gateway URL will be wrong by default. Top-priority fixes in order: T2 (Makefile) → T1 (.env keys) → T3 (nginx) → T4 (provider list) → all service-specific CRITICALs.

---

## NEXT STEPS (for the audit/viability-2026-06-05 branch)

- [ ] Rotate `GEMINI_API_KEY` and `GROQ_API_KEY` at provider consoles
- [ ] Apply T2 fix (Makefile default STACK)
- [ ] Apply T3 fix (nginx proxy_pass)
- [ ] Apply T4 fix (provider list)
- [ ] Run live boot smoke test in containers per audit ask_cards answer
- [ ] Containerized test pass: bring up `infra/docker-compose.yml`, curl-smoke `/health`, `/api/aggregate`, `/crawl`, `/embed`, `/query`
- [ ] Re-audit after fixes; close this report
