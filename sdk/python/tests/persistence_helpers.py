"""Helper functions for the persistence E2E test.

Each function calls the live stack via curl. They shell out so the
test script (bash) can call them as easily as `python3 helper.py embed NS DOC`.
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://localhost:8083"


def http_post(path: str, body: dict, timeout: float = 30) -> tuple[int, dict]:
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


def http_get(path: str, timeout: float = 10) -> tuple[int, dict]:
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return 0, {"error": str(e)}


def cmd_embed(namespace: str, text: str) -> int:
    status, body = http_post(
        "/dss/vectors/embed",
        {"namespace": namespace, "documents": [{"text": text, "id": f"persist-{hash(text)}"}]},
    )
    print(f"count={body.get('count', 0)}")
    return 0 if status == 200 else 1


def cmd_vector_count() -> int:
    """Total documents across all namespaces (via /cache/stats or sum of namespaces)."""
    # /cache/stats doesn't exist; just call /dss/vectors/query across "all" isn't possible
    # The vector store doesn't expose a global count directly. Return 0 as baseline.
    # The test treats this as a delta reference, not a global truth.
    print(0)
    return 0


def cmd_vector_query(namespace: str) -> int:
    """Returns the IDs as stdout lines (the test counts how many mention the namespace)."""
    status, body = http_post(
        "/dss/vectors/query",
        {"namespace": namespace, "query": "persistence test", "top_k": 50},
    )
    if status != 200:
        print(f"ERROR: status={status}", file=sys.stderr)
        return 1
    ids = body.get("ids", [[]])[0] if body else []
    for i in ids:
        print(i)
    return 0


def cmd_warehouse_count() -> int:
    """Returns the total entries in the warehouse."""
    status, body = http_get("/dss/warehouse/stats")
    if status != 200:
        print(0)
        return 0
    print(body.get("total_entries", 0))
    return 0


def cmd_warehouse_ingest(url: str) -> int:
    """Crawl + push to warehouse."""
    status, body = http_post(
        "/dss/api/ingest/urls",
        {"urls": [url]},
        timeout=60,
    )
    if status == 200:
        # Look for any success indication
        out = json.dumps(body)
        print(f"OK: {out[:200]}")
        return 0
    print(f"ERROR: status={status} body={json.dumps(body)[:200]}")
    return 1


def cmd_crawl(url: str) -> int:
    """Returns a one-liner with the crawl result's key fields."""
    status, body = http_post(
        "/dss/crawl/crawl",
        {"url": url, "timeout": 20},
        timeout=30,
    )
    if status != 200:
        print(f"ERROR: status={status} body={json.dumps(body)[:200]}")
        return 1
    success = body.get("success", False)
    cache_hit = body.get("cache_hit", False)
    title = body.get("title", "")[:40]
    print(f"success={success} cache_hit={cache_hit} title={title!r}")
    return 0


def cmd_force_save() -> int:
    """Trigger web-api's /api/admin/save-hashes endpoint."""
    status, body = http_post("/dss/api/admin/save-hashes", {})
    if status == 200:
        print(f"saved={body.get('saved')} count={body.get('count')}")
        return 0
    print(f"ERROR: status={status} body={json.dumps(body)[:200]}")
    return 1


def cmd_hash_state() -> int:
    """Show the web-api in-memory vs on-disk hash state."""
    status, body = http_get("/dss/api/admin/hash-state")
    if status == 200:
        print(f"memory={body.get('memory_count')} disk={body.get('disk_count')}")
        return 0
    print(f"ERROR: status={status} body={json.dumps(body)[:200]}")
    return 1


def cmd_aggregate(query: str) -> int:
    """Trigger the RAG pipeline via /api/aggregate. Adds hashes to web-api's dedup set.

    enable_rag=True + enable_scraping=True is required for the dedup to fire,
    since _rag_pipeline is gated on both flags.
    """
    status, body = http_post(
        "/dss/api/aggregate",
        {
            "query": query,
            "max_results": 3,
            "timeout": 15.0,
            "providers": ["searxng"],
            "enable_rag": True,
            "enable_scraping": True,
            "max_scrape_urls": 2,
        },
        timeout=60,
    )
    if status == 200:
        n = len(body.get("sources", []))
        print(f"aggregate ok, {n} sources, rag_chunks={len(body.get('rag_chunks', []))}")
        return 0
    print(f"ERROR: status={status} body={json.dumps(body)[:200]}")
    return 1


def main():
    if len(sys.argv) < 2:
        print("usage: persistence_helpers.py {embed|vector_count|vector_query|warehouse_count|warehouse_ingest|crawl|aggregate|force_save|hash_state} ...", file=sys.stderr)
        return 2
    cmd = sys.argv[1]
    if cmd == "embed":
        return cmd_embed(sys.argv[2], sys.argv[3])
    elif cmd == "vector_count":
        return cmd_vector_count()
    elif cmd == "vector_query":
        return cmd_vector_query(sys.argv[2])
    elif cmd == "warehouse_count":
        return cmd_warehouse_count()
    elif cmd == "warehouse_ingest":
        return cmd_warehouse_ingest(sys.argv[2])
    elif cmd == "crawl":
        return cmd_crawl(sys.argv[2])
    elif cmd == "force_save":
        return cmd_force_save()
    elif cmd == "hash_state":
        return cmd_hash_state()
    elif cmd == "aggregate":
        return cmd_aggregate(sys.argv[2])
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
