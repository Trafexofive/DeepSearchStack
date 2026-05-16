#!/usr/bin/env python3
"""dss-view — vim-style warehouse content browser (less-like, no escape codes).

Navigation:
  j / Down     next entry
  k / Up       prev entry
  Enter / l    view full content
  /            search (then type query + Enter)
  q            quit
  h            help

Usage:
  python3 scripts/dss-view.py                    # Browse recent entries
  python3 scripts/dss-view.py --search "rust"    # Search and browse

Pipes content through $PAGER (or less) for scrolling.
"""
import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sdk import DSSClient


def getch() -> str:
    """Read a single keystroke, handling escape sequences for arrows."""
    import termios, tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        ch = sys.stdin.buffer.read(1)
        if ch == b'\x1b':
            seq = sys.stdin.buffer.read(2)
            if seq == b'[A': return 'UP'
            if seq == b'[B': return 'DOWN'
            return 'ESC'
        if ch == b'\x03': return 'C-C'
        if ch == b'\x0d': return 'ENTER'
        return ch.decode('utf-8', errors='replace')
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def view_in_pager(title: str, content: str):
    """Display content in $PAGER (less)."""
    pager = os.environ.get('PAGER', 'less -R')
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, prefix='dss-') as f:
        f.write(f"# {title}\n\n")
        f.write(content)
        f.flush()
        subprocess.run(f"{pager} '{f.name}'", shell=True)
        os.unlink(f.name)


def print_list(entries: list[dict], selected: int, page: int, page_size: int):
    """Print one page of entries. No escape codes, plain text."""
    subprocess.run(['clear'], shell=True)  # reliable clear
    total = len(entries)
    start = page * page_size
    end = min(start + page_size, total)

    print(f"DSS Warehouse — {total} entries")
    print(f"j/k:move  Enter:view  /:search  n/p:page  q:quit  h:help")
    print("-" * 78)

    for i in range(start, end):
        e = entries[i]
        title = (e.get('title') or 'Untitled')[:55].replace('\n', ' ')
        domain = (e.get('source_domain') or '?')[:18]
        words = e.get('word_count', 0)
        marker = "→" if i == selected else " "
        print(f"{marker}{i:>4d} {title:55s} {words:>6d}w  {domain}")

    if end < total:
        print(f"\n  ... {total - end} more entries (press n for next page)")

    page_num = page + 1
    total_pages = (total + page_size - 1) // page_size
    print(f"\n  [{page_num}/{total_pages}]", end='', flush=True)


async def main():
    search_query = ""
    args = sys.argv[1:]
    if '--search' in args:
        idx = args.index('--search')
        if idx + 1 < len(args):
            search_query = args[idx + 1]

    async with DSSClient() as dss:
        # Fetch entries
        if search_query:
            entries = await dss.warehouse_search(search_query, limit=500)
            entries.sort(key=lambda e: e.get('id', 0), reverse=True)
        else:
            # Fetch across common stopwords for broad coverage
            entries = []
            seen = set()
            for term in ["the", "that", "this", "with", "from", "have", "they", "what", "when"]:
                batch = await dss.warehouse_search(term, limit=100)
                for e in batch:
                    eid = e.get('id')
                    if eid not in seen:
                        seen.add(eid)
                        entries.append(e)
                if len(entries) >= 500:
                    break
            entries.sort(key=lambda e: e.get('id', 0), reverse=True)

        if not entries:
            print("No entries found.")
            return

        selected = 0
        page = 0
        page_size = 20

        while True:
            print_list(entries, selected, page, page_size)
            ch = getch()

            if ch in ('q', 'ESC', 'C-C'):
                print("\n")
                break
            elif ch in ('j', 'DOWN'):
                selected = min(selected + 1, len(entries) - 1)
                # Auto-advance page
                if selected >= (page + 1) * page_size:
                    page += 1
            elif ch in ('k', 'UP'):
                selected = max(selected - 1, 0)
                if selected < page * page_size:
                    page = max(page - 1, 0)
            elif ch in ('n',):
                page = min(page + 1, (len(entries) - 1) // page_size)
                selected = page * page_size
            elif ch in ('p',):
                page = max(page - 1, 0)
                selected = page * page_size
            elif ch in ('ENTER', 'l', '\r', '\n'):
                # View content
                entry = entries[selected]
                entry_id = entry.get('id')
                if entry_id:
                    try:
                        async with httpx.AsyncClient(timeout=10.0) as c:
                            resp = await c.get(f"{dss.warehouse}/content/{entry_id}")
                            resp.raise_for_status()
                            content = resp.json()
                    except Exception as e:
                        content = {"title": "Error", "markdown": str(e)}

                    title = content.get('title', 'Untitled')
                    md = content.get('markdown', '')
                    url = content.get('url', '')
                    domain = content.get('source_domain', '?')
                    words = content.get('word_count', 0)

                    full_text = f"URL: {url}\nDomain: {domain}\nWords: {words}\n\n{md}"
                    view_in_pager(title, full_text)
            elif ch == '/':
                # Search — need to exit raw mode for input
                import termios, tty
                fd = sys.stdin.fileno()
                old = termios.tcgetattr(fd)
                tty.setcbreak(fd)
                subprocess.run(['clear'], shell=True)
                sys.stdout.write("Search: ")
                sys.stdout.flush()
                query = input()
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
                if query.strip():
                    entries = await dss.warehouse_search(query.strip(), limit=500)
                    entries.sort(key=lambda e: e.get('id', 0), reverse=True)
                    selected = 0
                    page = 0
                    search_query = query.strip()
            elif ch == 'h':
                subprocess.run(['clear'], shell=True)
                print("""DSS Viewer — Keybindings

  j / ↓        move down
  k / ↑        move up
  Enter / l    view full content (opens in less)
  n            next page
  p            prev page
  /            search warehouse
  h            this help
  q            quit

Content is displayed in your $PAGER (less by default).
Use less keys to scroll: j/k, gg/G, /search, q to return.
""")
                input("Press Enter to continue...")

    subprocess.run(['clear'], shell=True)
    print("DSS Viewer closed.")


if __name__ == "__main__":
    import httpx
    asyncio.run(main())
