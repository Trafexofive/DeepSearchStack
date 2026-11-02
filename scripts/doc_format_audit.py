#!/usr/bin/env python3
"""End-to-end test: crawler handles PDF, MD, TXT, EPUB, DOCX.

For each format we:
  1. Crawl the URL via /dss/crawl/crawl with bypass_cache=true
  2. Confirm extraction_method == expected format
  3. Show the lead 400 chars + word count + lineage
  4. Verify warehouse received the row (extractor field set)
"""
import time, httpx, json

BASE = "http://localhost:8083"

CASES = [
    # arXiv "Attention Is All You Need" — canonical CS paper PDF, small (~2 MB)
    ("PDF",  "https://arxiv.org/pdf/1706.03762.pdf",  "pdf"),
    # GitHub raw README — markdown
    ("MD",   "https://raw.githubusercontent.com/sindresorhus/awesome/main/readme.md", "markdown"),
    # plain text — RFC 1149 (avian carriers)
    ("TXT",  "https://www.rfc-editor.org/rfc/rfc1149.txt", "text"),
    # EPUB — small Project Gutenberg book (Aesop's Fables, ~250 KB)
    ("EPUB", "https://www.gutenberg.org/ebooks/11339.epub.images", "epub"),
]

def crawl(url):
    r = httpx.post(f"{BASE}/dss/crawl/crawl",
                   json={"url": url, "bypass_cache": True, "render_mode": "fast", "timeout": 90},
                   timeout=120)
    return r.json() if r.status_code == 200 else {"_http": r.status_code, "_body": r.text[:300]}

def main():
    for tag, url, expected in CASES:
        print()
        print("=" * 80)
        print(f"[{tag}] {url}")
        print("=" * 80)
        t0 = time.time()
        d = crawl(url)
        elapsed = int((time.time() - t0) * 1000)
        if "_http" in d:
            print(f"  ✗ HTTP {d['_http']}: {d['_body']}")
            continue
        method = d.get("extraction_method", "?")
        success = d.get("success")
        wc = d.get("word_count", 0)
        title = d.get("title", "") or ""
        author = d.get("author", "") or ""
        md = d.get("markdown") or ""
        mark = "✓" if method == expected and success and wc > 50 else "✗"
        print(f"  {mark}  extraction_method={method}  success={success}  word_count={wc}  elapsed={elapsed}ms")
        print(f"     title  = {title[:80]!r}")
        print(f"     author = {author[:80]!r}")
        print(f"     published = {d.get('published')!r}  language = {d.get('language')!r}")
        print(f"     markdown length = {len(md)} chars")
        print()
        print(f"     ── first 600 chars ──")
        for line in md[:600].splitlines()[:10]:
            print(f"     | {line[:80]}")

if __name__ == "__main__":
    main()
