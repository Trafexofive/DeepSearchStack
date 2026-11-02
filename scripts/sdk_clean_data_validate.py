#!/usr/bin/env python3
"""
Validate REAL data cleanliness + REAL OCR after trafilatura + RapidOCR landed.

This is the harsh test:
  - Crawl outputs must START with article content, not nav/sidebar/menu.
  - OCR text must be faithful to the source page, no hallucination.
  - Warehouse must accept ONLY bodies (no SERP-snippet rows).
"""
import sys, json, time, asyncio, subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "sdk" / "python"))
from deepsearch import AsyncDeepSearchClient

BASE = "http://localhost:8083"

JUNK_LEADERS = [
    "skip to content", "skip to main", "jump to content",
    "main menu", "navigation menu", "toggle navigation",
    "sign in", "search code, repositories", "move to sidebar",
    "[jump to content", "[skip to",
]


def hdr(t, name):
    print(f"\n{'═'*78}\n[{t}] {name}\n{'═'*78}")


def warehouse_stats():
    out = subprocess.check_output([
        "docker", "exec", "dss-knowledge-warehouse", "python3", "-c", """
import sqlite3, json
c=sqlite3.connect('/app/data/warehouse.db'); cur=c.cursor()
total=cur.execute('select count(*) from content').fetchone()[0]
bodies=cur.execute('select count(*) from content where word_count>=200').fetchone()[0]
shorts=cur.execute('select count(*) from content where word_count<200').fetchone()[0]
snippets=cur.execute('select count(*) from content where word_count<50').fetchone()[0]
filled=cur.execute('select count(*) from content where length(coalesce(content,\\\"\\\"))>0').fetchone()[0]
html=cur.execute('select count(*) from content where markdown like \\\"%<%>%\\\"').fetchone()[0]
avg_md=cur.execute('select coalesce(avg(length(markdown)),0) from content').fetchone()[0]
print(json.dumps({
  'total': total, 'bodies_ge_200w': bodies, 'short_lt_200w': shorts, 'snippets_lt_50w': snippets,
  'rows_with_content_col': filled, 'rows_with_html_tags': html,
  'avg_markdown_chars': int(avg_md),
}))
"""])
    return json.loads(out.decode().strip())


def warehouse_recent(limit=4):
    out = subprocess.check_output([
        "docker", "exec", "dss-knowledge-warehouse", "python3", "-c", f"""
import sqlite3, json
c=sqlite3.connect('/app/data/warehouse.db'); cur=c.cursor()
rows=[]
for r in cur.execute('select id, title, source_domain, word_count, substr(markdown,1,180), tags from content order by id desc limit {limit}'):
    rows.append({{'id':r[0], 'title':r[1], 'domain':r[2], 'wc':r[3], 'lead':r[4], 'tags':r[5]}})
print(json.dumps(rows))
"""])
    return json.loads(out.decode().strip())


def starts_with_junk(text):
    head = (text or "").strip()[:300].lower()
    for j in JUNK_LEADERS:
        if j in head[:120]:
            return j
    return None


async def crawl(c, url, **kwargs):
    r = await c.client.post(
        f"{BASE}/dss/crawl/crawl",
        json={"url": url, **kwargs},
        timeout=180,
    )
    return r.json() if r.status_code == 200 else {"_http": r.status_code, "_body": r.text[:300]}


async def main():
    print(f"DSS clean-data validation — {time.strftime('%Y-%m-%d %H:%M:%S')}")

    async with AsyncDeepSearchClient(base_url=BASE, timeout=240) as c:

        # ── BASELINE ────────────────────────────────────────────────
        hdr("0", "BASELINE — warehouse snapshot before workflow")
        before = warehouse_stats()
        print(json.dumps(before, indent=2))

        # ── 1. Clean article extraction: leader must NOT be nav junk ──
        targets = [
            "https://en.wikipedia.org/wiki/Erlang_(programming_language)",
            "https://github.com/akkadotnet/akka.net",
            "https://news.ycombinator.com/item?id=12345678",
        ]
        hdr("1", "CLEAN EXTRACTION — first 250 chars must be article body, not nav")
        for url in targets:
            d = await crawl(c, url, bypass_cache=True, timeout=60)
            md = (d.get("markdown") or "").strip()
            junk = starts_with_junk(md)
            verdict = "FAIL" if junk else "PASS"
            print(f"\n  [{verdict}] {url}")
            print(f"    extraction_method = {d.get('extraction_method')}  word_count = {d.get('word_count')}")
            if junk:
                print(f"    leads with junk: {junk!r}")
            print(f"    first 220 chars: {md[:220]!r}")

        # ── 2. REAL OCR (RapidOCR) — text must match actual page ────
        hdr("2", "REAL OCR — RapidOCR text must reflect actual page content")
        d = await crawl(c, "https://news.ycombinator.com/", bypass_cache=True, render_mode="ocr", timeout=60)
        md = (d.get("markdown") or "")
        print(f"  extraction_method = {d.get('extraction_method')}")
        print(f"  escalations       = {d.get('escalations')}")
        print(f"  word_count        = {d.get('word_count')}")
        print(f"  ocr text length   = {len(md)} chars")
        # Hacker News should contain "Hacker News" or known UI words
        signals = ["hacker news", "comments", "points", "ago", "show", "ask", "submit"]
        hits = [s for s in signals if s in md.lower()]
        print(f"  expected-signal hits: {hits} (need ≥2 to count as faithful)")
        print(f"\n  preview (first 800 chars):")
        for ln in md[:800].split("\n"):
            print(f"    {ln}")

        # ── 3. Aggregate w/ scraping → warehouse must accept BODIES only ──
        hdr("3", "AGGREGATE+SCRAPE — warehouse must only accept bodies (no snippets)")
        t0 = time.time()
        r = await c.client.post(
            f"{BASE}/dss/api/aggregate",
            json={
                "query": "Apache Pulsar bookkeeper internals 2025",
                "max_results": 8,
                "enable_scraping": True,
                "max_scrape_urls": 6,
                "include_warehouse": True,
                "reconcile": False,
                "enable_synthesis": False,
            },
            timeout=180,
        )
        print(f"  http={r.status_code}  elapsed={time.time()-t0:.2f}s")
        if r.status_code == 200:
            agg = r.json()
            print(f"  total_sources={agg.get('total_sources')}  scraped_urls={agg.get('scraped_urls')}")
        await asyncio.sleep(3)

        # ── 4. Delta + recent rows ───────────────────────────────────
        hdr("4", "DELTA + recent rows — confirm clean ingestion")
        after = warehouse_stats()
        delta = {k: after.get(k, 0) - before.get(k, 0) for k in after}
        print(f"  {'metric':28s} {'before':>9s} {'after':>9s} {'delta':>9s}")
        for k in after:
            print(f"  {k:28s} {before.get(k,0):>9d} {after.get(k,0):>9d} {delta[k]:>+9d}")

        print(f"\n  rule: snippets_lt_50w delta must be 0 (we no longer accept short rows)")
        print(f"  rule: bodies_ge_200w delta must be > 0 (bodies must land)")
        print(f"  rule: rows_with_content_col delta must equal bodies delta")

        hdr("5", "RECENT WAREHOUSE ROWS — leading 180 chars (must be content, not nav)")
        for row in warehouse_recent(4):
            print(f"\n  id={row['id']} wc={row['wc']} domain={row['domain']} tags={row['tags']}")
            print(f"  title: {row['title']}")
            lead = (row['lead'] or "").strip()
            junk = starts_with_junk(lead)
            print(f"  {'!! NAV JUNK !!' if junk else '✓ clean lead'}: {lead[:160]!r}")

    print(f"\n{'═'*78}\nworkflow complete @ {time.strftime('%H:%M:%S')}\n{'═'*78}")


if __name__ == "__main__":
    asyncio.run(main())
