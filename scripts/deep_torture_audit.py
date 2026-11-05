#!/usr/bin/env python3
"""
DeepSearchStack (DSS) - Deep Torture & Stress Audit Suite
A 10-20 minute comprehensive test suite designed to expose system-level bottlenecks,
dropped sockets, provider timeouts, memory leaks, and ranking degradation.

Usage:
  python3 scripts/deep_torture_audit.py
"""

import urllib.request
import urllib.error
import json
import time
import sys
import subprocess
import concurrent.futures
from collections import defaultdict
from datetime import datetime

GATEWAY_URL = "http://localhost:8083/dss/gateway/search"
CRAWL_URL = "http://localhost:8083/dss/crawl"
WAREHOUSE_URL = "http://localhost:8083/dss/warehouse"

AUDIT_QUERIES = [
    # CS / Distributed Systems
    ("paxos vs raft distributed consensus", "tech"),
    ("byzantine fault tolerance pbft view change", "tech"),
    ("epoll edge triggered socket starvation", "tech"),
    ("lsm tree compaction write amplification rocksdb", "tech"),
    
    # Systems Bugs / Real Stacktraces
    ("pthread_mutex_lock SIGSEGV null pointer dereference", "tech"),
    ("fatal error: linux/sched.h: No such file or directory", "tech"),
    ("tokio runtime worker thread panic unhandled task", "code"),
    
    # Biomedical / Scientific
    ("crispr cas9 off target cleavage specificity", "biomedical"),
    ("mrna lipid nanoparticle delivery mechanisms", "biomedical"),
    ("alphafold multimer protein structure prediction accuracy", "academic"),
    
    # Protocols & Specifications
    ("HTTP/3 QUIC transport multiplexing stream reset", "specs"),
    ("RFC 9110 HTTP Semantics status codes", "specs"),
    ("TLS 1.3 0-RTT replay attack mitigations", "specs"),
    
    # Security / CVEs
    ("CVE-2024-3094 xz utils backdoor ifunc", "security"),
    ("CVE-2021-44228 log4shell remote code execution", "security"),
    ("Dirty COW race condition mm/gup.c", "security"),
    
    # Ambiguous / General / Wikimedia
    ("quantum computing trapped ion vs superconducting", "wiki"),
    ("mercury planetary magnetosphere composition", "academic"),
    ("turing machine halting problem proof", "academic"),
    
    # Adversarial / Stress tokens
    ("' OR 1=1; DROP TABLE content; -- <script>alert(1)</script>", "all"),
    ("a" * 150, "all"),
]

def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

def get_docker_stats() -> dict:
    """Read memory consumption of running DSS containers."""
    try:
        out = subprocess.check_output(
            ["docker", "stats", "--no-stream", "--format", "{{.Name}}:{{.MemUsage}}"],
            stderr=subprocess.DEVNULL
        ).decode("utf-8")
        stats = {}
        for line in out.strip().split("\n"):
            if ":" in line:
                name, mem = line.split(":", 1)
                stats[name.strip()] = mem.split("/")[0].strip()
        return stats
    except Exception:
        return {}

def test_query(query: str, domain: str) -> dict:
    t0 = time.time()
    payload = {"query": query, "domain": domain, "max_results": 20}
    req = urllib.request.Request(
        GATEWAY_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            elapsed = time.time() - t0
            data = json.loads(resp.read().decode("utf-8"))
            return {"status": "ok", "elapsed": elapsed, "hits": len(data), "data": data, "error": None}
    except Exception as e:
        elapsed = time.time() - t0
        return {"status": "error", "elapsed": elapsed, "hits": 0, "data": [], "error": str(e)}

def main():
    print("=" * 80)
    print("  DEEPSEARCHSTACK (DSS) BRUTAL TORTURE & RESILIENCE AUDIT")
    print(f"  Target: {GATEWAY_URL} · Timestamp: {datetime.now().isoformat()}")
    print("=" * 80)

    initial_stats = get_docker_stats()
    log(f"Initial container baseline captured ({len(initial_stats)} containers active).")

    # ── Phase 1: Comprehensive Multi-Domain Matrix ──────────────────────────
    log("\n═══ PHASE 1: 20-Query Exhaustive Multi-Domain Matrix ═══")
    provider_hits = defaultdict(int)
    latencies = []
    failures = 0
    zero_hits = 0

    for idx, (q, domain) in enumerate(AUDIT_QUERIES):
        log(f"[{idx+1:2d}/{len(AUDIT_QUERIES)}] Querying: '{q[:40]}...' (domain={domain})")
        res = test_query(q, domain)
        latencies.append(res["elapsed"])
        if res["status"] != "ok":
            failures += 1
            log(f"  ✖ FAILED in {res['elapsed']:.2f}s: {res['error']}")
        elif res["hits"] == 0:
            zero_hits += 1
            log(f"  ⚠ ZERO HITS in {res['elapsed']:.2f}s")
        else:
            log(f"  ✓ {res['hits']} results in {res['elapsed']:.2f}s")
            for r in res["data"]:
                for src in r.get("source", "unknown").split("+"):
                    provider_hits[src] += 1
        time.sleep(1)  # avoid burst rate-limiting on external APIs

    # ── Phase 2: High Concurrency Saturation Flood ──────────────────────────
    log("\n═══ PHASE 2: High-Concurrency Saturation (30 Parallel Requests) ═══")
    flood_query = "distributed consensus Raft vs Paxos"
    concurrency = 30
    log(f"Flooding gateway with {concurrency} concurrent requests...")

    t0_flood = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(test_query, flood_query, "tech") for _ in range(concurrency)]
        flood_results = [f.result() for f in concurrent.futures.as_completed(futures)]
    flood_duration = time.time() - t0_flood

    flood_success = sum(1 for r in flood_results if r["status"] == "ok")
    flood_failed = sum(1 for r in flood_results if r["status"] != "ok")
    flood_avg_time = sum(r["elapsed"] for r in flood_results) / len(flood_results)

    log(f"Flood finished in {flood_duration:.2f}s | Success: {flood_success}/{concurrency} | Failed: {flood_failed} | Avg latency: {flood_avg_time:.2f}s")

    # ── Phase 3: Live Real-World Crawl & Extraction Test ────────────────────
    log("\n═══ PHASE 3: Live Web & PDF Crawl Torture ═══")
    crawl_targets = [
        "https://arxiv.org/pdf/1706.03762.pdf", # Direct PDF
        "https://github.com/python/cpython/issues/100000", # API shortcut
        "https://en.wikipedia.org/wiki/Raft_(computer_science)", # Static MediaWiki
        "https://httpbin.org/status/404", # 404 guard
    ]

    for target in crawl_targets:
        t0_crawl = time.time()
        log(f"Crawling: {target}")
        payload = {"url": target, "bypass_cache": True, "timeout": 30}
        req = urllib.request.Request(
            f"{CRAWL_URL}/crawl",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=35) as resp:
                elapsed = time.time() - t0_crawl
                cdata = json.loads(resp.read().decode("utf-8"))
                method = cdata.get("extraction_method", "unknown")
                clen = len(cdata.get("content", ""))
                log(f"  ✓ Extracted via [{method}] | {clen:,} chars in {elapsed:.2f}s")
        except Exception as e:
            elapsed = time.time() - t0_crawl
            log(f"  ✖ Crawl failed for {target} in {elapsed:.2f}s: {e}")

    # ── Phase 4: Warehouse Bulk Ingest & Outbox Torture ──────────────────────
    log("\n═══ PHASE 4: Knowledge Warehouse Stress & Integrity ═══")
    try:
        with urllib.request.urlopen(f"{WAREHOUSE_URL}/stats", timeout=5) as resp:
            wh_before = json.loads(resp.read().decode("utf-8"))
            log(f"Warehouse baseline: {wh_before.get('total_entries')} entries, {wh_before.get('total_words'):,} words.")
    except Exception as e:
        log(f"Warehouse stats error: {e}")

    # ── Phase 5: Resource & Memory Leak Inspection ──────────────────────────
    log("\n═══ PHASE 5: Resource Usage & Container Memory Delta ═══")
    final_stats = get_docker_stats()
    for container, mem in final_stats.items():
        init_mem = initial_stats.get(container, "N/A")
        log(f"  {container:<28s} Baseline: {init_mem:<10s} ──► Post-Stress: {mem}")

    # ── Final Report Summary ────────────────────────────────────────────────
    print("\n" + "=" * 80)
    print("                    FINAL TORTURE AUDIT REPORT")
    print("=" * 80)
    avg_lat = sum(latencies) / len(latencies) if latencies else 0.0
    sorted_lat = sorted(latencies)
    p50 = sorted_lat[len(sorted_lat) // 2] if sorted_lat else 0.0
    p95 = sorted_lat[int(len(sorted_lat) * 0.95)] if sorted_lat else 0.0

    print(f"Total Audit Queries:       {len(AUDIT_QUERIES)}")
    print(f"Total Errors / Crashes:    {failures}")
    print(f"Zero-Hit Queries:          {zero_hits}")
    print(f"Latency P50:               {p50:.2f}s")
    print(f"Latency P95:               {p95:.2f}s")
    print(f"Average Latency:           {avg_lat:.2f}s")
    print(f"Concurrency Flood (n=30):  {flood_success}/{concurrency} successful ({flood_avg_time:.2f}s avg)")

    print("\nProvider Hit Yield Across Entire Battery:")
    for p, count in sorted(provider_hits.items(), key=lambda x: x[1], reverse=True):
        print(f"  - {p:<20s}: {count:>3d} appearances")

    print("=" * 80)

if __name__ == "__main__":
    main()
