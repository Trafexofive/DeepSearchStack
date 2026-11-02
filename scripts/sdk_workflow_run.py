#!/usr/bin/env python3
"""
SDK workflow runner — real jobs against the running stack.

Each step prints: [STEP n] <name> → outcome + bounded preview of the real payload.
Run with: python3 scripts/sdk_workflow_run.py
"""
import sys, json, time, asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk" / "python"))
from deepsearch import AsyncDeepSearchClient

BASE = "http://localhost:8083"


def hdr(n, name):
    print(f"\n{'─'*72}\n[STEP {n}] {name}\n{'─'*72}")


def truncate(s, n=400):
    s = str(s)
    return s if len(s) <= n else s[:n] + f"… ({len(s)} chars total)"


async def main():
    print(f"DSS SDK workflow runner — base={BASE} time={time.strftime('%Y-%m-%d %H:%M:%S')}")
    async with AsyncDeepSearchClient(base_url=BASE, timeout=120) as c:

        # ─── 1. Health ────────────────────────────────────────────────────
        hdr(1, "health() — every service")
        h, err = await c.health()
        print(f"err={err}")
        if h:
            print(json.dumps(h, indent=2)[:800])

        # ─── 2. Model catalog ─────────────────────────────────────────────
        hdr(2, "list_models() — LLM inference catalog")
        models, err = await c.list_models()
        print(f"err={err}")
        if models:
            print(f"total={len(models)}")
            for m in models[:6]:
                print(f"  • {m.id:40s} provider={m.provider:12s} ctx={m.context_length}")
            if len(models) > 6:
                print(f"  … {len(models)-6} more")

        # ─── 3. LLM completion (proves provider keys work end-to-end) ─────
        hdr(3, "llm_complete() — deepseek-chat round-trip")
        t0 = time.time()
        result, err = await c.llm_complete(
            messages=[{"role": "user", "content": "Reply with exactly: pong"}],
            model="deepseek-chat",
            max_tokens=10,
        )
        print(f"err={err} elapsed={time.time()-t0:.2f}s")
        if result is not None:
            print(f"content={result!r}")

        # ─── 4. Search-gateway fan-out ────────────────────────────────────
        hdr(4, "search() — 3-provider fan-out on a real query")
        t0 = time.time()
        sr, err = await c.search(
            query="rust ownership and borrowing",
            providers=["wikipedia", "stackexchange", "github"],
            max_results=5,
        )
        print(f"err={err} elapsed={time.time()-t0:.2f}s")
        if sr:
            print(f"total_hits={len(sr.hits)}")
            for hit in sr.hits[:5]:
                print(f"  • [{hit.source:14s}] {truncate(hit.title, 80)}")
                print(f"    {hit.url}")

        # ─── 5. Aggregate (golden path) ───────────────────────────────────
        hdr(5, "aggregate() — multi-provider + LLM synthesis (raw POST; SDK drops synth)")
        print("  NOTE: SDK aggregate() at deepsearch.py:280-286 casts to SearchResult")
        print("  and drops consensus/synthesis/fact_db_hit. Calling raw endpoint.\n")
        t0 = time.time()
        r = await c.client.post(
            f"{BASE}/dss/api/aggregate",
            json={"query": "what are the differences between rust and go for systems programming", "max_results": 5},
            timeout=120,
        )
        err = None if r.status_code == 200 else f"HTTP {r.status_code}"
        agg = r.json() if r.status_code == 200 else None
        print(f"err={err} elapsed={time.time()-t0:.2f}s")
        if agg:
            d = agg
            print(f"total_sources={d.get('total_sources')}")
            print(f"domains_queried={d.get('domains_queried')}")
            print(f"fact_db_hit={d.get('fact_db_hit')}")
            print(f"execution_time_ms={d.get('execution_time_ms')}")
            srcs = d.get("sources", [])
            print(f"\n  Sources (first 3 of {len(srcs)}):")
            for s in srcs[:3]:
                print(f"  • [{s.get('source'):12s}] {truncate(s.get('title',''), 80)}")
            cons = d.get("consensus") or []
            print(f"\n  Consensus claims ({len(cons)}):")
            for fact in cons[:4]:
                print(f"  • [{fact.get('quality'):9s} {fact.get('confidence',0):.2f}] {truncate(fact.get('claim',''), 100)}")
            syn = d.get("synthesis") or d.get("answer") or ""
            print(f"\n  Synthesis ({len(syn)} chars):")
            print(f"  {truncate(syn, 600)}")

        # ─── 6. Crawl real page ───────────────────────────────────────────
        hdr(6, "crawl() — full page fetch + markdown extraction")
        t0 = time.time()
        cr, err = await c.crawl("https://en.wikipedia.org/wiki/Rust_(programming_language)")
        print(f"err={err} elapsed={time.time()-t0:.2f}s")
        if cr:
            content = cr.content or ""
            print(f"url={cr.url}")
            print(f"content_length={len(content)} chars")
            print(f"preview: {truncate(content, 300)}")

        # ─── 7. Warehouse search ──────────────────────────────────────────
        hdr(7, "warehouse_search() — local FTS5 index")
        ws, err = await c.warehouse_search("rust")
        print(f"err={err}")
        if ws is not None:
            print(f"hits={len(ws) if hasattr(ws,'__len__') else 'n/a'}")
            try:
                for hit in (ws[:3] if hasattr(ws, '__getitem__') else []):
                    print(f"  • {truncate(getattr(hit, 'title', str(hit)), 80)}")
            except Exception as e:
                print(f"  (preview err: {e})")

        # ─── 8. The N1 bug — prove fact-DB still leaks across queries ──────
        hdr(8, "AUDIT N1 PROOF — fact-DB false positive (raw POST)")
        t0 = time.time()
        r = await c.client.post(
            f"{BASE}/dss/api/aggregate",
            json={"query": "the dog is on the floor", "max_results": 2, "reconcile": False},
            timeout=30,
        )
        err = None if r.status_code == 200 else f"HTTP {r.status_code}"
        bad = r.json() if r.status_code == 200 else None
        print(f"err={err} elapsed={time.time()-t0:.2f}s")
        if bad:
            d = bad
            print(f"fact_db_hit={d.get('fact_db_hit')}   (expect False for an unrelated query)")
            print(f"total_sources={d.get('total_sources')}  sources={d.get('sources')}")
            cons = d.get("consensus") or []
            print(f"consensus claims returned for 'the dog is on the floor':")
            for fact in cons[:3]:
                print(f"  • {truncate(fact.get('claim',''), 120)}")

    print(f"\n{'─'*72}\nworkflow complete @ {time.strftime('%H:%M:%S')}\n{'─'*72}")


if __name__ == "__main__":
    asyncio.run(main())
