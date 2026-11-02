#!/usr/bin/env python3
"""Probe what we can/can't scrape today.

Categories tested:
  static       — static HTML, control case
  spa          — single-page app, content via JS
  cloudflare   — bot-managed (will see "Just a moment" or fail)
  paywall      — major newspaper paywalls
  login_wall   — auth required
  api_only     — modern app that doesn't serve HTML
  pdf          — direct PDF URLs
  rate_limit   — APIs with strict limits
  geo_block    — geo-fenced content
  binary       — non-text content (video/image)
"""
import time, httpx, json
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "http://localhost:8083"

# Each probe: (category, label, url, render_mode)
CASES = [
    ("static",     "Wikipedia article",            "https://en.wikipedia.org/wiki/Distributed_computing",                "auto"),
    ("static",     "GitHub README",                "https://github.com/torvalds/linux",                                   "auto"),
    ("static",     "arXiv abstract page",          "https://arxiv.org/abs/2310.01234",                                    "auto"),
    ("static",     "Stripe API docs",              "https://stripe.com/docs/api",                                          "auto"),
    ("static",     "MDN — Array",                  "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Array", "auto"),

    ("pdf",        "arXiv direct PDF",             "https://arxiv.org/pdf/1706.03762.pdf",                                "auto"),
    ("pdf",        "RFC PDF",                      "https://www.rfc-editor.org/rfc/rfc1149.txt",                          "auto"),

    ("spa",        "Reddit comments (SPA)",        "https://www.reddit.com/r/programming/comments/1g0ev3v/",              "auto"),
    ("spa",        "Twitter/X profile",            "https://x.com/karpathy",                                              "auto"),
    ("spa",        "Discord public invite",        "https://discord.com/invite/python",                                   "auto"),

    ("cloudflare", "Medium article (sometimes CF)","https://medium.com/@karpathy/cracking-the-coding-interview-something", "auto"),
    ("cloudflare", "G2 reviews",                   "https://www.g2.com/products/notion/reviews",                          "auto"),

    ("paywall",    "NYT article",                  "https://www.nytimes.com/2024/10/01/technology/openai.html",           "auto"),
    ("paywall",    "WSJ article",                  "https://www.wsj.com/articles/tech-earnings-fall",                     "auto"),
    ("paywall",    "FT article",                   "https://www.ft.com/content/00000000-0000-0000-0000-000000000000",     "auto"),

    ("login_wall", "LinkedIn profile",             "https://www.linkedin.com/in/satyanadella",                            "auto"),
    ("login_wall", "Facebook page",                "https://www.facebook.com/openai",                                     "auto"),
    ("login_wall", "Instagram",                    "https://www.instagram.com/openai/",                                   "auto"),

    ("rate_limit", "GitHub API (no auth)",         "https://api.github.com/repos/torvalds/linux",                         "auto"),
    ("rate_limit", "HN API",                       "https://hacker-news.firebaseio.com/v0/item/1.json",                   "auto"),

    ("binary",     "YouTube video page",           "https://www.youtube.com/watch?v=dQw4w9WgXcQ",                         "auto"),
    ("binary",     "MP4 direct",                   "https://download.blender.org/peach/bigbuckbunny_movies/big_buck_bunny_720p_1mb.mp4", "auto"),

    ("force_browser", "Reddit via FORCE browser",  "https://www.reddit.com/r/programming/comments/1g0ev3v/",              "browser"),
]

def probe(category, label, url, mode):
    try:
        t0 = time.time()
        r = httpx.post(f"{BASE}/dss/crawl/crawl",
                       json={"url": url, "bypass_cache": True, "render_mode": mode, "timeout": 60},
                       timeout=120)
        elapsed = int((time.time() - t0) * 1000)
        if r.status_code != 200:
            return (category, label, url, mode, False, f"HTTP {r.status_code}", 0, elapsed, "", None, None)
        d = r.json()
        success = d.get("success") and d.get("word_count", 0) > 50
        method = d.get("extraction_method", "?")
        escalations = d.get("escalations", [])
        blocked = d.get("blocked")
        wc = d.get("word_count", 0)
        title = (d.get("title") or "")[:60]
        md_lead = (d.get("markdown") or "")[:120].replace("\n", " ")
        return (category, label, url, mode, success, method, wc, elapsed, title, blocked, md_lead)
    except Exception as e:
        return (category, label, url, mode, False, str(e)[:60], 0, 0, "", None, None)

def main():
    print(f"DSS scrape-difficulty audit — {len(CASES)} URLs across categories\n")
    results = []
    # Parallel — most fail fast, browser ones take time
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = {ex.submit(probe, *c): c for c in CASES}
        for fut in as_completed(futures):
            results.append(fut.result())

    # Print by category in original order
    by_label = {(r[0], r[1]): r for r in results}
    last_cat = None
    cat_stats = {}
    for category, label, url, mode, *_ in CASES:
        r = by_label[(category, label)]
        cat, lab, u, m, success, method, wc, elapsed, title, blocked, lead = r
        if cat != last_cat:
            print(f"\n── {cat.upper()} ──")
            last_cat = cat
        cat_stats.setdefault(cat, [0, 0])
        cat_stats[cat][0] += 1
        if success:
            cat_stats[cat][1] += 1
        mark = "✓" if success else "✗"
        bl = f" blocked={blocked}" if blocked else ""
        esc = f" via:{method}" if success else ""
        print(f"  {mark} {label[:35]:35s} {wc:6d}w {elapsed:5d}ms{esc}{bl}  {u[:55]}")
        if success and lead:
            print(f"      lead: {lead[:90]}...")
        elif not success:
            print(f"      → {method}")

    print(f"\n══ SUMMARY ══")
    for cat, (total, ok) in sorted(cat_stats.items()):
        print(f"  {cat:14s} {ok}/{total}  {'█' * ok}{'░' * (total - ok)}")

if __name__ == "__main__":
    main()
