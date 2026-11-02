#!/usr/bin/env bash
# E2E smoke suite for DSS. Exit 0 if everything passes, non-zero count = bugs.
# Each test prints "PASS" / "FAIL" + a short reason. Doesn't bail on failures —
# walks the whole matrix so we collect every bug in one pass.

set -u  # but NOT -e — we want to keep going through failures
BASE="${BASE:-http://localhost:8083}"
CLI="${CLI:-./clients/cli-go/dss}"

PASS=0
FAIL=0
FAILS=()

T() {
  local name="$1" cmd="$2" expect="$3"
  local out
  out=$(bash -c "$cmd" 2>&1)
  if echo "$out" | grep -qE "$expect"; then
    PASS=$((PASS+1))
    printf "  \033[32m✓\033[0m %s\n" "$name"
  else
    FAIL=$((FAIL+1))
    FAILS+=("$name")
    printf "  \033[31m✗\033[0m %s\n" "$name"
    printf "      cmd:    %s\n" "$cmd"
    printf "      expect: %s\n" "$expect"
    printf "      got:    %s\n" "$(echo "$out" | head -c 200)"
  fi
}

section() { printf "\n\033[36m── %s\033[0m\n" "$1"; }

section "1. Health"
T "stack health" "curl -fs $BASE/health" '"status":"ok"'
T "crawler health" "curl -fs $BASE/dss/crawl/health" '"status":"healthy"'
T "warehouse health" "curl -fs $BASE/dss/warehouse/health" '"status":"healthy"'
T "vector-store health" "curl -fs $BASE/dss/vectors/health" '"status"'
T "search-gateway health" "curl -fs $BASE/dss/gateway/health" '"status":"healthy"'
T "search-agent health" "curl -fs $BASE/dss/agent/health" '"status":"healthy"'
T "web-api health" "curl -fs $BASE/dss/api/health" '"status":"ok"'

section "2. Warehouse — basic CRUD"
T "stats has categories field" "curl -fs $BASE/dss/warehouse/stats" '"categories"'
T "list returns >=1 row" "curl -fs '$BASE/dss/warehouse/list?limit=5' | python3 -c 'import sys,json; sys.exit(0 if len(json.load(sys.stdin))>0 else 1)'" 'PASS|^$'
T "list with --category doc returns docs" "curl -fs '$BASE/dss/warehouse/list?category=doc&limit=3' | python3 -c 'import sys,json; d=json.load(sys.stdin); sys.exit(0 if all(r.get(chr(99)+chr(97)+chr(116)+chr(101)+chr(103)+chr(111)+chr(114)+chr(121))==chr(100)+chr(111)+chr(99) for r in d) else 1)'" '^$'
T "by-url for known row" "curl -fs '$BASE/dss/warehouse/content/by-url?url=https://en.wikipedia.org/wiki/Distributed_computing'" '"id":'
T "by-url 404 for bogus" "curl -s -o /dev/null -w '%{http_code}' '$BASE/dss/warehouse/content/by-url?url=https://nope.nope/'" '404'
T "get-by-id returns row" "curl -fs $BASE/dss/warehouse/content/3" '"id":3'
T "get-by-id 404 for missing" "curl -s -o /dev/null -w '%{http_code}' $BASE/dss/warehouse/content/9999999" '404'

section "3. Warehouse — hybrid search"
T "hybrid returns hits" "curl -fs '$BASE/dss/api/search/hybrid?q=rust&limit=5' | python3 -c 'import sys,json; d=json.load(sys.stdin); sys.exit(0 if len(d.get(\"hits\",[]))>0 else 1)'" '^$'
T "hybrid has fts_rank or vec_rank" "curl -fs '$BASE/dss/api/search/hybrid?q=python&limit=5' | python3 -c 'import sys,json; d=json.load(sys.stdin); sys.exit(0 if d[\"hits\"][0].get(\"fts_rank\") or d[\"hits\"][0].get(\"vec_rank\") else 1)'" '^$'

section "4. Crawler — generic"
T "crawl a static page" "curl -fs -X POST '$BASE/dss/crawl/crawl' -H 'content-type: application/json' -d '{\"url\":\"https://example.com\",\"bypass_cache\":true,\"timeout\":30}'" '"success":true'
T "crawl 404 on non-CDN site short-circuits" "curl -fs -X POST '$BASE/dss/crawl/crawl' -H 'content-type: application/json' -d '{\"url\":\"https://httpbin.org/status/404\",\"bypass_cache\":true,\"timeout\":15}'" '"extraction_method":"head-404"|"success":false'

section "5. Crawler — domain shortcuts"
T "arxiv abs returns arxiv-api" "curl -fs -X POST '$BASE/dss/crawl/crawl' -H 'content-type: application/json' -d '{\"url\":\"https://arxiv.org/abs/1706.03762\",\"bypass_cache\":true,\"timeout\":30}'" '"extraction_method":"arxiv-api"'
T "github issue returns github-api" "curl -fs -X POST '$BASE/dss/crawl/crawl' -H 'content-type: application/json' -d '{\"url\":\"https://github.com/python/cpython/issues/100000\",\"bypass_cache\":true,\"timeout\":30}'" '"extraction_method":"github-api"'
T "arxiv PDF returns pdf method" "curl -fs -X POST '$BASE/dss/crawl/crawl' -H 'content-type: application/json' -d '{\"url\":\"https://arxiv.org/pdf/1706.03762.pdf\",\"bypass_cache\":true,\"timeout\":60}'" '"extraction_method":"pdf"'

section "6. Async ingest queue"
T "queue-urls returns job_id" "curl -fs -X POST '$BASE/dss/crawl/ingest/urls/async' -H 'content-type: application/json' -d '{\"urls\":[\"https://example.com\"],\"concurrency\":1}'" '"job_id":'
T "list jobs has at least 1" "curl -fs '$BASE/dss/crawl/ingest-jobs?limit=5' | python3 -c 'import sys,json; d=json.load(sys.stdin); sys.exit(0 if d[\"count\"]>0 else 1)'" '^$'
T "filter jobs by status" "curl -fs '$BASE/dss/crawl/ingest-jobs?status=done&limit=2'" '"status":"done"'
T "get specific job by id" "curl -fs $BASE/dss/crawl/ingest-jobs/1" '"id":1'
T "404 on bogus job id" "curl -s -o /dev/null -w '%{http_code}' $BASE/dss/crawl/ingest-jobs/9999999" '404'

section "7. Watcher (RSS feeds)"
T "list feeds endpoint works" "curl -fs $BASE/dss/warehouse/watch/feeds" '"feeds":'
T "404 on bogus feed poll" "curl -s -o /dev/null -w '%{http_code}' -X POST $BASE/dss/warehouse/watch/feeds/9999999/poll-now" '404'
T "409 on duplicate feed add" "curl -s -o /dev/null -w '%{http_code}' -X POST $BASE/dss/warehouse/watch/feeds -H 'content-type: application/json' -d '{\"feed_url\":\"https://simonwillison.net/atom/everything/\",\"interval_sec\":3600}'" '409'

section "8. Aggregate (web-api)"
T "aggregate basic" "curl -fs -X POST '$BASE/dss/api/aggregate' -H 'content-type: application/json' -d '{\"query\":\"rust\",\"max_results\":3,\"include_warehouse\":true,\"enable_scraping\":false,\"enable_synthesis\":false}'" '"total_sources":'
T "providers endpoint" "curl -fs $BASE/dss/gateway/providers" 'duckduckgo|wikipedia'
T "models endpoint" "curl -fs $BASE/dss/api/providers" '"models":'

section "9. CLI commands"
T "dss health succeeds" "$CLI health" '✓ stack ok'
T "dss warehouse stats" "$CLI warehouse stats" 'entries:'
T "dss warehouse list" "$CLI warehouse list --limit 3" 'id='
T "dss warehouse list --category doc" "$CLI warehouse list --category doc --limit 3" 'id='
T "dss warehouse hybrid" "$CLI warehouse hybrid --limit 3 rust" 'Hybrid'
T "dss warehouse by-url" "$CLI warehouse by-url https://en.wikipedia.org/wiki/Distributed_computing" 'Row '
T "dss --json warehouse get" "$CLI --json warehouse get 3" '"id": 3'
T "dss models" "$CLI models" 'Models'
T "dss providers" "$CLI providers" 'providers'
T "dss jobs" "$CLI jobs" 'Ingest jobs'
T "dss jobs --status done" "$CLI --json jobs --status done | python3 -c 'import sys,json; d=json.load(sys.stdin); sys.exit(0 if len(d[\"jobs\"])>0 else 1)'" '^$'
T "dss watches" "$CLI watches" 'Watched feeds'
T "dss --no-color works" "$CLI --no-color health" 'stack ok'

section "10. End-to-end: queue → crawl → warehouse → hybrid"
JOB_ID=$($CLI --json jobs queue-urls --concurrency 2 'https://en.wikipedia.org/wiki/Paxos_(computer_science)' 2>/dev/null | python3 -c 'import sys,json; print(json.load(sys.stdin)["job_id"])' 2>/dev/null || echo "")
if [ -n "$JOB_ID" ]; then
  echo "  queued job_id=$JOB_ID, waiting up to 60s..."
  for i in $(seq 1 30); do
    status=$(curl -fs $BASE/dss/crawl/ingest-jobs/$JOB_ID | python3 -c 'import sys,json; print(json.load(sys.stdin)["status"])' 2>/dev/null)
    [ "$status" = "done" ] && break
    [ "$status" = "failed" ] && break
    sleep 2
  done
  T "queue→job done" "echo $status" 'done'
  T "row landed in warehouse" "curl -fs '$BASE/dss/warehouse/content/by-url?url=https://en.wikipedia.org/wiki/Paxos_(computer_science)'" '"id":'
  T "row has category" "curl -fs '$BASE/dss/warehouse/content/by-url?url=https://en.wikipedia.org/wiki/Paxos_(computer_science)' | python3 -c 'import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get(chr(99)+chr(97)+chr(116)+chr(101)+chr(103)+chr(111)+chr(114)+chr(121)) else 1)'" '^$'
  T "row reachable by hybrid" "curl -fs '$BASE/dss/api/search/hybrid?q=paxos+consensus&limit=5' | grep -c paxos" '[1-9]'
else
  printf "  \033[31m✗\033[0m E2E queue setup failed\n"
  FAIL=$((FAIL+4))
fi

printf "\n══ RESULTS ══\n"
printf "  \033[32mPASS\033[0m: %d\n" "$PASS"
printf "  \033[31mFAIL\033[0m: %d\n" "$FAIL"
if [ "$FAIL" -gt 0 ]; then
  printf "\nFailing tests:\n"
  for f in "${FAILS[@]}"; do
    printf "  - %s\n" "$f"
  done
  exit 1
fi
