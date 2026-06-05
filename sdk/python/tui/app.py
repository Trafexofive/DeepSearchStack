"""DeepSearchStack TUI — Textual app.

EPIC 5.5: comprehensive, real TUI that exercises the full pipeline
via the SDK. No toy.

Layout:
  ┌─ Tabs: Search | Synthesize | LLM | Crawl | Embed | Warehouse | Settings | Help ─┐
  │                                                                                  │
  │                          Active tab content                                     │
  │                                                                                  │
  ├─ Status: stack=up  model=virtual/free-coder  12 results in 3.4s ───────────────┤
  └─ Keys: ? Help  Tab Next  Ctrl+C Quit  Ctrl+L Clear  Esc Cancel ───────────────┘
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

# Make the SDK importable when this is run directly
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import (
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Log,
    Markdown,
    Static,
    TabbedContent,
    TabPane,
    TextArea,
)

from deepsearch import (
    AsyncDeepSearchClient,
    DeepSearchClient,
    SearchHit,
    SynthesizedChunk,
    validate_citations,
)


# ─── Tabs ──────────────────────────────────────────────────────────────


class SearchTab(Container):
    """Search tab: query input, provider list, streaming result + sources."""

    DEFAULT_CSS = """
    SearchTab {
        layout: vertical;
    }
    .search-row {
        height: auto;
        padding: 1;
    }
    .search-input {
        width: 1fr;
    }
    .search-btn {
        width: 16;
    }
    .results-area {
        height: 1fr;
    }
    .providers-list {
        width: 32;
        border: round $primary;
    }
    .synthesis-view {
        width: 1fr;
        border: round $secondary;
        padding: 1;
    }
    .sources-view {
        height: 12;
        border: round $accent;
        padding: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(classes="search-row"):
            yield Input(placeholder="What do you want to search?", id="query-input", classes="search-input")
            yield Static(" Search ", id="search-btn", classes="search-btn")
        with Horizontal(classes="results-area"):
            yield ListView(id="providers-list", classes="providers-list")
            yield Log(id="synthesis-view", classes="synthesis-view")
        yield Log(id="sources-view", classes="sources-view")

    def on_mount(self) -> None:
        providers = self.app.default_providers
        lv = self.query_one("#providers-list", ListView)
        for p in providers:
            lv.append(ListItem(Label(p), id=f"provider-{p}"))
        # pre-select first 4
        for i in range(min(4, len(providers))):
            lv.children[i].highlighted = True

    @on(Input.Submitted, "#query-input")
    async def submit_query(self, event: Input.Submitted) -> None:
        query = event.value.strip()
        if not query:
            return
        synth = self.query_one("#synthesis-view", Log)
        srcs = self.query_one("#sources-view", Log)
        synth.clear()
        srcs.clear()
        synth.write_line(f"[bold]Searching:[/bold] {query}")
        selected = []
        for item in self.query_one("#providers-list", ListView).children:
            if item.highlighted:
                # the Label's text is the provider name; the id is 'provider-{name}'
                name = item.id.removeprefix("provider-") if item.id else ""
                if name:
                    selected.append(name)
        if not selected:
            selected = self.app.default_providers
        start = time.time()
        try:
            async with AsyncDeepSearchClient(self.app.base_url) as client:
                res, err = await client.aggregate(query, providers=selected, max_results=5, timeout=15.0)
                if err:
                    synth.write_line(f"[red]aggregate failed:[/red] {err}")
                    return
                if not res.hits:
                    synth.write_line("[yellow]No results. Try a different query or providers.[/yellow]")
                    return
                for i, h in enumerate(res.hits, 1):
                    srcs.write_line(f"[{i}] {h.title} [dim]({h.source})[/dim]")
                    srcs.write_line(f"    [dim]{h.url}[/dim]")
                synth.write_line(f"\n[bold]Synthesis ({len(res.hits)} sources, {res.elapsed_seconds:.1f}s):[/bold]\n")
                sources_dicts = [
                    {"title": h.title, "url": h.url, "description": h.description, "source": h.source}
                    for h in res.hits
                ]
                full_text = ""
                warning = None
                async for ch in client.synthesize_stream(query, sources=sources_dicts):
                    if ch.warning:
                        warning = ch.warning
                    if ch.content and not ch.finished:
                        synth.write(ch.content)
                        full_text += ch.content
                synth.write_line("")
                if warning:
                    synth.write_line(f"\n[yellow]{warning.strip()}[/yellow]")
                report = validate_citations(full_text, len(res.hits))
                self.app.last_citation_report = report
                elapsed = time.time() - start
                self.app.status_message = f"{len(res.hits)} hits, {elapsed:.1f}s, {len(report['valid'])} valid citations"
        except Exception as e:
            synth.write_line(f"[red]error: {type(e).__name__}: {e}[/red]")


class SynthesizeTab(Container):
    """Synthesize tab: paste sources, prompt input, stream synthesis."""

    DEFAULT_CSS = """
    SynthesizeTab {
        layout: vertical;
    }
    .syn-row {
        height: auto;
        padding: 1;
    }
    .syn-input {
        width: 1fr;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(classes="syn-row"):
            yield Label("Sources (one per line, format: title | url | description):")
            yield TextArea(id="sources-textarea")
            yield Label("Prompt:")
            yield Input(placeholder="What should the LLM answer?", id="syn-prompt", classes="syn-input")
            yield Static(" Synthesize ", id="syn-btn")
        yield Log(id="syn-output")

    @on(Input.Submitted, "#syn-prompt")
    async def submit(self, event: Input.Submitted) -> None:
        prompt = event.value.strip()
        if not prompt:
            return
        out = self.query_one("#syn-output", Log)
        srcs_text = self.query_one("#sources-textarea", TextArea).text
        sources = []
        for line in srcs_text.splitlines():
            line = line.strip()
            if not line:
                continue
            parts = [p.strip() for p in line.split("|", 2)]
            if len(parts) < 3:
                parts = parts + [""] * (3 - len(parts))
            sources.append({"title": parts[0], "url": parts[1] or "https://example.com", "description": parts[2], "source": "user", "confidence": 1.0})
        if not sources:
            out.clear()
            out.write_line("[red]no sources — add at least one line above[/red]")
            return
        out.clear()
        out.write_line(f"[bold]Synthesizing ({len(sources)} sources):[/bold]\n")
        try:
            async with AsyncDeepSearchClient(self.app.base_url) as client:
                full_text = ""
                async for ch in client.synthesize_stream(prompt, sources=sources):
                    if ch.warning:
                        out.write_line(f"\n[yellow]{ch.warning.strip()}[/yellow]")
                    if ch.content and not ch.finished:
                        out.write(ch.content)
                        full_text += ch.content
                out.write_line("")
                report = validate_citations(full_text, len(sources))
                if report["invalid"]:
                    out.write_line(f"\n[yellow]Citation check: {len(report['invalid'])} invalid: {report['invalid_strs']}[/yellow]")
        except Exception as e:
            out.write_line(f"[red]error: {type(e).__name__}: {e}[/red]")


class LLMTab(Container):
    """LLM tab: direct completion, system prompt + user input + stream."""

    DEFAULT_CSS = """
    LLMTab {
        layout: vertical;
    }
    .llm-row {
        height: auto;
        padding: 1;
    }
    """

    def compose(self) -> ComposeResult:
        with Vertical(classes="llm-row"):
            yield Label("System prompt:")
            yield TextArea(id="llm-system", text="You are a helpful assistant.")
            yield Label("User message:")
            yield Input(placeholder="Hello", id="llm-user", classes="llm-input")
        yield Log(id="llm-output")

    @on(Input.Submitted, "#llm-user")
    async def submit(self, event: Input.Submitted) -> None:
        user_msg = event.value.strip()
        if not user_msg:
            return
        out = self.query_one("#llm-output", Log)
        out.clear()
        out.write_line(f"[bold]Streaming:[/bold]\n")
        system = self.query_one("#llm-system", TextArea).text
        try:
            async with AsyncDeepSearchClient(self.app.base_url) as client:
                start = time.time()
                n_chunks = 0
                async for ch in client.llm_stream(
                    [{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
                    model=self.app.default_model,
                ):
                    n_chunks += 1
                    out.write(ch)
                elapsed = time.time() - start
                out.write_line(f"\n\n[dim]{n_chunks} chunks in {elapsed:.2f}s[/dim]")
        except Exception as e:
            out.write_line(f"[red]error: {type(e).__name__}: {e}[/red]")


class CrawlTab(Container):
    """Crawl tab: single URL, shows markdown."""

    DEFAULT_CSS = """
    CrawlTab {
        layout: vertical;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Input(placeholder="https://example.com", id="crawl-url")
            yield Static(" Crawl ", id="crawl-btn")
        yield Log(id="crawl-output")

    @on(Input.Submitted, "#crawl-url")
    async def submit(self, event: Input.Submitted) -> None:
        url = event.value.strip()
        if not url:
            return
        out = self.query_one("#crawl-output", Log)
        out.clear()
        out.write_line(f"[bold]Crawling:[/bold] {url}")
        try:
            async with AsyncDeepSearchClient(self.app.base_url) as client:
                res, err = await client.crawl(url, timeout=30)
                if err:
                    out.write_line(f"[red]{err}[/red]")
                    return
                if not res.success:
                    out.write_line(f"[red]crawl failed: {res.error_message}[/red]")
                    return
                out.write_line(f"[dim]title: {res.title}[/dim]")
                out.write_line(f"[dim]words: {res.word_count}[/dim]\n")
                lines = (res.markdown or res.content).splitlines()
                for line in lines[:100]:
                    out.write_line(line)
                if len(lines) > 100:
                    out.write_line(f"\n[dim]... {len(lines) - 100} more lines[/dim]")
        except Exception as e:
            out.write_line(f"[red]error: {type(e).__name__}: {e}[/red]")


class EmbedTab(Container):
    """Embed tab: text input + namespace, then embed + query."""

    DEFAULT_CSS = """
    EmbedTab {
        layout: vertical;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Input(placeholder="namespace", id="embed-ns", value="default")
            yield Input(placeholder="text to embed", id="embed-text")
            yield Static(" Embed ", id="embed-btn")
        with Horizontal():
            yield Input(placeholder="query", id="embed-query")
            yield Static(" Query ", id="embed-query-btn")
        yield Log(id="embed-output")

    @on(Input.Submitted, "#embed-text")
    async def submit_embed(self, event: Input.Submitted) -> None:
        ns = self.query_one("#embed-ns", Input).value.strip() or "default"
        text = self.query_one("#embed-text", Input).value.strip()
        if not text:
            return
        out = self.query_one("#embed-output", Log)
        out.clear()
        out.write_line(f"[bold]Embedding into {ns!r}:[/bold] {text[:60]!r}")
        try:
            async with AsyncDeepSearchClient(self.app.base_url) as client:
                res, err = await client.embed([{"text": text, "id": f"tui-{int(time.time())}"}], namespace=ns)
                if err:
                    out.write_line(f"[red]{err}[/red]")
                else:
                    out.write_line(f"[green]embedded:[/green] count={res.count}")
        except Exception as e:
            out.write_line(f"[red]error: {type(e).__name__}: {e}[/red]")

    @on(Input.Submitted, "#embed-query")
    async def submit_query(self, event: Input.Submitted) -> None:
        ns = self.query_one("#embed-ns", Input).value.strip() or "default"
        q = self.query_one("#embed-query", Input).value.strip()
        if not q:
            return
        out = self.query_one("#embed-output", Log)
        out.write_line(f"\n[bold]Querying {ns!r}:[/bold] {q!r}")
        try:
            async with AsyncDeepSearchClient(self.app.base_url) as client:
                res, err = await client.vector_query(q, namespace=ns, top_k=3)
                if err:
                    out.write_line(f"[red]{err}[/red]")
                else:
                    ids = (res.get("ids") or [[]])[0]
                    docs = (res.get("documents") or [[]])[0]
                    dists = (res.get("distances") or [[]])[0]
                    for i, (id_, doc, dist) in enumerate(zip(ids, docs, dists), 1):
                        out.write_line(f"  {i}. [dim](dist={dist:.3f})[/dim] {id_}: {doc[:80]!r}")
        except Exception as e:
            out.write_line(f"[red]error: {type(e).__name__}: {e}[/red]")


class WarehouseTab(Container):
    """Warehouse tab: search the persisted knowledge store."""

    DEFAULT_CSS = """
    WarehouseTab {
        layout: vertical;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal():
            yield Input(placeholder="search the warehouse", id="wh-query")
            yield Input(placeholder="domain filter (optional)", id="wh-domain")
            yield Static(" Search ", id="wh-btn")
        yield Log(id="wh-output")

    @on(Input.Submitted, "#wh-query")
    async def submit(self, event: Input.Submitted) -> None:
        q = self.query_one("#wh-query", Input).value.strip()
        if not q:
            return
        domain = self.query_one("#wh-domain", Input).value.strip() or None
        out = self.query_one("#wh-output", Log)
        out.clear()
        out.write_line(f"[bold]Warehouse search:[/bold] {q!r} (domain={domain!r})")
        try:
            async with AsyncDeepSearchClient(self.app.base_url) as client:
                hits, err = await client.warehouse_search(q, domain=domain, limit=10)
                if err:
                    out.write_line(f"[red]{err}[/red]")
                    return
                if not hits:
                    out.write_line("[yellow]no hits[/yellow]")
                    return
                for i, h in enumerate(hits, 1):
                    out.write_line(f"{i}. {h.title or '?'} [dim]({h.source_domain})[/dim]")
                    out.write_line(f"   [dim]{h.url}[/dim]")
                    if h.snippet:
                        out.write_line(f"   {h.snippet[:100]}...")
        except Exception as e:
            out.write_line(f"[red]error: {type(e).__name__}: {e}[/red]")


class SettingsTab(Container):
    """Settings tab: show current config (read-only for now)."""

    DEFAULT_CSS = """
    SettingsTab {
        padding: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("Current settings (read-only):", classes="header")
        yield Static("")
        yield Static(f"Base URL:  {self.app.base_url}")
        yield Static(f"LLM URL:   {self.app.llm_base_url}")
        yield Static(f"Model:     {self.app.default_model}")
        yield Static(f"Providers: {', '.join(self.app.default_providers)}")
        yield Static("")
        yield Static("Set via env vars: DEEPSEEK_BASE_URL, DEEPSEEK_LLM_URL, DEEPSEAK_MODEL, AGGREGATE_PROVIDERS")
        yield Static("")
        yield Static("Settings file: ~/.config/deepsearch/tui.toml (TODO 5.5.9)")


class HelpTab(Container):
    """Help tab: keyboard shortcuts + quick reference."""

    DEFAULT_CSS = """
    HelpTab {
        padding: 1;
    }
    """

    HELP_TEXT = """
# DeepSearchStack TUI — Help

## Keyboard
  `?`           — this help
  `Tab`         — next tab
  `Shift+Tab`   — previous tab
  `Ctrl+C`      — quit
  `Ctrl+L`      — clear current output
  `Esc`         — cancel in-flight request (best-effort)
  `↑` / `↓`     — navigate lists (providers, etc.)

## Tabs
  **Search**       — multi-provider aggregate + streaming synthesis
  **Synthesize**   — paste sources, prompt, stream
  **LLM**          — direct completion (system + user)
  **Crawl**        — single URL, shows markdown
  **Embed**        — embed text + vector query
  **Warehouse**    — search the knowledge store
  **Settings**     — current config
  **Help**         — this page

## Quickstart
  1. Make sure the stack is up:  `make up STACK=full`
  2. Open the **Search** tab (it's the default)
  3. Type a query, press Enter
  4. Watch the right panel stream the synthesis
  5. The bottom panel shows the sources

## Citation validation
  When the LLM produces [N] citations, the TUI validates them
  against the source list. If the LLM hallucinates a citation
  (e.g. [7] when only 3 sources exist), a warning appears at
  the end of the synthesis.

## Streaming
  Every LLM call streams. Token-by-token rendering. You can see
  reasoning_content too (when the model is deepseek-reasoner or
  similar).
"""

    def compose(self) -> ComposeResult:
        yield Markdown(self.HELP_TEXT)


# ─── Main App ──────────────────────────────────────────────────────────


class DeepSearchTUI(App):
    """DeepSearchStack TUI."""

    CSS = """
    Screen {
        layout: vertical;
    }
    #status-bar {
        dock: bottom;
        height: 1;
        background: $primary;
        color: $text;
        padding: 0 2;
    }
    """

    BINDINGS = [
        Binding("ctrl+c", "quit", "Quit", show=True),
        Binding("ctrl+l", "clear_output", "Clear", show=True),
        Binding("question_mark", "show_help", "Help", show=True),
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    status_message: reactive[str] = reactive("ready")

    def __init__(
        self,
        base_url: str = "http://localhost:8083",
        llm_base_url: Optional[str] = None,
        default_model: str = "virtual/free-coder",
        default_providers: Optional[list] = None,
    ) -> None:
        super().__init__()
        self.base_url = base_url
        self.llm_base_url = llm_base_url or base_url.rsplit(":", 1)[0] + ":8005"
        self.default_model = default_model
        self.default_providers = default_providers or [
            "searxng", "wikipedia", "github", "hackernews",
        ]
        self.last_citation_report = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="tab-search"):
            with TabPane("Search", id="tab-search"):
                yield SearchTab()
            with TabPane("Synthesize", id="tab-syn"):
                yield SynthesizeTab()
            with TabPane("LLM", id="tab-llm"):
                yield LLMTab()
            with TabPane("Crawl", id="tab-crawl"):
                yield CrawlTab()
            with TabPane("Embed", id="tab-embed"):
                yield EmbedTab()
            with TabPane("Warehouse", id="tab-warehouse"):
                yield WarehouseTab()
            with TabPane("Settings", id="tab-settings"):
                yield SettingsTab()
            with TabPane("Help", id="tab-help"):
                yield HelpTab()
        yield Static(f"  {self.status_message}  |  model={self.default_model}  |  base={self.base_url}", id="status-bar")
        yield Footer()

    def watch_status_message(self, new: str) -> None:
        try:
            bar = self.query_one("#status-bar", Static)
            bar.update(f"  {new}  |  model={self.default_model}  |  base={self.base_url}")
        except Exception:
            pass

    def action_clear_output(self) -> None:
        # Clear the active tab's output (best effort)
        active = self.query(".tabPane--active")
        if active is None:
            return
        for log in active.query(Log):
            log.clear()

    def action_show_help(self) -> None:
        # Switch to the Help tab
        tabs = self.query_one(TabbedContent)
        tabs.active = "tab-help"

    def action_cancel(self) -> None:
        # Best-effort: cancel in-flight workers
        for w in self.workers:
            w.cancel()


# ─── Entry point ──────────────────────────────────────────────────────


def main() -> int:
    """CLI entry: parse args, run the TUI."""
    import argparse
    p = argparse.ArgumentParser(description="DeepSearchStack TUI")
    p.add_argument("--base-url", default=os.environ.get("DEEPSEARCH_BASE_URL", "http://localhost:8083"))
    p.add_argument("--llm-base-url", default=os.environ.get("DEEPSEARCH_LLM_URL"))
    p.add_argument("--model", default=os.environ.get("DEEPSEARCH_MODEL", "virtual/free-coder"))
    p.add_argument("--providers", default=os.environ.get("AGGREGATE_PROVIDERS", "searxng,wikipedia,github,hackernews"))
    args = p.parse_args()

    providers = [p.strip() for p in args.providers.split(",") if p.strip()]

    app = DeepSearchTUI(
        base_url=args.base_url,
        llm_base_url=args.llm_base_url,
        default_model=args.model,
        default_providers=providers,
    )
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
