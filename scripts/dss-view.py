#!/usr/bin/env python3
"""dss-view — vim-style warehouse content browser (ANSI, no flicker).

Navigation:
  j / ↓        move down
  k / ↑        move up
  n            next page
  p            prev page
  Enter / l    view full content (in $PAGER)
  /            search warehouse
  h            help
  q            quit
  gg           jump to top
  G            jump to bottom

Usage:
  python3 scripts/dss-view.py                    # Browse recent entries
  python3 scripts/dss-view.py --search "rust"    # Search and browse
"""
import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sdk import DSSClient


# ── ANSI ──────────────────────────────────────────────────────────
CLEAR = "\033[H\033[2J"
BOLD = "\033[1m"
DIM = "\033[2m"
REV = "\033[7m"
YELLOW = "\033[33m"
GREEN = "\033[32m"
RESET = "\033[0m"


def getch() -> str:
    """Single keystroke with arrow-key decoding."""
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


# ── Render ────────────────────────────────────────────────────────

def render(entries: list[dict], selected: int, page: int, page_size: int):
    """Render one page. ANSI-clean, no flicker."""
    total = len(entries)
    start = page * page_size
    end = min(start + page_size, total)
    total_pages = max(1, (total + page_size - 1) // page_size)

    lines = []
    lines.append(f"{CLEAR}{BOLD}DSS Warehouse{RESET}  {DIM}{total} entries  page {page+1}/{total_pages}{RESET}")
    lines.append(f"{DIM}j/k:move  Enter:view  /:search  n/p:page  gg/G:top/bot  q:quit  h:help{RESET}")
    lines.append("")

    for i in range(start, end):
        e = entries[i]
        title = (e.get('title') or 'Untitled')[:52].replace('\n', ' ')
        domain = (e.get('source_domain') or '?')[:18]
        words = e.get('word_count', 0)
        marker = "→" if i == selected else " "

        if i == selected:
            lines.append(f"{REV}{marker}{i:>4d} {title:52s} {words:>6d}w  {domain:18s}{RESET}")
        else:
            lines.append(f"{marker}{i:>4d} {title:52s} {words:>6d}w  {domain:18s}")

    # Fill to page_size
    for _ in range(page_size - (end - start)):
        lines.append("")

    lines.append(f"{DIM}[{page+1}/{total_pages}]  {total} entries{RESET}")

    sys.stdout.write("\n".join(lines))
    sys.stdout.flush()


def view_in_pager(title: str, content: str):
    """Display content in $PAGER."""
    pager = os.environ.get('PAGER', 'less -R')
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False, prefix='dss-') as f:
        f.write(f"# {title}\n\n")
        f.write(content)
        f.flush()
        subprocess.run(f"{pager} '{f.name}'", shell=True)
        os.unlink(f.name)


# ── Main ──────────────────────────────────────────────────────────

async def main():
    search_query = ""
    args = sys.argv[1:]
    if '--search' in args:
        idx = args.index('--search')
        if idx + 1 < len(args):
            search_query = args[idx + 1]

    async with DSSClient() as dss:
        if search_query:
            entries = await dss.warehouse_search(search_query, limit=500)
            entries.sort(key=lambda e: e.get('id', 0), reverse=True)
        else:
            entries = []
            seen = set()
            for term in ["the", "that", "this", "with", "from", "have", "they", "what"]:
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
            sys.stdout.write(CLEAR)
            print("No entries found.")
            return

        selected = 0
        page = 0
        page_size = 20

        while True:
            render(entries, selected, page, page_size)
            ch = getch()

            if ch in ('q', 'ESC', 'C-C'):
                sys.stdout.write(CLEAR)
                print("closed.")
                break
            elif ch in ('j', 'DOWN'):
                if selected < len(entries) - 1:
                    selected += 1
                    if selected >= (page + 1) * page_size:
                        page += 1
            elif ch in ('k', 'UP'):
                if selected > 0:
                    selected -= 1
                    if selected < page * page_size:
                        page = max(page - 1, 0)
            elif ch == 'g':
                ch2 = getch()
                if ch2 == 'g':
                    selected = 0
                    page = 0
            elif ch == 'G':
                selected = len(entries) - 1
                page = max(0, (len(entries) - 1) // page_size)
            elif ch in ('n',):
                page = min(page + 1, (len(entries) - 1) // page_size)
                selected = page * page_size
            elif ch in ('p',):
                page = max(page - 1, 0)
                selected = page * page_size
            elif ch in ('ENTER', 'l', '\r', '\n'):
                entry = entries[selected]
                entry_id = entry.get('id')
                if entry_id:
                    try:
                        import httpx
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
                import termios, tty
                fd = sys.stdin.fileno()
                old = termios.tcgetattr(fd)
                tty.setcbreak(fd)
                sys.stdout.write(CLEAR + "Search: ")
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
                import termios, tty
                fd = sys.stdin.fileno()
                old = termios.tcgetattr(fd)
                tty.setcbreak(fd)
                sys.stdout.write(CLEAR + """
DSS Viewer — Keybindings

  j / ↓         move down
  k / ↑         move up
  n             next page
  p             prev page
  Enter / l     view full content (opens in less)
  /             search warehouse
  gg            jump to top
  G             jump to bottom
  h             this help
  q             quit

Content opens in $PAGER (less). Use less keys to scroll.
Press Enter to continue...
""")
                sys.stdout.flush()
                input()
                termios.tcsetattr(fd, termios.TCSADRAIN, old)


if __name__ == "__main__":
    asyncio.run(main())
