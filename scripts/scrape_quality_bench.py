#!/usr/bin/env python3
"""Honest quality + speed benchmark.

Runs a fixed corpus of URLs through /dss/crawl/crawl with bypass_cache=true,
measures per-URL: latency, success, word count, extraction method, and a
"noise ratio" (chrome lines / total lines) to surface what cleanup actually
delivered. Prints per-URL detail + aggregate p50/p95 + per-domain breakdown.

Why this script:
  Anecdotal probes ("Wikipedia 4329w, looks clean") aren't a benchmark.
  This script gives a single number you can watch move as the crawler
  changes — and an honest "noise ratio" so we know when 'more words' is
  actually 'more chrome'.
"""
import json
import re
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import httpx

BASE = "http://localhost:8083"

# A representative corpus. Each is a real article URL that should yield
# meaningful body content. Avoids 404 placeholders.
CORPUS = [
    # Wikipedia — long-form references
    "https://en.wikipedia.org/wiki/Distributed_computing",
    "https://en.wikipedia.org/wiki/Rust_(programming_language)",
    "https://en.wikipedia.org/wiki/Byzantine_fault",
    # Docs
    "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Array",
    "https://docs.python.org/3/library/asyncio.html",
    # Programming blogs (often clean)
    "https://simonwillison.net/2026/Jun/13/publishing-wasm-wheels/",
    "https://simonwillison.net/2026/Jun/11/fable-is-relentlessly-proactive/",
    "https://simonwillison.net/2026/Jun/9/claude-fable-5/",
    "https://martinfowler.com/articles/refactoring-2nd-ed.html",
    "https://danluu.com/postgres-perf/",
    # Engineering blogs
    "https://stripe.com/blog",
    "https://blog.cloudflare.com/",
    # Github
    "https://github.com/torvalds/linux",
    "https://github.com/rust-lang/rust",
    # PDFs
    "https://arxiv.org/pdf/1706.03762.pdf",
    "https://arxiv.org/pdf/2310.06825.pdf",
    # arXiv abstracts (domain shortcut)
    "https://arxiv.org/abs/1706.03762",
    "https://arxiv.org/abs/2310.06825",
    # HN
    "https://news.ycombinator.com/item?id=1",
    "https://news.ycombinator.com/item?id=39945803",
    # Reddit
    "https://www.reddit.com/r/programming/comments/1g0ev3v/",
    # YouTube
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    # News
    "https://www.bbc.com/news",
    "https://techcrunch.com",
    "https://arstechnica.com",
]

# Lines that look like nav/chrome. Used to compute the "noise ratio."
NOISE_PATTERNS = [
    re.compile(p, re.I) for p in [
        r"^\[?(jump to|skip to|skip nav)",
        r"^\[?(menu|main menu|navigation|sign in|sign up|log in|log out)\b",
        r"^\[?(privacy|terms|cookie|legal|accessibility)\b",
        r"^(previous|next)\s+(topic|page|article|chapter)",
        r"^(home|search|contact|about)\s*$",
        r"^\[\s*\]\(",          # empty-link shells
        r"^!\[",                 # image stubs
        r"^\s*[\*\-_=]{3,}\s*$", # separator lines
        r"^\[?subscribe\b",
        r"^\[?tap to (unmute|mute|play)",
    ]
]


def noise_ratio(md: str) -> float:
    """0.0 = pristine; 1.0 = all chrome.

    A line counts as noise if it matches a known UI pattern OR it's short
    (< 30 chars) with no sentence-like grammar OR it's separator-heavy
    (`|`, `>` between tokens — common nav serialization).
    """
    if not md:
        return 0.0
    lines = [l for l in md.split("\n") if l.strip()]
    if not lines:
        return 0.0
    noisy = 0
    for l in lines:
        stripped = l.strip()
        # 1. Known pattern
        if any(p.search(stripped) for p in NOISE_PATTERNS):
            noisy += 1
            continue
        # 2. Short, non-sentence (no terminal punctuation, < 30 chars)
        if len(stripped) < 30 and not re.search(r"[\.!?:;]\s*$", stripped):
            noisy += 1
            continue
        # 3. Separator-heavy: many `|` or `>` between word tokens
        sep_count = stripped.count("|") + stripped.count(" > ")
        if sep_count >= 2 and len(stripped) < 120:
            noisy += 1
            continue
    return noisy / len(lines)


def probe(url: str) -> dict:
    t0 = time.perf_counter()
    try:
        r = httpx.post(
            f"{BASE}/dss/crawl/crawl",
            json={"url": url, "bypass_cache": True, "timeout": 60},
            timeout=180,
        )
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        if r.status_code != 200:
            return {"url": url, "ok": False, "ms": elapsed_ms,
                    "words": 0, "method": f"HTTP {r.status_code}",
                    "noise": 0.0, "title": ""}
        d = r.json()
        md = d.get("markdown") or ""
        return {
            "url": url,
            "ok": bool(d.get("success")) and (d.get("word_count", 0) or 0) > 50,
            "ms": elapsed_ms,
            "words": d.get("word_count", 0),
            "method": d.get("extraction_method", "?"),
            "noise": round(noise_ratio(md), 3),
            "title": (d.get("title") or "")[:50],
            "blocked": bool(d.get("blocked")),
        }
    except Exception as e:
        return {"url": url, "ok": False, "ms": int((time.perf_counter() - t0) * 1000),
                "words": 0, "method": f"ERR:{type(e).__name__}",
                "noise": 0.0, "title": ""}


def main():
    print(f"DSS scrape-quality bench — {len(CORPUS)} URLs, bypass_cache=true\n")
    results: list[dict] = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(probe, u): u for u in CORPUS}
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            tag = "✓" if r["ok"] else "✗"
            block = " blocked" if r.get("blocked") else ""
            host = urlparse(r["url"]).netloc[:20]
            print(f"  {tag} {host:20s} {r['ms']:6d}ms {r['words']:6d}w "
                  f"noise={r['noise']:.2f} via={r['method'][:22]:22s}  "
                  f"{r['url'][:70]}{block}")
    total_s = time.perf_counter() - started

    # Aggregates
    ok = [r for r in results if r["ok"]]
    fail = [r for r in results if not r["ok"]]
    lat = [r["ms"] for r in results]
    words = [r["words"] for r in ok]
    noise_vals = [r["noise"] for r in ok]

    def p(xs, q):
        if not xs:
            return 0
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(len(xs) * q))]

    print("\n══ SPEED ══")
    print(f"  total wall:      {total_s:.1f}s    (n={len(results)}, parallel=4)")
    print(f"  latency p50:    {p(lat, 0.50):>5d}ms")
    print(f"  latency p95:    {p(lat, 0.95):>5d}ms")
    print(f"  latency max:    {max(lat):>5d}ms")

    print("\n══ QUALITY ══")
    print(f"  success:        {len(ok)}/{len(results)}  ({len(ok)*100//len(results)}%)")
    print(f"  fail:           {len(fail)}")
    if words:
        print(f"  words median:   {int(statistics.median(words))}")
        print(f"  words mean:     {int(statistics.mean(words))}")
        print(f"  words total:    {sum(words):,}")
    if noise_vals:
        print(f"  noise ratio median: {statistics.median(noise_vals):.3f}")
        print(f"  noise ratio mean:   {statistics.mean(noise_vals):.3f}")
        print(f"  noise ratio max:    {max(noise_vals):.3f}")

    # Per-method breakdown
    print("\n══ METHOD MIX ══")
    method_count: dict = {}
    for r in results:
        method_count[r["method"]] = method_count.get(r["method"], 0) + 1
    for m, n in sorted(method_count.items(), key=lambda x: -x[1]):
        print(f"  {n:3d}  {m}")

    # Worst-noise offenders — where cleanup needs attention
    print("\n══ WORST-NOISE WINNERS (cleanup gap) ══")
    noisiest = sorted([r for r in ok if r["noise"] > 0.1],
                      key=lambda x: -x["noise"])[:5]
    for r in noisiest:
        host = urlparse(r["url"]).netloc[:25]
        print(f"  noise={r['noise']:.2f}  {host:25s}  {r['url'][:65]}")
    if not noisiest:
        print("  (none > 0.10 — clean)")

    print()


if __name__ == "__main__":
    main()
