#!/usr/bin/env python3
"""Overnight awesome-list ingestion + source code warehousing.

Extracts links from popular awesome-* repos. For each link:
  1. Crawls the page (HTML→markdown) via web-api
  2. If it's a GitHub repo, clones and extracts source files

Run: nohup python3 -u scripts/dss-overnight.py --crawl > /tmp/dss-overnight.log 2>&1 &

Logs start/end time with total duration.
"""
import asyncio
import datetime
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

WAREHOUSE_URL = "http://localhost:8009"
WEB_API_URL = "http://localhost:8014"

# ── README parser ─────────────────────────────────────────────────

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


# ── Repo detection + code extraction ─────────────────────────────

REPO_PATTERN = re.compile(r'https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?(?:/.*)?$')
SKIP_PATHS = {'blob', 'tree', 'issues', 'pulls', 'wiki', 'releases', 'actions', 'projects', 'discussions', 'settings'}

LANGUAGE_MAP = {
    '.py': 'python', '.rs': 'rust', '.go': 'go', '.js': 'javascript',
    '.ts': 'typescript', '.c': 'c', '.h': 'c', '.cpp': 'cpp', '.hpp': 'cpp',
    '.java': 'java', '.rb': 'ruby', '.sh': 'bash', '.md': 'markdown',
    '.json': 'json', '.yaml': 'yaml', '.yml': 'yaml', '.toml': 'toml',
    '.css': 'css', '.html': 'html', '.sql': 'sql', '.swift': 'swift',
    '.kt': 'kotlin', '.scala': 'scala', '.lua': 'lua', '.zig': 'zig',
    '.hs': 'haskell', '.ml': 'ocaml', '.erl': 'erlang', '.ex': 'elixir',
    '.dart': 'dart', '.r': 'r', '.jl': 'julia', '.nim': 'nim',
}

SKIP_GLOBS = ['node_modules', '.git', '__pycache__', 'target', 'build', 'dist',
              'vendor', '.venv', 'venv', '.cache', '.next', '.nuxt',
              'package-lock.json', 'yarn.lock', 'Cargo.lock', 'Gemfile.lock',
              '.png', '.jpg', '.gif', '.svg', '.ico', '.woff', '.mp3', '.mp4',
              '.pdf', '.zip', '.tar', '.gz']

def is_repo_url(url: str) -> tuple[str, str] | None:
    m = REPO_PATTERN.match(url)
    if not m:
        return None
    user, repo = m.group(1), m.group(2)
    path_parts = urlparse(url).path.strip('/').split('/')
    if len(path_parts) > 2 and path_parts[2] in SKIP_PATHS:
        return None
    return user, repo


def clone_and_extract(repo_url: str, limit: int = 100) -> list[dict]:
    user, repo = repo_url.split('/')[-2:]
    repo = repo.replace('.git', '')
    clone_url = f"https://github.com/{user}/{repo}.git"

    with tempfile.TemporaryDirectory(prefix='dss-repo-') as tmpdir:
        for branch in ['main', 'master']:
            result = subprocess.run(
                ['git', 'clone', '--depth', '1', '--single-branch', '--branch', branch,
                 '--filter=blob:none', clone_url, tmpdir],
                capture_output=True, text=True, timeout=60,
            )
            if result.returncode == 0:
                break
        else:
            return []

        files = []
        for fpath in sorted(Path(tmpdir).rglob('*')):
            if not fpath.is_file():
                continue
            rel = str(fpath.relative_to(tmpdir))
            if any(g in rel for g in SKIP_GLOBS):
                continue
            try:
                if fpath.stat().st_size > 500_000:
                    continue
            except Exception:
                continue

            lang = LANGUAGE_MAP.get(fpath.suffix.lower(), 'text')
            try:
                content = fpath.read_text(errors='replace')
            except Exception:
                continue
            if not content.strip():
                continue

            files.append({
                'path': rel,
                'language': lang,
                'content': content[:100000],
                'size': len(content),
                'lines': content.count('\n') + 1,
            })
            if len(files) >= limit:
                break

        return files


# ── Ingest ───────────────────────────────────────────────────────

async def ingest_code_files(client: httpx.AsyncClient, repo_url: str, files: list[dict]) -> int:
    repo_name = repo_url.rstrip('/').split('/')[-1].replace('.git', '')
    ok = 0
    for f in files:
        payload = {
            "url": f"{repo_url}/blob/main/{f['path']}",
            "markdown": f"```{f['language']}\n{f['content']}\n```",
            "title": f"{repo_name}/{f['path']}",
            "source_domain": "github.com",
            "word_count": len(f['content'].split()),
            "tags": ["code", f['language'], repo_name, "awesome-list"],
        }
        try:
            resp = await client.post(
                f"{WAREHOUSE_URL}/ingest",
                json=payload,
                timeout=30.0,
            )
            if resp.status_code == 200:
                ok += 1
        except Exception:
            pass
    return ok


# ── Awesome-list repos ───────────────────────────────────────────

AWESOME_REPOS = [
    "https://github.com/sindresorhus/awesome",
    "https://github.com/rust-unofficial/awesome-rust",
    "https://github.com/vinta/awesome-python",
    "https://github.com/avelino/awesome-go",
    "https://github.com/akullpp/awesome-java",
    "https://github.com/sorrycc/awesome-javascript",
    "https://github.com/papers-we-love/papers-we-love",
    "https://github.com/Hack-with-Github/Awesome-Hacking",
    "https://github.com/awesome-selfhosted/awesome-selfhosted",
    "https://github.com/kdeldycke/awesome-falsehood",
    "https://github.com/donnemartin/system-design-primer",
    "https://github.com/jwasham/coding-interview-university",
    "https://github.com/EbookFoundation/free-programming-books",
    "https://github.com/ossu/computer-science",
    "https://github.com/sdmg15/Best-websites-a-programmer-should-visit",
    "https://github.com/kamranahmedse/developer-roadmap",
    "https://github.com/trimstray/the-book-of-secret-knowledge",
    "https://github.com/dypsilon/frontend-dev-bookmarks",
    "https://github.com/enaqx/awesome-pentest",
    "https://github.com/matiassingers/awesome-readme",
]


async def main():
    limit = 100
    crawl = False
    do_repos = True  # always extract repos by default
    for arg in sys.argv[1:]:
        if arg == '--crawl':
            crawl = True
        elif arg == '--no-repos':
            do_repos = False
        elif arg.isdigit():
            limit = int(arg)
    t_start = datetime.datetime.now()

    print(f"Overnight awesome-list ingestion + source code warehousing")
    print(f"  Repos: {len(AWESOME_REPOS)}")
    print(f"  Links per list: {limit}")
    print(f"  Crawl pages: {crawl}")
    print(f"  Warehouse code: {do_repos}")
    print(f"  Started: {t_start.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        total_links = 0
        total_crawled = 0
        total_code_files = 0
        total_repos_cloned = 0

        for i, repo_url in enumerate(AWESOME_REPOS, 1):
            repo_name = repo_url.rstrip('/').split('/')[-1]
            t0 = datetime.datetime.now()
            print(f"[{i}/{len(AWESOME_REPOS)}] {repo_name}  ({t0.strftime('%H:%M:%S')})")

            try:
                readme = fetch_readme(repo_url)
                links = extract_links(readme, limit)
                print(f"  {len(links)} links extracted")
                total_links += len(links)
                if not links:
                    continue

                # Crawl pages for full content
                crawled_this = 0
                if crawl:
                    urls = [url for _, url in links]
                    batch_size = 5
                    for j in range(0, len(urls), batch_size):
                        batch = urls[j:j + batch_size]
                        try:
                            resp = await client.post(
                                f"{WEB_API_URL}/api/ingest/urls",
                                json={"urls": batch, "timeout": 20},
                                timeout=90.0,
                            )
                            if resp.status_code == 200:
                                data = resp.json()
                                n = data.get("success_count", 0)
                                crawled_this += n
                                total_crawled += n
                                print(f"    crawl batch {j//batch_size+1}: {n}/{len(batch)} ok (total: {total_crawled})")
                        except Exception as e:
                            print(f"    ⚠ crawl batch {j}: {e}")
                        await asyncio.sleep(1)

                # Clone and extract source code from GitHub repo links
                code_files_this = 0
                if do_repos:
                    repo_urls = set()
                    for _, url in links:
                        info = is_repo_url(url)
                        if info:
                            user, repo = info
                            repo_urls.add(f"https://github.com/{user}/{repo}")

                    if repo_urls:
                        print(f"  Cloning {len(repo_urls)} repos for source extraction...")
                        for j, rurl in enumerate(sorted(repo_urls)[:20]):  # max 20 repos per list
                            files = clone_and_extract(rurl, limit=100)
                            if files:
                                ok = await ingest_code_files(client, rurl, files)
                                code_files_this += ok
                                total_code_files += ok
                                total_repos_cloned += 1
                                print(f"    [{j+1}/{min(len(repo_urls),20)}] {rurl.split('/')[-1]}: {ok} files")
                            else:
                                print(f"    [{j+1}/{min(len(repo_urls),20)}] {rurl.split('/')[-1]}: clone failed, skipping")

                # Stats checkpoint
                try:
                    resp = await client.get(f"{WAREHOUSE_URL}/stats", timeout=10.0)
                    stats = resp.json()
                    print(f"  warehouse: {stats['total_entries']} entries, {stats['db_size_mb']}MB")
                except Exception:
                    pass

                elapsed = (datetime.datetime.now() - t0).total_seconds()
                print(f"  done in {elapsed:.0f}s (crawled {crawled_this} pages, {code_files_this} code files)")

            except Exception as e:
                print(f"  ✗ {repo_name}: {e}")
                import traceback; traceback.print_exc()
                continue

            print()

        t_end = datetime.datetime.now()
        duration = t_end - t_start
        print(f"{'='*60}")
        print(f"DONE")
        print(f"  Started:  {t_start.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Finished: {t_end.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Duration: {duration}")
        print(f"  Results:")
        print(f"    {total_links} links from {len(AWESOME_REPOS)} awesome-lists")
        if crawl:
            print(f"    {total_crawled} pages crawled into warehouse")
        if do_repos:
            print(f"    {total_code_files} source files from {total_repos_cloned} repos")
        try:
            resp = await client.get(f"{WAREHOUSE_URL}/stats", timeout=10.0)
            stats = resp.json()
            print(f"    Warehouse: {stats['total_entries']} entries, {stats['db_size_mb']}MB, {stats.get('total_domains', '?')} domains")
        except Exception:
            pass

        # Final timestamp on its own line for easy grepping
        print(f"\nOVERNIGHT_COMPLETED: {t_end.strftime('%Y-%m-%d %H:%M:%S')}  duration={duration}")


if __name__ == "__main__":
    asyncio.run(main())
