#!/usr/bin/env python3
"""Overnight awesome-list ingestion job.

Extracts links from popular awesome-* repos and crawls every linked page.
This seeds the warehouse with high-quality, human-curated content.

Run: nohup python3 scripts/dss-overnight.py > /tmp/dss-overnight.log 2>&1 &

Estimated: 2-4 hours for ~1000 pages (depends on --limit and --crawl depth).
"""
import asyncio
import re
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sdk import DSSClient


# ── README parser (inlined from dss-awesome.py) ─────────────────────

def fetch_readme(repo_url: str) -> str:
    parsed = urlparse(repo_url)
    parts = parsed.path.strip('/').split('/')
    if len(parts) < 2:
        return ""
    user, repo = parts[0], parts[1]
    for b in ["master", "main"]:
        raw_url = f"https://raw.githubusercontent.com/{user}/{repo}/{b}/README.md"
        try:
            with urllib.request.urlopen(raw_url, timeout=15) as resp:
                return resp.read().decode('utf-8', errors='replace')
        except Exception:
            continue
    return ""


def extract_links(markdown: str, limit: int = 200) -> list[tuple[str, str]]:
    pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
    links, seen = [], set()
    for match in pattern.finditer(markdown):
        title, url = match.group(1).strip(), match.group(2).strip()
        if url.startswith('#') or url.startswith('![') or not url.startswith('http'):
            continue
        if url not in seen:
            seen.add(url)
            links.append((title, url))
        if len(links) >= limit:
            break
    return links


# ── Awesome-list repos to ingest ───────────────────────────────────

AWESOME_REPOS = [
    "https://github.com/sindresorhus/awesome",           # general
    "https://github.com/rust-unofficial/awesome-rust",    # Rust
    "https://github.com/vinta/awesome-python",            # Python
    "https://github.com/avelino/awesome-go",              # Go
    "https://github.com/akullpp/awesome-java",            # Java
    "https://github.com/sorrycc/awesome-javascript",      # JavaScript
    "https://github.com/matiassingers/awesome-readme",    # READMEs
    "https://github.com/papers-we-love/papers-we-love",   # CS papers
    "https://github.com/Hack-with-Github/Awesome-Hacking",# Security
    "https://github.com/awesome-selfhosted/awesome-selfhosted",  # Self-hosted
    "https://github.com/kdeldycke/awesome-falsehood",     # Falsehoods
    "https://github.com/donnemartin/system-design-primer",# System design
    "https://github.com/jwasham/coding-interview-university", # Interviews
    "https://github.com/EbookFoundation/free-programming-books", # Free books
    "https://github.com/ossu/computer-science",           # CS curriculum
    "https://github.com/sdmg15/Best-websites-a-programmer-should-visit",
    "https://github.com/kamranahmedse/developer-roadmap", # Roadmaps
    "https://github.com/trimstray/the-book-of-secret-knowledge",
    "https://github.com/dypsilon/frontend-dev-bookmarks", # Frontend
    "https://github.com/enaqx/awesome-pentest",           # Pentest
]


async def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 100
    crawl = "--crawl" in sys.argv

    print(f"Overnight awesome-list ingestion")
    print(f"  Repos: {len(AWESOME_REPOS)}")
    print(f"  Links per repo: {limit}")
    print(f"  Crawl pages: {crawl}")
    print(f"  Started: {__import__('datetime').datetime.now()}")
    print()

    async with DSSClient(timeout=120.0) as dss:
        total_links = 0
        total_crawled = 0

        for i, repo_url in enumerate(AWESOME_REPOS, 1):
            repo_name = repo_url.rstrip('/').split('/')[-1]
            print(f"[{i}/{len(AWESOME_REPOS)}] {repo_name}")

            try:
                readme = fetch_readme(repo_url)
                links = extract_links(readme, limit)
                print(f"  {len(links)} links extracted")
                total_links += len(links)

                if not links:
                    continue

                # Seed warehouse with link metadata
                seeded = 0
                for title, url in links:
                    try:
                        resp = await dss.client.post(
                            f"{dss.warehouse}/ingest",
                            json={
                                "url": url,
                                "markdown": title,
                                "title": title,
                                "source_domain": __import__('urllib.parse').urlparse(url).netloc,
                                "word_count": len(title.split()),
                                "tags": ["awesome-list", repo_name],
                            },
                            timeout=5.0,
                        )
                        if resp.status_code == 200:
                            seeded += 1
                    except Exception:
                        pass
                print(f"  {seeded} seeded to warehouse")

                # Crawl pages for full content
                if crawl:
                    urls = [url for _, url in links]
                    batch_size = 10
                    for j in range(0, len(urls), batch_size):
                        batch = urls[j:j + batch_size]
                        try:
                            resp = await dss.client.post(
                                f"{dss.web_api}/api/ingest/urls",
                                json={"urls": batch, "timeout": 20},
                                timeout=60.0,
                            )
                            if resp.status_code == 200:
                                data = resp.json()
                                total_crawled += data.get("success_count", 0)
                        except Exception as e:
                            print(f"    ⚠ batch {j}: {e}")
                        await asyncio.sleep(1)

                    print(f"  crawled: {min(len(urls), len(urls))}/{len(urls)} pages (total: {total_crawled})")

            except Exception as e:
                print(f"  ✗ {repo_name}: {e}")
                continue

            # Stats checkpoint
            try:
                stats = await dss.warehouse_stats()
                print(f"  warehouse: {stats['total_entries']} entries, {stats['db_size_mb']}MB")
            except Exception:
                pass

            print()

        print(f"\n{'='*60}")
        print(f"Done: {total_links} links from {len(AWESOME_REPOS)} awesome-lists")
        if crawl:
            print(f"      {total_crawled} pages crawled into warehouse")
        try:
            stats = await dss.warehouse_stats()
            print(f"      Warehouse: {stats['total_entries']} entries, {stats['db_size_mb']}MB")
        except Exception:
            pass
        print(f"      Finished: {__import__('datetime').datetime.now()}")


if __name__ == "__main__":
    asyncio.run(main())
