#!/usr/bin/env python3
"""Overnight books, papers, and PDF ingestion job.

Targets GitHub repos known for free books, research papers,
documentation, and educational resources.

For each link: extracts PDF/EPUB/Markdown content via dss-docs.py extractors,
or clones repos with document-heavy contents (tutorials, books in markdown).

Run: nohup python3 -u scripts/dss-overnight-books.py > /tmp/dss-overnight-books.log 2>&1 &

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


# ── Document extraction ──────────────────────────────────────────

DOCUMENT_EXTENSIONS = {'.pdf', '.epub', '.mobi', '.djvu', '.ps', '.dvi'}

def is_document_url(url: str) -> str | None:
    """Return content-type hint if URL points to a document."""
    path = urlparse(url).path.lower()
    for ext in DOCUMENT_EXTENSIONS:
        if path.endswith(ext):
            return ext.lstrip('.')
    # arxiv PDF links
    if 'arxiv.org/pdf/' in url:
        return 'pdf'
    if 'arxiv.org/abs/' in url:
        return 'arxiv'  # has PDF equivalent
    return None


def download_document(url: str) -> bytes | None:
    """Download a document file (PDF, EPUB, etc.)."""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'DSS/1.0'})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except Exception:
        return None


def extract_pdf_text(data: bytes) -> str:
    try:
        import fitz
        doc = fitz.open(stream=data, filetype='pdf')
        pages = [page.get_text() for page in doc]
        doc.close()
        return '\n\n'.join(pages)
    except ImportError:
        return _error("pymupdf not installed")
    except Exception as e:
        return _error(f"PDF extract: {e}")


def extract_epub_text(data: bytes) -> str:
    try:
        from ebooklib import epub
        import html.parser as _html

        with tempfile.NamedTemporaryFile(suffix='.epub', delete=False) as tmp:
            tmp.write(data)
            tmp.flush()
            book = epub.read_epub(tmp.name)
        Path(tmp.name).unlink()

        chapters = []
        for item in book.get_items():
            if item.get_type() == 9:
                text = item.get_content().decode('utf-8', errors='replace')
                class S(_html.HTMLParser):
                    def __init__(self):
                        super().__init__()
                        self.text = []
                    def handle_data(self, d):
                        self.text.append(d)
                s = S(); s.feed(text)
                chapters.append('\n'.join(s.text))
        return '\n\n'.join(chapters)
    except ImportError:
        return _error("ebooklib not installed")
    except Exception as e:
        return _error(f"EPUB extract: {e}")


def extract_arxiv_pdf(abs_url: str) -> tuple[str, str]:
    """Fetch arxiv paper: PDF text + abstract."""
    arxiv_id = abs_url.split('/')[-1]
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    data = download_document(pdf_url)
    if not data:
        return "", ""
    return extract_pdf_text(data), pdf_url


def _error(msg: str) -> str:
    return f"[Error: {msg}]"


# ── Repo cloning for markdown-book repos ────────────────────────

SKIP_GLOBS = ['node_modules', '.git', '__pycache__', 'target', 'build', 'dist',
              'vendor', '.venv', 'venv', '.cache',
              '.png', '.jpg', '.gif', '.svg', '.ico', '.mp3', '.mp4', '.zip', '.tar']

def clone_and_extract_markdown(repo_url: str, limit: int = 200) -> list[dict]:
    """Clone a repo and extract all markdown/text files (for book repos)."""
    parts = repo_url.rstrip('/').split('/')
    repo = parts[-1].replace('.git', '')
    user = parts[-2] if len(parts) >= 2 else 'unknown'
    clone_url = f"https://github.com/{user}/{repo}.git"

    with tempfile.TemporaryDirectory(prefix='dss-book-') as tmpdir:
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
            suffix = fpath.suffix.lower()
            if suffix not in ('.md', '.rst', '.txt', '.tex', '.adoc', '.org'):
                continue
            try:
                if fpath.stat().st_size > 500_000:
                    continue
                content = fpath.read_text(errors='replace')
            except Exception:
                continue
            if not content.strip(): continue
            files.append({
                'path': rel,
                'content': content[:100000],
                'words': len(content.split()),
            })
            if len(files) >= limit:
                break

        return files


# ── Target repos ─────────────────────────────────────────────────

BOOK_PAPER_REPOS = [
    # Free books and programming resources
    "https://github.com/EbookFoundation/free-programming-books",
    "https://github.com/papers-we-love/papers-we-love",

    # Free books written as markdown repos
    "https://github.com/getify/You-Dont-Know-JS",
    "https://github.com/mhinz/vim-galore",
    "https://github.com/rockerBOO/awesome-neovim",
    "https://github.com/learn-anything/books",
    "https://github.com/dariubs/GoBooks",
    "https://github.com/hackerkid/Mind-Expanding-Books",
    "https://github.com/vhf/free-programming-books",  # mirror

    # Documentation and tutorials
    "https://github.com/rust-lang/book",
    "https://github.com/rust-lang/rust-by-example",
    "https://github.com/rust-lang/reference",
    "https://github.com/golang/go/wiki",
    "https://github.com/ziishaned/learn-regex",
    "https://github.com/denysdovhan/wtfjs",
    "https://github.com/ryanmcdermott/clean-code-javascript",
    "https://github.com/elsewhencode/project-guidelines",
    "https://github.com/lydiahallie/javascript-questions",
    "https://github.com/sdras/awesome-actions",

    # Research papers and theses
    "https://github.com/paperswithcode/releasing-research-code",
    "https://github.com/terryum/awesome-deep-learning-papers",
    "https://github.com/floodsung/Deep-Learning-Papers-Reading-Roadmap",
    "https://github.com/aleju/papers",
    "https://github.com/ojroques/awesome-ml-papers",

    # System design and architecture
    "https://github.com/donnemartin/system-design-primer",

    # Math and CS
    "https://github.com/ossu/math",
    "https://github.com/ossu/computer-science",

    # Self-hosted and ops
    "https://github.com/awesome-foss/awesome-sysadmin",
    "https://github.com/kahun/awesome-sysadmin",
]


async def main():
    limit = 200
    for arg in sys.argv[1:]:
        if arg.isdigit():
            limit = int(arg)

    t_start = datetime.datetime.now()
    print(f"Overnight books/papers/PDF ingestion")
    print(f"  Target repos: {len(BOOK_PAPER_REPOS)}")
    print(f"  Links per repo: {limit}")
    print(f"  Started: {t_start.strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
        total_docs = 0
        total_md_files = 0
        total_repos_cloned = 0

        for i, repo_url in enumerate(BOOK_PAPER_REPOS, 1):
            repo_name = repo_url.rstrip('/').split('/')[-1]
            t0 = datetime.datetime.now()
            print(f"[{i}/{len(BOOK_PAPER_REPOS)}] {repo_name}  ({t0.strftime('%H:%M:%S')})")

            try:
                readme = fetch_readme(repo_url)
                links = extract_links(readme, limit)
                print(f"  {len(links)} links extracted")
                if not links:
                    continue

                docs_this = 0

                # Phase 1: Extract PDFs, EPUBs, and arxiv papers from links
                for title, url in links:
                    doctype = is_document_url(url)
                    if not doctype:
                        continue

                    text = ""
                    source_url = url

                    if doctype == 'pdf':
                        data = download_document(url)
                        if data:
                            text = extract_pdf_text(data)
                    elif doctype == 'epub':
                        data = download_document(url)
                        if data:
                            text = extract_epub_text(data)
                    elif doctype == 'arxiv':
                        text, source_url = extract_arxiv_pdf(url)

                    if text and not text.startswith('[Error'):
                        payload = {
                            "url": source_url,
                            "markdown": text[:100000],
                            "title": title[:200],
                            "source_domain": urlparse(source_url).netloc,
                            "word_count": len(text.split()),
                            "tags": ["book", doctype, repo_name],
                        }
                        try:
                            resp = await client.post(
                                f"{WAREHOUSE_URL}/ingest",
                                json=payload,
                                timeout=30.0,
                            )
                            if resp.status_code == 200:
                                docs_this += 1
                                total_docs += 1
                        except Exception as e:
                            pass

                    if docs_this % 20 == 0 and docs_this > 0:
                        print(f"    documents: {docs_this}")

                if docs_this:
                    print(f"    {docs_this} documents extracted (PDF/EPUB/arxiv)")

                # Phase 2: Clone the repo itself if it contains markdown books/tutorials
                md_files = clone_and_extract_markdown(repo_url, limit=100)
                if md_files:
                    ok = 0
                    for f in md_files:
                        payload = {
                            "url": f"{repo_url}/blob/main/{f['path']}",
                            "markdown": f['content'],
                            "title": f"{repo_name}/{f['path']}",
                            "source_domain": "github.com",
                            "word_count": f['words'],
                            "tags": ["book", "markdown", repo_name],
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
                    total_md_files += ok
                    total_repos_cloned += 1
                    print(f"    {ok} markdown files from repo clone")

                # Stats checkpoint
                try:
                    resp = await client.get(f"{WAREHOUSE_URL}/stats", timeout=10.0)
                    stats = resp.json()
                    print(f"  warehouse: {stats['total_entries']} entries, {stats['db_size_mb']}MB")
                except Exception:
                    pass

                elapsed = (datetime.datetime.now() - t0).total_seconds()
                print(f"  done in {elapsed:.0f}s")

            except Exception as e:
                print(f"  ✗ {repo_name}: {e}")
                continue

            print()

        t_end = datetime.datetime.now()
        duration = t_end - t_start
        print(f"{'='*60}")
        print(f"DONE — Books & Papers Overnight")
        print(f"  Started:  {t_start.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Finished: {t_end.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  Duration: {duration}")
        print(f"  Results:")
        print(f"    {total_docs} documents (PDF/EPUB/arxiv)")
        print(f"    {total_md_files} markdown files from {total_repos_cloned} repos")
        try:
            resp = await client.get(f"{WAREHOUSE_URL}/stats", timeout=10.0)
            stats = resp.json()
            print(f"    Warehouse: {stats['total_entries']} entries, {stats['db_size_mb']}MB")
        except Exception:
            pass

        print(f"\nOVERNIGHT_BOOKS_COMPLETED: {t_end.strftime('%Y-%m-%d %H:%M:%S')}  duration={duration}")


if __name__ == "__main__":
    asyncio.run(main())
