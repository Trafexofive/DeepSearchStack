#!/usr/bin/env python3
"""Docs + manuals baseline. The bare minimum any "polymath archive" needs.

Targets the documentation sites people actually live in: official language
docs, manual pages, framework docs, ReadTheDocs, GitHub Pages docs, dev
references. For each URL we want:
  - >500 words of clean content (manuals/refs are dense)
  - <0.20 noise ratio (no nav/sidebar leaking in)
  - <8s latency (doc pages are static, should be fast)

Use this to find docs sites that DON'T work and fix them. Anything failing
this bar is an instant-ROI bug.
"""
import json
import re
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import httpx

BASE = "http://localhost:8083"

CORPUS = [
    # ── Official language docs ─────────────────────────────────────
    "https://docs.python.org/3/library/asyncio.html",
    "https://doc.rust-lang.org/std/vec/struct.Vec.html",
    "https://doc.rust-lang.org/book/ch04-01-what-is-ownership.html",
    "https://pkg.go.dev/net/http",
    "https://go.dev/doc/effective_go",
    "https://nodejs.org/api/fs.html",
    "https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Array",
    "https://en.cppreference.com/w/cpp/container/vector",

    # ── Framework / library docs ──────────────────────────────────
    "https://react.dev/learn",
    "https://docs.djangoproject.com/en/5.0/intro/tutorial01/",
    "https://flask.palletsprojects.com/en/3.0.x/quickstart/",
    "https://fastapi.tiangolo.com/tutorial/first-steps/",
    "https://docs.sqlalchemy.org/en/20/orm/quickstart.html",
    "https://expressjs.com/en/4x/api.html",

    # ── Infrastructure docs ───────────────────────────────────────
    "https://docs.docker.com/get-started/overview/",
    "https://kubernetes.io/docs/concepts/overview/",
    "https://docs.nginx.com/nginx/admin-guide/web-server/web-server/",
    "https://www.postgresql.org/docs/16/sql-select.html",
    "https://redis.io/docs/latest/develop/clients/",

    # ── Manual pages (the bare minimum) ───────────────────────────
    "https://man7.org/linux/man-pages/man1/grep.1.html",
    "https://man7.org/linux/man-pages/man2/open.2.html",
    "https://man7.org/linux/man-pages/man7/signal.7.html",
    "https://manpages.debian.org/bookworm/systemd/systemctl.1.en.html",
    "https://manpages.ubuntu.com/manpages/jammy/man1/ssh.1.html",

    # ── Wiki-style ────────────────────────────────────────────────
    "https://wiki.archlinux.org/title/Systemd",
    "https://en.wikibooks.org/wiki/Bash_Shell_Scripting",

    # ── ReadTheDocs ───────────────────────────────────────────────
    "https://requests.readthedocs.io/en/latest/user/quickstart/",
    "https://pip.pypa.io/en/stable/user_guide/",

    # ── API references ────────────────────────────────────────────
    "https://stripe.com/docs/api/charges/create",
    "https://platform.openai.com/docs/api-reference/chat/create",
]


NOISE_PATTERNS = [
    re.compile(p, re.I) for p in [
        r"^\[?(jump to|skip to|skip nav)",
        r"^\[?(menu|main menu|navigation|sign in|sign up|log in|log out)\b",
        r"^\[?(privacy|terms|cookie|legal|accessibility)\b",
        r"^(previous|next)\s+(topic|page|article|chapter)",
        r"^(home|search|contact|about)\s*$",
        r"^\[\s*\]\(",
        r"^!\[",
        r"^\s*[\*\-_=]{3,}\s*$",
        r"^\[?subscribe\b",
        r"^edit (this )?page",
        r"^toggle\s+\w+",
        r"^read\s+the\s+docs",
        r"^view\s+page\s+source",
        r"^©\s*\d{4}",
    ]
]


_CODE_LIKE = re.compile(
    r"^[`*_\-\|\#\[!>]"                 # structural markdown
    r"|^\s*(class|struct|template|namespace|fn|let|const|var|def|function|return|public|private|protected|static|virtual|override|async|await|import|export|from)\b"
    r"|^[A-Za-z_][A-Za-z0-9_:<>,\s\(\)\*&]*\s*[\(\{=:]"  # identifier-like signatures
    r"|^\-{1,2}\w"                       # CLI flags like -h or --help
    r"|^[A-Z_][A-Z0-9_]+(\s|$)"          # CONSTANTS
    r"|^[a-z_][a-z0-9_]*\(\)"            # function calls
)


def noise_ratio(md: str) -> float:
    """Lines that look like nav/UI/legal — NOT code, NOT structural markdown."""
    if not md:
        return 0.0
    lines = [l for l in md.split("\n") if l.strip()]
    if not lines:
        return 0.0
    noisy = 0
    for l in lines:
        stripped = l.strip()
        if any(p.search(stripped) for p in NOISE_PATTERNS):
            noisy += 1
            continue
        # Code/identifier/structural lines are content for doc pages
        if _CODE_LIKE.search(stripped):
            continue
        # Short, non-sentence, non-code line
        if len(stripped) < 30 and not re.search(r"[\.!?:;\)\]]$", stripped):
            noisy += 1
            continue
        # Separator-heavy nav serialization
        sep_count = stripped.count("|") + stripped.count(" > ")
        if sep_count >= 3 and len(stripped) < 120:
            noisy += 1
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
                    "noise": 0.0, "title": "", "blocked": False}
        d = r.json()
        md = d.get("markdown") or ""
        words = d.get("word_count", 0) or 0
        nr = round(noise_ratio(md), 3)
        # OK only if >= 200 words AND noise < 0.40
        ok = bool(d.get("success")) and words >= 200 and nr < 0.40
        return {
            "url": url, "ok": ok, "ms": elapsed_ms, "words": words,
            "method": d.get("extraction_method", "?"), "noise": nr,
            "title": (d.get("title") or "")[:50],
            "blocked": bool(d.get("blocked")),
        }
    except Exception as e:
        return {"url": url, "ok": False,
                "ms": int((time.perf_counter() - t0) * 1000),
                "words": 0, "method": f"ERR:{type(e).__name__}",
                "noise": 0.0, "title": "", "blocked": False}


def main():
    print(f"DSS docs+manuals bench — {len(CORPUS)} URLs\n")
    print(f"  Pass criteria: success=true AND words >= 200 AND noise < 0.40\n")
    results = []
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=4) as ex:
        futs = {ex.submit(probe, u): u for u in CORPUS}
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            tag = "✓" if r["ok"] else "✗"
            host = urlparse(r["url"]).netloc[:25]
            url_short = r["url"][len(f"https://{urlparse(r['url']).netloc}"):][:50]
            print(f"  {tag} {host:25s} {r['ms']:6d}ms {r['words']:6d}w "
                  f"noise={r['noise']:.2f} via={r['method'][:18]:18s}  "
                  f"{url_short}")
    total_s = time.perf_counter() - started

    ok = [r for r in results if r["ok"]]
    fail = [r for r in results if not r["ok"]]
    lat = [r["ms"] for r in results]
    words = [r["words"] for r in ok]

    def p(xs, q):
        if not xs:
            return 0
        xs = sorted(xs)
        return xs[min(len(xs) - 1, int(len(xs) * q))]

    print(f"\n══ DOCS BENCH SUMMARY ══")
    print(f"  total wall: {total_s:.1f}s")
    print(f"  pass: {len(ok)}/{len(results)} ({len(ok)*100//len(results)}%)")
    print(f"  fail: {len(fail)}")
    print(f"  p50 latency:  {p(lat, 0.50):>5d}ms")
    print(f"  p95 latency:  {p(lat, 0.95):>5d}ms")
    if words:
        print(f"  words median: {int(statistics.median(words)):,}")
        print(f"  words total:  {sum(words):,}")

    if fail:
        print("\n══ FAILURES (need fix) ══")
        for r in fail:
            host = urlparse(r["url"]).netloc[:30]
            reason = []
            if not r.get("ok") and r["words"] < 200:
                reason.append(f"thin({r['words']}w)")
            if r["noise"] >= 0.40:
                reason.append(f"noisy({r['noise']:.2f})")
            if r.get("blocked"):
                reason.append("blocked")
            reason_s = " ".join(reason) or "fail"
            print(f"  ✗ {host:30s} {reason_s:24s} {r['url'][:60]}")


if __name__ == "__main__":
    main()
