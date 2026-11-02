#!/usr/bin/env python3
"""
Validate the new crawler escalation ladder + warehouse data-cleanliness fix.

Steps:
  A.  Static page via fast path → extraction_method=html, no escalations.
  B.  JS-heavy page on auto → expect possible browser escalation.
  C.  Force render_mode=browser → expect extraction_method=browser.
  D.  Force render_mode=ocr → expect extraction_method=ocr (vision LLM).
  E.  Aggregate with enable_scraping=true → confirm warehouse now stores
      FULL BODIES (not 1000-char snippets) with `content` populated and no
      HTML tag pollution.
"""
import sys, json, time, asyncio, sqlite3, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk" / "python"))
from deepsearch import AsyncDeepSearchClient
import httpx

BASE = "http://localhost:8083"


def hdr(t, name):
    print(f"\n{'═'*78}\n[{t}] {name}\n{'═'*78}")


def warehouse_stats():
    """Snapshot warehouse data-cleanliness metrics via direct SQLite read."""
    out = subprocess.check_output([
        "docker", "exec", "dss-knowledge-warehouse", "python3", "-c", """
import sqlite3, json
c=sqlite3.connect('/app/data/warehouse.db'); cur=c.cursor()
total=cur.execute('select count(*) from content').fetchone()[0]
bodies=cur.execute('select count(*) from content where word_count>=200').fetchone()[0]
snippets=cur.execute('select count(*) from content where word_count<50').fetchone()[0]
filled_content=cur.execute('select count(*) from content where length(coalesce(content,\\\"\\\"))>0').fetchone()[0]
html_pollution=cur.execute('select count(*) from content where markdown like \\\"%<%>%\\\"').fetchone()[0]
avg_md=cur.execute('select coalesce(avg(length(markdown)),0) from content').fetchone()[0]
max_md=cur.execute('select coalesce(max(length(markdown)),0) from content').fetchone()[0]
print(json.dumps({
  'total': total, 'bodies_ge_200w': bodies, 'snippets_lt_50w': snippets,
  'rows_with_content_col': filled_content, 'rows_with_html_tags': html_pollution,
  'avg_markdown_chars': int(avg_md), 'max_markdown_chars': int(max_md),
}))
"""])
    return json.loads(out.decode().strip())


async def crawl(c, url, **kwargs):
    """Direct crawler call (bypassing SDK's CrawlResult cast so we see all fields)."""
    r = await c.client.post(
        f"{BASE}/dss/crawl/crawl",
        json={"url": url, **kwargs},
        timeout=180,
    )
    return r.json() if r.status_code == 200 else {"_http": r.status_code, "_body": r.text[:300]}


async def main():
    print(f"DSS escalation + cleanliness validation — {time.strftime('%Y-%m-%d %H:%M:%S')}")

    async with AsyncDeepSearchClient(base_url=BASE, timeout=240) as c:

        hdr("PRE", "warehouse snapshot BEFORE workflow")
        before = warehouse_stats()
        print(json.dumps(before, indent=2))

        # ── A. Static page via fast path ──────────────────────────────────
        hdr("A", "static page (fast path) — Hacker News front page")
        t0 = time.time()
        d = await crawl(c, "https://news.ycombinator.com/", bypass_cache=True, render_mode="fast")
        print(f"elapsed={time.time()-t0:.2f}s")
        print(f"  extraction_method = {d.get('extraction_method')}")
        print(f"  word_count        = {d.get('word_count')}")
        print(f"  escalations       = {d.get('escalations')}")
        print(f"  blocked           = {d.get('blocked')}  reason={d.get('block_reason')}")

        # ── B. JS-heavy page on auto ─────────────────────────────────────
        hdr("B", "JS-heavy (auto) — Reddit /r/programming")
        t0 = time.time()
        d = await crawl(c, "https://www.reddit.com/r/programming/", bypass_cache=True, render_mode="auto")
        print(f"elapsed={time.time()-t0:.2f}s")
        print(f"  extraction_method = {d.get('extraction_method')}")
        print(f"  word_count        = {d.get('word_count')}")
        print(f"  escalations       = {d.get('escalations')}")
        print(f"  blocked           = {d.get('blocked')}  reason={d.get('block_reason')}")
        md = d.get("markdown") or ""
        print(f"  markdown_preview  = {md[:200]!r}")

        # ── C. Force browser ────────────────────────────────────────────
        hdr("C", "force render_mode=browser — same Reddit page")
        t0 = time.time()
        d = await crawl(c, "https://www.reddit.com/r/programming/", bypass_cache=True, render_mode="browser")
        print(f"elapsed={time.time()-t0:.2f}s")
        print(f"  extraction_method = {d.get('extraction_method')}")
        print(f"  word_count        = {d.get('word_count')}")
        print(f"  escalations       = {d.get('escalations')}")

        # ── D. Force OCR (the real demo) ────────────────────────────────
        hdr("D", "force render_mode=ocr — screenshot → vision-LLM OCR")
        t0 = time.time()
        d = await crawl(c, "https://en.wikipedia.org/wiki/BEAM_(Erlang_virtual_machine)",
                        bypass_cache=True, render_mode="ocr")
        print(f"elapsed={time.time()-t0:.2f}s")
        print(f"  extraction_method = {d.get('extraction_method')}")
        print(f"  escalations       = {d.get('escalations')}")
        print(f"  word_count        = {d.get('word_count')}")
        md = d.get("markdown") or ""
        print(f"  OCR text preview ({len(md)} chars):")
        print("  " + md[:400].replace("\n", "\n  "))

        # ── E. Aggregate with scraping → warehouse cleanliness check ────
        hdr("E", "aggregate(enable_scraping=true) — proves seed-warehouse now stores BODIES")
        t0 = time.time()
        r = await c.client.post(
            f"{BASE}/dss/api/aggregate",
            json={
                "query": "Akka Cluster Sharding internals 2025",
                "max_results": 6,
                "enable_scraping": True,
                "max_scrape_urls": 5,
                "include_warehouse": True,
                "reconcile": False,
                "enable_synthesis": False,
            },
            timeout=180,
        )
        print(f"elapsed={time.time()-t0:.2f}s http={r.status_code}")
        if r.status_code == 200:
            agg = r.json()
            print(f"  total_sources = {agg.get('total_sources')}  scraped_urls = {agg.get('scraped_urls')}")
        await asyncio.sleep(3)  # let fire-and-forget seed_warehouse settle

        hdr("POST", "warehouse snapshot AFTER workflow")
        after = warehouse_stats()
        print(json.dumps(after, indent=2))

        hdr("DELTA", "data-cleanliness delta")
        keys = ["total", "bodies_ge_200w", "snippets_lt_50w", "rows_with_content_col",
                "rows_with_html_tags", "avg_markdown_chars", "max_markdown_chars"]
        print(f"  {'metric':28s} {'before':>10s} {'after':>10s} {'delta':>10s}")
        for k in keys:
            b, a = before.get(k, 0), after.get(k, 0)
            print(f"  {k:28s} {b:>10d} {a:>10d} {a-b:>+10d}")

        print(f"\n  bodies_ge_200w delta should be POSITIVE → bodies are now landing in warehouse.")
        print(f"  rows_with_content_col delta should be POSITIVE → `content` column now populated.")
        print(f"  rows_with_html_tags delta should be ~0 → HTML stripped from new snippets.")

    print(f"\n{'═'*78}\nworkflow complete @ {time.strftime('%H:%M:%S')}\n{'═'*78}")


if __name__ == "__main__":
    asyncio.run(main())
