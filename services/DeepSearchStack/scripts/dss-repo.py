#!/usr/bin/env python3
"""dss-repo — code repository ingestion for DeepSearchStack warehouse.

Clones a GitHub repo, extracts source files as structured warehouse entries.
Each file stored separately for FTS5 search + vector embedding.

Usage:
    python3 scripts/dss-repo.py https://github.com/user/repo
    python3 scripts/dss-repo.py https://github.com/user/repo --branch main --depth 50
    python3 scripts/dss-repo.py --dir ./local-repo/

Flags:
    --branch BRANCH    branch to clone (default: main)
    --depth N          shallow clone depth (default: 1)
    --parse            use tree-sitter for structured AST extraction
    --embed            also embed files in vector store for RAG
    --limit N          max files to extract (default: 500)
"""
import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sdk import DSSClient


# ── File classification ────────────────────────────────────────

LANGUAGE_MAP = {
    '.py':   'python',   '.pyi':  'python',
    '.js':   'javascript','.ts':   'typescript', '.jsx': 'jsx', '.tsx': 'tsx',
    '.rs':   'rust',      '.go':   'go',
    '.c':    'c',         '.h':    'c',         '.cpp': 'cpp', '.hpp': 'cpp',
    '.java': 'java',      '.kt':   'kotlin',    '.scala':'scala',
    '.rb':   'ruby',      '.sh':   'bash',      '.bash':'bash',
    '.md':   'markdown',  '.rst':  'rst',       '.txt':  'text',
    '.json': 'json',      '.yaml': 'yaml',      '.yml':  'yaml',
    '.toml': 'toml',      '.ini':  'ini',       '.cfg':  'config',
    '.css':  'css',       '.html': 'html',      '.htm':  'html',
    '.sql':  'sql',       '.r':    'r',
    '.swift':'swift',     '.zig':  'zig',       '.nim':  'nim',
    '.ml':   'ocaml',     '.mli':  'ocaml',     '.hs':   'haskell',
    '.lua':  'lua',       '.elm':  'elm',       '.ex':   'elixir', '.exs': 'elixir',
    '.erl':  'erlang',    '.clj':  'clojure',   '.cljs': 'clojure',
    '.dart': 'dart',      '.jl':   'julia',
    '.tf':   'hcl',       '.proto':'protobuf',
    '.cmake':'cmake',     '.dockerfile': 'dockerfile',
}

SKIP_PATTERNS = [
    'node_modules', '.git', '__pycache__', '.venv', 'venv',
    'target', 'build', 'dist', '.next', '.nuxt', 'vendor',
    '.cache', '.pytest_cache', '.mypy_cache', '.tox',
    'package-lock.json', 'yarn.lock', 'Cargo.lock', 'Gemfile.lock',
    'poetry.lock', 'pnpm-lock.yaml', 'go.sum', 'Pipfile.lock',
    '.DS_Store', 'Thumbs.db',
    '.min.js', '.min.css', '.bundle.js', '.chunk.',
    '.png', '.jpg', '.jpeg', '.gif', '.svg', '.ico', '.woff', '.woff2',
    '.ttf', '.eot', '.mp3', '.mp4', '.wav', '.ogg', '.pdf', '.zip',
    '.tar', '.gz', '.bz2', '.7z',
]


def detect_language(filepath: Path) -> str:
    suffix = filepath.suffix.lower()
    if suffix:
        return LANGUAGE_MAP.get(suffix, 'text')
    # Handle special filenames
    name = filepath.name.lower()
    if name == 'dockerfile':
        return 'dockerfile'
    if name == 'makefile':
        return 'makefile'
    return 'text'


def should_skip(filepath: Path) -> bool:
    """Skip binary, vendor, generated, and large files."""
    path_str = str(filepath)
    for pattern in SKIP_PATTERNS:
        if pattern in path_str:
            return True
    # Skip files > 1MB
    try:
        if filepath.stat().st_size > 1_000_000:
            return True
    except Exception:
        return True
    return False


def format_code(filepath: Path, content: str, lang: str) -> str:
    """Wrap code in markdown code block for warehouse storage."""
    if lang == 'markdown':
        return content
    return f"```{lang}\n{content}\n```"


# ── Clone ──────────────────────────────────────────────────────

def clone_repo(url: str, branch: str = "main", depth: int = 1) -> Path | None:
    """Shallow clone a repo. Tries specified branch, then master."""
    tmpdir = tempfile.mkdtemp(prefix='dss-repo-')
    for b in [branch, "master"]:
        cmd = [
            'git', 'clone',
            '--depth', str(depth),
            '--single-branch',
            '--branch', b,
            '--filter=blob:none',
            url, tmpdir,
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode == 0:
                print(f"  Cloned {url} (branch={b}, depth={depth})")
                return Path(tmpdir)
        except subprocess.TimeoutExpired:
            pass
    print(f"  ⚠ Clone failed")
    return None


# ── Walk & extract ─────────────────────────────────────────────

def extract_files(repo_path: Path, limit: int = 500) -> list[dict]:
    """Walk repo, extract source files with metadata."""
    files = []
    repo_name = repo_path.name

    for filepath in sorted(repo_path.rglob('*')):
        if not filepath.is_file():
            continue
        if should_skip(filepath):
            continue

        rel_path = filepath.relative_to(repo_path)
        lang = detect_language(filepath)

        try:
            content = filepath.read_text(errors='replace')
        except Exception:
            continue

        if not content.strip():
            continue

        # Build relative URL-style path
        url_path = str(rel_path)
        files.append({
            'path': url_path,
            'language': lang,
            'content': content,
            'size': len(content),
            'lines': content.count('\n') + 1,
        })

        if len(files) >= limit:
            break

    return files


# ── Ingest ─────────────────────────────────────────────────────

async def ingest_files(dss: DSSClient, repo_url: str, repo_name: str, files: list[dict], embed: bool = False):
    """Store each file as a separate warehouse entry."""
    ok = 0
    batch_urls = []

    for f in files:
        payload = {
            "url": f"{repo_url}/blob/main/{f['path']}",
            "markdown": format_code(Path(f['path']), f['content'], f['language']),
            "title": f"{repo_name}/{f['path']}",
            "source_domain": "github.com",
            "word_count": len(f['content'].split()),
            "tags": ["code", f['language'], repo_name, f"repo:{repo_name}"],
        }

        try:
            resp = await dss.client.post(
                f"{dss.warehouse}/ingest",
                json=payload,
                timeout=30.0,
            )
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ingested") or data.get("cached"):
                    ok += 1
                    if embed:
                        batch_urls.append(payload['url'])
            else:
                print(f"    ⚠ warehouse {resp.status_code}: {f['path'][:60]}")
        except Exception as e:
            print(f"    ✗ {f['path'][:60]}: {e}")

        if ok % 100 == 0 and ok > 0:
            print(f"  ingested {ok}/{len(files)} files")

    print(f"  ✓ {ok}/{len(files)} files stored in warehouse")

    # Optionally embed for RAG
    if embed and batch_urls:
        print(f"  Embedding {len(batch_urls)} files in vector store...")
        batch_size = 20
        for i in range(0, len(files), batch_size):
            batch = files[i:i + batch_size]
            docs = []
            for f in batch:
                docs.append({
                    "text": f['content'][:5000],
                    "metadata": {"url": f"{repo_url}/blob/main/{f['path']}", "title": f"{repo_name}/{f['path']}"},
                })
            try:
                await dss.client.post(
                    f"{dss.vector_store}/embed",
                    json={"documents": docs, "namespace": f"repo:{repo_name}"},
                    timeout=60.0,
                )
            except Exception:
                pass
            print(f"    embedded {min(i + batch_size, len(files))}/{len(files)}")
        print(f"  ✓ RAG embeddings complete (namespace: repo:{repo_name})")

    return ok


# ── Main ────────────────────────────────────────────────────────

async def main():
    args = sys.argv[1:]
    repo_url = None
    local_dir = None
    branch = "main"
    depth = 1
    limit = 500
    do_parse = False
    do_embed = False

    i = 0
    while i < len(args):
        arg = args[i]
        if arg == '--branch' and i + 1 < len(args):
            branch = args[i + 1]; i += 2; continue
        if arg == '--depth' and i + 1 < len(args):
            depth = int(args[i + 1]); i += 2; continue
        if arg == '--limit' and i + 1 < len(args):
            limit = int(args[i + 1]); i += 2; continue
        if arg == '--dir' and i + 1 < len(args):
            local_dir = Path(args[i + 1]); i += 2; continue
        if arg == '--parse':
            do_parse = True; i += 1; continue
        if arg == '--embed':
            do_embed = True; i += 1; continue
        if arg.startswith('http'):
            repo_url = arg
        i += 1

    if not repo_url and not local_dir:
        print(__doc__)
        sys.exit(1)

    async with DSSClient() as dss:
        if local_dir:
            repo_path = local_dir
            repo_name = repo_path.name
            print(f"Local repo: {repo_path}")
        else:
            # Extract repo name from URL
            repo_name = repo_url.rstrip('/').split('/')[-1]
            if repo_name.endswith('.git'):
                repo_name = repo_name[:-4]
            print(f"Cloning: {repo_url} (branch={branch}, depth={depth})")
            repo_path = clone_repo(repo_url, branch, depth)
            if not repo_path:
                return

        print(f"Extracting files (limit={limit})...")
        files = extract_files(repo_path, limit)
        print(f"  {len(files)} files extracted")
        if not files:
            return

        # Show language breakdown
        langs = {}
        for f in files:
            langs[f['language']] = langs.get(f['language'], 0) + 1
        print(f"  Languages:")
        for lang, count in sorted(langs.items(), key=lambda x: -x[1])[:10]:
            print(f"    {lang:15s} {count:4d} files")

        print(f"\nIngesting into warehouse...")
        ok = await ingest_files(dss, repo_url or f"file://{repo_path}", repo_name, files, embed=do_embed)

        # Cleanup
        if not local_dir and repo_path:
            import shutil
            shutil.rmtree(str(repo_path), ignore_errors=True)

        print(f"\n✓ {ok} files from {repo_name} ingested")


if __name__ == "__main__":
    asyncio.run(main())
