# DeepSearchStack Viability Audit — 2026-06-12 (refresh)

**Branch:** `audit/viability-2026-06-05` (HEAD `c9166c8`)
**Last audit:** `docs/audit/viability-2026-06-05.md` (7 days ago)
**Method:** Live boot of full stack (`infra/docker-compose.yml`, 12 services), real curl probes against `/dss/api/aggregate`, `/v1/chat/completions`, `/dss/gateway/*`, `/dss/crawl/*`, `/dss/warehouse/*`, `/dss/vectors/*`. All code references file:line.

---

## TL;DR — INDIE-HACKER CALL

**Boot status:** 12/12 containers come up green. nginx routes work. The cross-domain `/dss/api/aggregate` golden path returns synthesized results from 7 providers in ~29s on cold query.

**Shippable today? NO.** One showstopper found live: the fact-DB short-circuit serves stale, wrong-domain "verified consensus" facts as cached truth in 2ms for any query containing common English stopwords like *is*, *the*, *on*. Self-hosting a search stack that confidently hallucinates is worse than a slow stack — it's a trust killer. Fix is ~5 lines.

**Net since last audit:** Big wins (T2/T3/T4/crawler-WAL/hash-flush all landed correctly), but T1 (API keys) is untouched and **two new criticals** were introduced in code merged between 2026-06-05 and 2026-06-06.

---

## 1. AUDIT FIX VERIFICATION (vs viability-2026-06-05.md)

| ID | Fix | Status | Evidence |
|----|-----|--------|----------|
| T1 | Rotate live API keys in `.env` | ❌ **NOT DONE** | `.env` still has live-format `GEMINI_API_KEY=AIzaSyCS-...` and `GROQ_API_KEY=gsk_QVBh...`; `infra/env/.dev.env` adds live `DEEPSEEK_API_KEY=sk-7cbf...`. Groq key returns 401 on `/v1/chat/completions` — already burned. |
| T2 | `STACK ?= full` | ✅ | `Makefile:27` |
| T3 | nginx `/dss/api/` → `/api/` | ✅ | `infra/nginx/nginx.conf:15-16` |
| T4 | `AGGREGATE_PROVIDERS` env-plumbed | ✅ | `services/web-api/main.py:382-402` + `infra/docker-compose.yml:231` |
| web-api inference-gateway host | ✅ runtime | Code default still `inference_gateway` (underscore) at `main.py:80`, but compose env override at `infra/docker-compose.yml:225` corrects it. Stale `inference_gateway:8005` still appears in `infra/docker-compose.dss.yml:116,265` (see §3 dead file). |
| Crawler WAL | ✅ | `services/crawler/main.py:60` `conn.execute("PRAGMA journal_mode=WAL")` |
| `_save_hashes()` flush | ✅ | `services/web-api/main.py:313` periodic task + shutdown hook |
| Whoogle removal | ⚠️ Partial | Removed from `infra/docker-compose.yml`, still present in `infra/docker-compose.dss.yml:145-147` |

---

## 2. NEW CRITICALS (introduced or uncovered live)

### N1. CRITICAL — Fact-DB short-circuit serves wrong-domain facts as "verified"
- **Live proof:** `POST /dss/api/aggregate {"query":"the cat is on the mat","max_results":2,"reconcile":false}` returns HTTP 200 in 2ms with `fact_db_hit:true` and `consensus:[{claim:"Rust is used for high-performance computational tasks...", quality:"verified"}, {claim:"Bitcoin price is driven by supply and demand..."}, ...]`. None of these have anything to do with cats or mats.
- **Root cause:** `services/web-api/main.py:154-165` — `_query_facts` splits the query on whitespace and increments a score for every word that appears as a substring in any cached claim. Any query containing "is", "the", "on", "a", etc. matches every cached fact. No stopword filter. No minimum-overlap threshold. No semantic check.
- **Why it's a showstopper:** the endpoint then SHORT-CIRCUITS the entire pipeline at `main.py:730-749`, returns `total_sources:N` with `sources:[]`, and labels everything `quality:"verified"`. Result: a self-hosted "research" API that confidently fabricates citations for any query.
- **Fix (minutes):** require ALL non-stopword query terms to match, or compute Jaccard ≥ 0.5, or just disable the fact-DB until a semantic match is wired through vector-store. The Redis cache already covers the cache-hit case; the fact-DB is a net negative.

### N2. CRITICAL — Fact-DB writes to a non-volume path; persistence is illusory
- **Evidence:** `main.py:85` `FACT_DB_PATH = Path(os.environ.get("FACT_DB_PATH", "/app/volumes/data/facts.json"))`. Compose mounts the `web_api_data` volume at `/app/data` (`infra/docker-compose.yml:234`), not `/app/volumes/data`. There is NO `FACT_DB_PATH` env override in the compose file (unlike `HASH_DB_PATH=/app/data/embed_hashes.json` at line 232).
- **Result:** `/app/volumes/data/facts.json` lives inside the container's writable layer. `docker compose down` or `docker rm` wipes it. After ~2 minutes of live use I had 10 cached facts (6 Rust, 4 Bitcoin); a `docker compose down && up` would dump them.
- **Fix:** add `FACT_DB_PATH=/app/data/facts.json` next to the HASH_DB_PATH line in compose. One line.

### N3. HIGH — vector-store cold-start downloads 79 MB ONNX model with no warm-up gate
- **Live proof:** After `compose up`, `dss-vector-store` reports `(healthy)` in Docker, but `curl http://localhost:8083/dss/vectors/health` times out at 8s for 10+ minutes. Logs show `chroma-onnx-models.s3.amazonaws.com/all-MiniLM-L6-v2/onnx.tar.gz` downloading at ~150–300 kiB/s.
- **Impact:** Any aggregate request with `enable_rag:true` blocks for ~10 minutes on first boot. `/dss/api/aggregate {"query":"explain bitcoin","use_rag":true}` timed out at 30s during the audit. No clear error to the caller — just a hang.
- **Compounding:** No volume cache for `/root/.cache/chroma/onnx_models/`. Every container recreation re-downloads the 79 MB blob.
- **Fix:** bake the model into the image, OR mount `/root/.cache/chroma` to a named volume, OR gate the health check on model-ready instead of process-up.

### N4. HIGH — Groq provider is dead, but still listed in `/v1/models`
- **Live proof:** `POST /v1/chat/completions {"model":"llama-3.1-8b-instant",...}` → `HTTP 401 {"error":{"message":"Invalid API Key"}}`. `GET /v1/models` still lists 4 Groq models as available.
- **Impact:** Cascade routing can still pick Groq → user-facing 401. Currently masked because deepseek-chat is the cascade default and works.
- **Fix:** rotate the Groq key OR drop Groq from `services/inference-gateway/config/*.yml`. If you want it, /loop the cascade to skip 401-responding providers automatically.

---

## 3. DEAD WEIGHT & WORKING-TREE LITTER

- `infra/docker-compose.dss.yml` (276 lines): not referenced by Makefile. Still defines `whoogle` service and `INFERENCE_GATEWAY_URL=http://inference_gateway:8005` (underscore — broken hostname). **Delete or rewrite.**
- `infra/docker-compose.light.yml` and `infra/docker-compose.test.yml`: stack files exist but their Makefile targets aren't documented; verify they still parse and reflect current service set.
- 7 deleted files under `testing/` sitting uncommitted in working tree (replaced by `tests/`). Either `git add -A` to commit the deletions or `git restore testing/`.
- web-api `main.py:1058` still self-identifies as `"DeepSearch Web API Orchestrator"` — fine, but `main.py:710` docstring still says "replaces deepsearch (8001) and web-api (8014)", which is migration-era cruft.

---

## 4. WHAT ACTUALLY WORKS (proof, not promises)

| Endpoint | Status | Evidence |
|----------|--------|----------|
| `GET /health` (nginx) | 200 in 1ms | `{"status":"ok","proxy":"dss-nginx"}` |
| `POST /dss/api/aggregate` (no RAG, cold) | 200 in **29s** | 10 sources, 7 providers (arxiv/github/hackernews/searxng/stackexchange/wikipedia/yacy), 7 consensus claims, full LLM synthesis |
| `GET /dss/gateway/providers` | 200 | 12 providers enabled |
| Search-gateway internal fan-out | 7 providers × ~2.4s | container logs show real 200s from each provider |
| `POST /dss/crawl/crawl` (Wikipedia/Rust) | 200, 500 KB markdown | full-page extraction, WAL-mode SQLite cache |
| `GET /dss/warehouse/health` | 200 | `{"status":"healthy","total_entries":53}` |
| `POST /v1/chat/completions` (deepseek-chat) | 200 in 1.4s | `pong` ✓ |
| `POST /v1/chat/completions` (deepseek-v4-flash via opencode) | 200 in 1.8s | works |
| `POST /v1/chat/completions` (llama-3.1-8b-instant via groq) | **401** | dead key — see N4 |
| `GET /dss/vectors/health` | **timeout** (cold) | see N3 |

---

## 5. PRIORITY PUNCH LIST

| # | Issue | Effort | Action |
|---|-------|--------|--------|
| 1 | N1 — fact-DB false positives | 5 lines | Patch `_query_facts` (stopword filter + min-overlap) or disable. |
| 2 | T1 — live API keys on disk | 2 min | Rotate Gemini/Groq/DeepSeek at provider consoles; move to secret manager or wipe. |
| 3 | N2 — fact-DB not persisted | 1 line | Add `FACT_DB_PATH=/app/data/facts.json` to compose web-api env. |
| 4 | N3 — vector-store cold start | volume mount or Dockerfile bake | Cache `/root/.cache/chroma` OR add real readiness probe. |
| 5 | N4 — Groq 401 | env | Rotate key, or drop Groq from inference-gateway providers. |
| 6 | Dead `infra/docker-compose.dss.yml` | 1 min | Delete (it's stale). |
| 7 | Working-tree `testing/` deletions | 30s | `git add -A && git commit -m "chore: drop legacy testing/ dir (replaced by tests/)"` |

Items 1–3 are quick. Do them before the next push and the stack moves from "boots and lies sometimes" to "boots and gives real answers."

---

**Auditor's note:** The previous audit's CRITICAL/HIGH items that *were* fixed are well fixed — the boot is clean, nginx routes work, the orchestrator returns real synthesized output. The frustration is justified at the *project*, not at the *work*; the gap is between "boots" and "trustworthy under arbitrary input", and that gap right now is one bad function (`_query_facts`).
