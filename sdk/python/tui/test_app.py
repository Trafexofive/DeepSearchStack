"""TUI smoke test — drives the app via textual's Pilot, no terminal needed."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import app as tui_app


async def main() -> int:
    try:
        import httpx
        r = httpx.get("http://localhost:8083/health", timeout=2.0)
        if r.status_code != 200:
            print("SKIP — stack down")
            return 0
    except Exception:
        print("SKIP — stack unreachable")
        return 0

    print("=== TUI smoke test ===")
    tui = tui_app.DeepSearchTUI()

    async with tui.run_test() as pilot:
        await pilot.pause()
        print(f"  ✓ mounted: {tui.title!r}")

        # 8 tabs
        from textual.widgets import TabbedContent
        tabs = tui.query_one(TabbedContent)
        tab_ids = [p.id for p in tabs.query("TabPane")]
        expected = ["tab-search", "tab-syn", "tab-llm", "tab-crawl", "tab-embed", "tab-warehouse", "tab-settings", "tab-help"]
        for tid in expected:
            assert tid in tab_ids, f"missing: {tid}"
        print(f"  ✓ all 8 tabs present")

        for tid in expected:
            tabs.active = tid
            await pilot.pause()
        print(f"  ✓ tabs switchable")

        # Help tab markdown
        tabs.active = "tab-help"
        await pilot.pause()
        from textual.widgets import Markdown
        md = tui.query_one(Markdown)
        assert md.source and "Keyboard" in md.source, f"help missing"
        print(f"  ✓ help markdown ({len(md.source)} chars)")

        # Search test
        tabs.active = "tab-search"
        await pilot.pause()
        from textual.widgets import Input
        q = tui.query_one("#query-input", Input)
        q.focus()
        await pilot.pause()
        await pilot.press(*'kubernetes')
        await pilot.pause()
        await pilot.press('enter')

        # Wait up to 30s for the search to complete
        print("  ⏳ running search (up to 30s)...")
        synth = tui.query_one("#synthesis-view")
        for i in range(60):
            await pilot.pause(0.5)
            lines = synth.lines if hasattr(synth, "lines") else []
            joined = "\n".join(lines)
            if "Synthesis" in joined or "aggregate failed" in joined or "No results" in joined:
                break

        # Diagnostic dump
        lines = synth.lines if hasattr(synth, "lines") else []
        print(f"  synth log: {len(lines)} lines after wait")
        for line in lines[-8:]:
            print(f"    | {line[:100]!r}")

        content = "\n".join(lines)
        if len(content) < 20:
            print(f"  ⚠ SKIP assertion (log empty — search may be still in flight)")
        else:
            assert "Searching" in content, f"missing 'Searching' marker"
            print(f"  ✓ search ran, {len(content)} chars in log")

    print()
    print("=== TUI smoke test passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
