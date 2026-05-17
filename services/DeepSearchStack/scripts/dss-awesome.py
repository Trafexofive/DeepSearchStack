#!/usr/bin/env python3
"""dss-awesome — ingest GitHub awesome-list curated links into warehouse.

Parses awesome-* README.md, extracts all markdown links, ingests URLs.
These are high-quality, human-curated resource lists.

Usage:
    python3 scripts/dss-awesome.py https://github.com/sindresorhus/awesome
    python3 scripts/dss-awesome.py https://github.com/rust-unofficial/awesome-rust --crawl
    python3 scripts/dss-awesome.py --file awesome-links.txt

Flags:
    --crawl     also crawl each linked page (slower, richer content)
    --limit N   max links to extract (default: 200)
    --file      read links from a local file instead of GitHub README
"""
import asyncio
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sdk import DSSClient


def fetch_readme(repo_url: str) -> str:
    """Fetch raw README.md from a GitHub repo."""
    # Convert github.com URL to raw.githubusercontent.com
    parsed = urlparse(repo_url)
    if 'github.com' not in parsed.netloc:
        print(f"Error: not a GitHub URL: {repo_url}")
        sys.exit(1)

    path = parsed.path.strip('/')
    # Handle /user/repo format
    parts = path.split('/')
    if len(parts) < 2:
        print(f"Error: expected github.com/user/repo, got: {repo_url}")
        sys.exit(1)

    user, repo = parts[0], parts[1]
    branch = "master"  # try master first, fallback to main

    import urllib.request
    for b in [branch, "main"]:
        raw_url = f"https://raw.githubusercontent.com/{user}/{repo}/{b}/README.md"
        try:
            with urllib.request.urlopen(raw_url, timeout=15) as resp:
                return resp.read().decode('utf-8', errors='replace')
        except Exception:
            continue

    print(f"Error: could not fetch README from {repo_url}")
    sys.exit(1)


def extract_links(markdown: str, limit: int = 200) -> list[tuple[str, str]]:
    """Extract [title](url) markdown links from README."""
    # Match [text](url) pattern
    pattern = re.compile(r'\[([^\]]+)\]\(([^)]+)\)')
    links = []
    seen = set()

    for match in pattern.finditer(markdown):
        title = match.group(1).strip()
        url = match.group(2).strip()

        # Skip relative links, anchors, images
        if url.startswith('#') or url.startswith('!['):
            continue
        if url.startswith('./') or url.startswith('../'):
            continue
        if not url.startswith('http'):
            continue
        # Skip github.com links (self-referential)
        if 'github.com' in url and '/blob/' not in url and '/tree/' not in url:
            if 'awesome' in url.lower():
                pass  # allow awesome-list links to other awesome lists
            else:
                continue

        if url not in seen:
            seen.add(url)
            links.append((title, url))

        if len(links) >= limit:
            break

    return links


async def ingest_links(dss: DSSClient, links: list[tuple[str, str]], crawl: bool = False):
    """Ingest link metadata into warehouse, optionally crawl pages."""
    # First: store all link metadata in warehouse
    for i, (title, url) in enumerate(links):
        try:
            async with dss.client as client:
                resp = await client.post(
                    f"{dss.warehouse}/ingest",
                    json={
                        "url": url,
                        "markdown": title,
                        "title": title,
                        "source_domain": urlparse(url).netloc,
                        "word_count": len(title.split()),
                        "tags": ["awesome-list"],
                    },
                    timeout=5.0,
                )
        except Exception:
            pass

        if (i + 1) % 50 == 0:
            print(f"  seeded {i+1}/{len(links)} links to warehouse")

    print(f"  ✓ {len(links)} links seeded to warehouse")

    # Optionally crawl each page for full content
    if crawl:
        urls = [url for _, url in links]
        batch_size = 10
        total = 0
        for i in range(0, len(urls), batch_size):
            batch = urls[i:i + batch_size]
            try:
                async with dss.client as client:
                    resp = await client.post(
                        f"{dss.web_api}/api/ingest/urls",
                        json={"urls": batch, "timeout": 20},
                        timeout=60.0,
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        total += data.get("success_count", 0)
            except Exception as e:
                print(f"  ⚠ crawl batch failed: {e}")

            print(f"  crawled {min(i + batch_size, len(urls))}/{len(urls)} — {total} ok")
            await asyncio.sleep(1)  # gentle pacing

        print(f"  ✓ {total} pages crawled into warehouse")


async def main():
    crawl = '--crawl' in sys.argv
    limit = 200
    file_input = None
    repo_url = None

    args = [a for a in sys.argv[1:] if a != '--crawl']
    for i, arg in enumerate(args):
        if arg == '--limit' and i + 1 < len(args):
            limit = int(args[i + 1])
        elif arg == '--file' and i + 1 < len(args):
            file_input = args[i + 1]
        elif arg.startswith('http'):
            repo_url = arg

    if not repo_url and not file_input:
        print(__doc__)
        sys.exit(1)

    async with DSSClient() as dss:
        if file_input:
            with open(file_input) as f:
                links = []
                for line in f:
                    line = line.strip()
                    if line and line.startswith('http'):
                        links.append((line, line))
            print(f"Loaded {len(links)} links from {file_input}")
        else:
            print(f"Fetching README: {repo_url}")
            readme = fetch_readme(repo_url)
            links = extract_links(readme, limit)
            print(f"Extracted {len(links)} links from README")

        if not links:
            print("No links found.")
            return

        # Show sample
        print("\nSample:")
        for title, url in links[:5]:
            print(f"  {title[:60]}")
            print(f"    {url[:100]}")
        print(f"  ... and {len(links) - 5} more\n")

        await ingest_links(dss, links, crawl=crawl)


if __name__ == "__main__":
    asyncio.run(main())
