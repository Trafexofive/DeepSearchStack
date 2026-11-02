#!/usr/bin/env python3
"""
REAL deep-search workflow — aggregation + scraping + warehousing + cascade.

Goal: exercise the actual pipeline end-to-end on a fresh topic, prove each
layer fires with real data (not toy single-fetch), and demonstrate the
warehouse + vector cascade hit on a follow-up query.

Run:  python3 scripts/sdk_deepsearch_workflow.py
"""
import sys, json, time, asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk" / "python"))
from deepsearch import AsyncDeepSearchClient

BASE = "http://localhost:8083"
# Fresh, narrow topic that won't collide with the seeded fact-DB ("rust", "bitcoin"):
TOPIC = "Erlang BEAM scheduler reduction counting"
FOLLOWUP = "BEAM virtual machine preemptive scheduling internals"


def hdr(n, name):
    print(f"\n{'═'*78}\n[STEP {n}] {name}\n{'═'*78}")


def truncate(s, n=400):
    s = str(s)
    return s if len(s) <= n else s[:n] + f"… ({len(s)} chars total)"


async def main():
    print(f"DSS deep-search workflow — base={BASE}  time={time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"topic    = {TOPIC!r}")
    print(f"followup = {FOLLOWUP!r}")
    async with AsyncDeepSearchClient(base_url=BASE, timeout=180) as c:

        # ── BASELINE ───────────────────────────────────────────────────────
        hdr(0, "BASELINE — warehouse + facts BEFORE the workflow runs")
        r = await c.client.get(f"{BASE}/dss/warehouse/stats", timeout=10)
        wh_before = r.json() if r.status_code == 200 else {}
        r = await c.client.get(f"{BASE}/dss/api/facts", timeout=10)
        fb_before = r.json() if r.status_code == 200 else {}
        print(f"warehouse_total_entries = {wh_before.get('total_entries')}")
        print(f"fact_db_total           = {fb_before.get('total')}")

        # ── 1. PROVE N1 IS PATCHED ─────────────────────────────────────────
        hdr(1, "N1 regression check — 'the dog is on the floor' must NOT hit fact-DB")
        r = await c.client.post(
            f"{BASE}/dss/api/aggregate",
            json={"query": "the dog is on the floor", "max_results": 2, "reconcile": False, "enable_synthesis": False},
            timeout=60,
        )
        d = r.json()
        hit = d.get("fact_db_hit")
        print(f"fact_db_hit = {hit}   (PASS if False)")
        print(f"total_sources = {d.get('total_sources')}  ← real sources, not cached cross-topic facts")

        # ── 2. FAN-OUT — search-gateway across all default providers ───────
        hdr(2, "search() — multi-provider fan-out on a fresh topic")
        t0 = time.time()
        sr, err = await c.search(query=TOPIC, max_results=12)
        print(f"err={err}  elapsed={time.time()-t0:.2f}s")
        if sr:
            sources_seen = {}
            for hit in sr.hits:
                sources_seen[hit.source] = sources_seen.get(hit.source, 0) + 1
            print(f"total_hits = {len(sr.hits)}")
            print(f"providers  = {sources_seen}")
            print("\nFirst 6 hits:")
            for hit in sr.hits[:6]:
                print(f"  • [{hit.source:14s}] {truncate(hit.title, 90)}")
                print(f"    {hit.url}")
            scrape_urls = [h.url for h in sr.hits[:5] if h.url.startswith("http")]
        else:
            scrape_urls = []

        # ── 3. REAL AGGREGATION — full pipeline (scrape+warehouse+synth) ───
        hdr(3, "aggregate() with enable_scraping + include_warehouse + synthesis")
        t0 = time.time()
        r = await c.client.post(
            f"{BASE}/dss/api/aggregate",
            json={
                "query": TOPIC,
                "max_results": 8,
                "include_warehouse": True,
                "reconcile": True,
                "enable_scraping": True,
                "max_scrape_urls": 5,
                "enable_synthesis": True,
            },
            timeout=180,
        )
        elapsed = time.time() - t0
        print(f"http={r.status_code}  elapsed={elapsed:.2f}s")
        if r.status_code == 200:
            d = r.json()
            print(f"  total_sources    = {d.get('total_sources')}")
            print(f"  domains_queried  = {d.get('domains_queried')}")
            print(f"  scraped_urls     = {d.get('scraped_urls')}")
            print(f"  rag_chunks       = {d.get('rag_chunks')}")
            print(f"  fact_db_hit      = {d.get('fact_db_hit')}")
            print(f"  execution_time_ms= {d.get('execution_time_ms')}")
            srcs = d.get("sources", [])
            print(f"\n  Sources by provider (top {min(8,len(srcs))}):")
            for s in srcs[:8]:
                print(f"    • [{s.get('source'):14s}] conf={s.get('confidence',0):.2f}  {truncate(s.get('title',''), 78)}")
            cons = d.get("consensus") or []
            print(f"\n  Consensus claims ({len(cons)}):")
            for fact in cons[:6]:
                supp = fact.get("supporting_sources", [])
                print(f"    • [{fact.get('quality'):9s} {fact.get('confidence',0):.2f}] {truncate(fact.get('claim',''), 110)}")
                print(f"      sources={supp}")
            syn = d.get("synthesis") or d.get("answer") or ""
            print(f"\n  Synthesis ({len(syn)} chars):")
            for line in syn.split("\n"):
                print(f"    {line}")
        else:
            print(f"  ERROR body: {r.text[:500]}")

        # ── 4. WAREHOUSE DELTA ─────────────────────────────────────────────
        hdr(4, "warehouse delta — should grow from baseline")
        await asyncio.sleep(2)  # let async seed_warehouse settle
        r = await c.client.get(f"{BASE}/dss/warehouse/stats", timeout=10)
        wh_after = r.json() if r.status_code == 200 else {}
        delta = (wh_after.get("total_entries", 0) or 0) - (wh_before.get("total_entries", 0) or 0)
        print(f"warehouse_total_entries before = {wh_before.get('total_entries')}")
        print(f"warehouse_total_entries after  = {wh_after.get('total_entries')}")
        print(f"delta                          = +{delta}")

        # ── 5. WAREHOUSE SEARCH — find what we just stored ─────────────────
        hdr(5, "warehouse_search() — query the freshly indexed corpus")
        ws, err = await c.warehouse_search("BEAM scheduler")
        print(f"err={err}")
        if ws is not None:
            try:
                items = list(ws) if hasattr(ws, '__iter__') else []
            except Exception:
                items = []
            print(f"hits_on_local_warehouse = {len(items)}")
            for hit in items[:5]:
                title = getattr(hit, 'title', None) or (hit.get('title') if isinstance(hit, dict) else str(hit))
                url = getattr(hit, 'url', '') or (hit.get('url','') if isinstance(hit, dict) else '')
                print(f"  • {truncate(title, 80)}")
                if url:
                    print(f"    {url}")

        # ── 6. FOLLOWUP QUERY — should hit warehouse/vector cascade ────────
        hdr(6, "FOLLOWUP aggregate — semantically related; expect LOCAL CASCADE hit (no external)")
        t0 = time.time()
        r = await c.client.post(
            f"{BASE}/dss/api/aggregate",
            json={
                "query": FOLLOWUP,
                "max_results": 5,
                "include_warehouse": True,
                "reconcile": False,
                "enable_synthesis": False,
            },
            timeout=120,
        )
        elapsed = time.time() - t0
        print(f"http={r.status_code}  elapsed={elapsed:.2f}s")
        if r.status_code == 200:
            d = r.json()
            srcs = d.get("sources", [])
            local_src = sum(1 for s in srcs if s.get("source") in ("warehouse", "vector_store", "internal"))
            external_src = len(srcs) - local_src
            print(f"  total_sources = {d.get('total_sources')}")
            print(f"  local (warehouse/vector) hits = {local_src}")
            print(f"  external hits                 = {external_src}")
            print(f"  fact_db_hit  = {d.get('fact_db_hit')}")
            print(f"  exec_time_ms = {d.get('execution_time_ms')}  ← compare to step 3's value")

        # ── 7. METRICS — counter delta proves the cascade fired ────────────
        hdr(7, "metrics — counter delta")
        r = await c.client.get(f"{BASE}/dss/api/metrics", timeout=10)
        m = r.json() if r.status_code == 200 else {}
        cnt = m.get("counters", {})
        print(f"  aggregate.requests          = {cnt.get('aggregate.requests', 0)}")
        print(f"  aggregate.external_searches = {cnt.get('aggregate.external_searches', 0)}")
        print(f"  aggregate.local_cascade_hits= {cnt.get('aggregate.local_cascade_hits', 0)}")
        print(f"  aggregate.vector_store_hits = {cnt.get('aggregate.vector_store_hits', 0)}")
        print(f"  aggregate.fact_db_hits      = {cnt.get('aggregate.fact_db_hits', 0)}")
        print(f"  aggregate.cache_misses      = {cnt.get('aggregate.cache_misses', 0)}")
        print(f"  reconcile.requests          = {cnt.get('reconcile.requests', 0)}")

    print(f"\n{'═'*78}\nworkflow complete @ {time.strftime('%H:%M:%S')}\n{'═'*78}")


if __name__ == "__main__":
    asyncio.run(main())
