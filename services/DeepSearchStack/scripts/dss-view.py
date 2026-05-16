#!/usr/bin/env python3
"""dss-view — vim-style TUI for browsing DeepSearchStack warehouse content.

Navigation:
  j / Down     move down
  k / Up       move up
  Enter        view content of selected entry
  /            search warehouse
  r            refresh list
  gg           jump to top
  G            jump to bottom
  Ctrl+D       page down
  Ctrl+U       page up
  q / Esc      quit / back to list

Usage:
  python3 scripts/dss-view.py                    # Browse all warehouse entries
  python3 scripts/dss-view.py --search "rust"    # Search and browse
"""
import asyncio
import os
import sys
import termios
import tty
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sdk import DSSClient


# ── Terminal helpers ───────────────────────────────────────────────────────

def clear():
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()

def move_cursor(row: int, col: int = 0):
    sys.stdout.write(f"\033[{row};{col}H")
    sys.stdout.flush()

def get_terminal_size() -> tuple[int, int]:
    try:
        return os.get_terminal_size()
    except Exception:
        return 80, 24

class RawTerm:
    """Context manager for raw terminal input (single keystrokes)."""
    def __enter__(self):
        self.fd = sys.stdin.fileno()
        self.old = termios.tcgetattr(self.fd)
        tty.setraw(self.fd)
        return self

    def __exit__(self, *args):
        termios.tcsetattr(self.fd, termios.TCSADRAIN, self.old)

    def getch(self) -> str:
        ch = sys.stdin.buffer.read(1)
        if ch == b'\x1b':
            # Escape sequence
            seq = sys.stdin.buffer.read(2)
            if seq == b'[A': return 'UP'
            if seq == b'[B': return 'DOWN'
            if seq == b'[C': return 'RIGHT'
            if seq == b'[D': return 'LEFT'
            return 'ESC'
        if ch == b'\x03': return 'C-C'  # Ctrl+C
        if ch == b'\x04': return 'C-D'  # Ctrl+D
        if ch == b'\x15': return 'C-U'  # Ctrl+U
        if ch == b'\x0d': return 'ENTER'
        if ch == b'\x7f': return 'BS'
        if ch == b'\t': return 'TAB'
        return ch.decode('utf-8', errors='replace')


# ── Rendering ──────────────────────────────────────────────────────────────

def render_list(entries: list[dict], selected: int, offset: int, height: int, search: str = ""):
    """Render the entry list view."""
    clear()
    cols, _ = get_terminal_size()
    cols = max(cols, 60)
    title = " DSS Warehouse " if not search else f" Search: {search} "
    print(f"\033[1;37;44m{title:─<{cols}}\033[0m")

    visible = min(len(entries) - offset, height - 5)
    for i in range(visible):
        idx = offset + i
        entry = entries[idx]
        e_title = (entry.get('title') or 'Untitled').replace('\n', ' ')
        domain = (entry.get('source_domain') or '?')[:18]
        words = entry.get('word_count', 0)
        wid = str(idx)
        # Format: #NNN │ Title... │ NNNNNw │ domain
        title_width = cols - 30
        line = f" {wid:>4s} {e_title[:title_width]:{title_width}s} {words:>6d}w {domain:>18s}"
        if idx == selected:
            print(f"\033[7m{line[:cols]}\033[0m")
        else:
            print(line[:cols])

    # Fill remaining space
    for _ in range(height - 5 - visible):
        print()

    # Status bar
    pct = f"{selected + 1}/{len(entries)}" if entries else "0/0"
    status = f" {pct} | j/k:move Enter:view /:search r:refresh q:quit "
    print(f"\033[1;37;44m{status:<{cols}}\033[0m", end='', flush=True)


def render_content(entry: dict, scroll: int, height: int):
    """Render full content view with scrolling."""
    clear()
    cols, _ = get_terminal_size()
    title = entry.get('title', 'Untitled')
    domain = entry.get('source_domain', '?')
    url = entry.get('url', '')
    words = entry.get('word_count', 0)
    markdown = entry.get('markdown', '')

    # Header
    print(f"\033[1;37;44m{' Content View ':<{cols}}\033[0m")
    print(f"  \033[1m{title[:cols-4]}\033[0m")
    print(f"  \033[2m{url[:cols-4]}\033[0m")
    print(f"  {words} words │ {domain}")
    print("─" * cols)

    # Render markdown with syntax highlighting (just bold headers)
    lines = markdown.split('\n')
    visible_lines = height - 7
    end = min(scroll + visible_lines, len(lines))

    for i in range(scroll, end):
        line = lines[i][:cols - 1]
        if line.startswith('#'):
            print(f"\033[1;33m{line}\033[0m")  # Yellow for headings
        elif line.startswith('```'):
            print(f"\033[2m{line}\033[0m")       # Dim for code fences
        elif line.startswith('>'):
            print(f"\033[32m{line}\033[0m")       # Green for blockquotes
        elif line.startswith('- ') or line.startswith('* '):
            print(f"  {line}")
        else:
            print(line)

    # Status bar
    print("─" * cols)
    pct = f"{scroll}/{len(lines)}"
    status = f" {pct} │ j/k:scroll  gg/G:top/bot  Ctrl+D/U:page  q:back "
    print(f"\033[1;37;44m{status:<{cols}}\033[0m", end='', flush=True)


# ── Main ───────────────────────────────────────────────────────────────────

async def main():
    search_query = ""
    for i, arg in enumerate(sys.argv[1:]):
        if arg == '--search' and i + 1 < len(sys.argv) - 1:
            search_query = sys.argv[i + 2]

    async with DSSClient() as dss:
        # Fetch entries — if no search query, list recent via domain search
        if search_query:
            entries = await dss.warehouse_search(search_query, limit=200)
        else:
            # Fetch across common domains to get broad coverage
            entries = []
            seen = set()
            for term in ["the", "that", "this", "with", "from", "have", "they", "what", "when", "were"]:
                batch = await dss.warehouse_search(term, limit=50)
                for e in batch:
                    eid = e.get('id')
                    if eid not in seen:
                        seen.add(eid)
                        entries.append(e)
                if len(entries) >= 200:
                    break
            entries.sort(key=lambda e: e.get('id', 0), reverse=True)

        if not entries:
            print("No entries found.")
            return

        selected = 0
        offset = 0
        scroll = 0
        viewing = None  # None = list view, dict = content view

        with RawTerm() as term:
            while True:
                _, height = get_terminal_size()

                if viewing is None:
                    render_list(entries, selected, offset, height, search_query)
                else:
                    render_content(viewing, scroll, height)

                ch = term.getch()

                if viewing is None:
                    # ── List view keybindings ──
                    if ch in ('q', 'ESC'):
                        break
                    elif ch in ('j', 'DOWN'):
                        selected = min(selected + 1, len(entries) - 1)
                    elif ch in ('k', 'UP'):
                        selected = max(selected - 1, 0)
                    elif ch == 'g':
                        ch2 = term.getch()
                        if ch2 == 'g':
                            selected = 0
                            offset = 0
                    elif ch == 'G':
                        selected = len(entries) - 1
                    elif ch in ('ENTER', '\r', '\n', 'l', 'RIGHT'):
                        # View content
                        entry_id = entries[selected].get('id')
                        if entry_id:
                            try:
                                async with DSSClient() as c:
                                    resp = await c.client.get(f"{dss.warehouse}/content/{entry_id}")
                                    resp.raise_for_status()
                                    viewing = resp.json()
                                    scroll = 0
                            except Exception as e:
                                viewing = {"title": "Error", "url": "", "markdown": str(e),
                                           "word_count": 0, "source_domain": "error"}
                    elif ch == '/':
                        # Search
                        clear()
                        sys.stdout.write("Search: ")
                        sys.stdout.flush()
                        term.old_set = termios.tcgetattr(term.fd)
                        tty.setcbreak(term.fd)
                        query = input()
                        tty.setraw(term.fd)
                        if query.strip():
                            entries = await dss.warehouse_search(query.strip(), limit=200)
                            selected = 0
                            offset = 0
                            search_query = query.strip()
                    elif ch == 'r':
                        entries = await dss.warehouse_search(search_query or "the", limit=200) if search_query else []
                        if not search_query:
                            seen = set()
                            entries = []
                            for term in ["the", "that", "this", "with", "from"]:
                                batch = await dss.warehouse_search(term, limit=50)
                                for e in batch:
                                    if e.get('id') not in seen:
                                        seen.add(e['id'])
                                        entries.append(e)
                            entries.sort(key=lambda e: e.get('id', 0), reverse=True)
                        selected = 0
                        offset = 0
                    elif ch in ('C-D',):
                        selected = min(selected + 10, len(entries) - 1)
                    elif ch in ('C-U',):
                        selected = max(selected - 10, 0)

                    # Keep selected in view
                    if selected < offset:
                        offset = selected
                    elif selected >= offset + height - 5:
                        offset = selected - height + 6

                else:
                    # ── Content view keybindings ──
                    content_lines = len(viewing.get('markdown', '').split('\n'))
                    visible_lines = height - 7

                    if ch in ('q', 'ESC'):
                        viewing = None
                        scroll = 0
                    elif ch in ('j', 'DOWN'):
                        scroll = min(scroll + 1, max(0, content_lines - visible_lines))
                    elif ch in ('k', 'UP'):
                        scroll = max(scroll - 1, 0)
                    elif ch == 'g':
                        ch2 = term.getch()
                        if ch2 == 'g':
                            scroll = 0
                    elif ch == 'G':
                        scroll = max(0, content_lines - visible_lines)
                    elif ch in ('C-D',):
                        scroll = min(scroll + visible_lines // 2, max(0, content_lines - visible_lines))
                    elif ch in ('C-U',):
                        scroll = max(scroll - visible_lines // 2, 0)
                    elif ch in ('Enter', '\r', '\n'):
                        viewing = None
                        scroll = 0
                    elif ch == 'C-C':
                        break

        clear()
        print("DSS Viewer closed.")


if __name__ == "__main__":
    asyncio.run(main())
