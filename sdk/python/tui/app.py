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
    Button,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Log,
    Markdown,
    Select,
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

# TUI infrastructure (history + config persistence)
from config import CONFIG_PATH, TUIConfig, load_or_default
from history import DB_PATH as HISTORY_DB_PATH
from history import HistoryDB


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
            yield Button("Save synth", id="search-save-synth", variant="default")
            yield Button("Save sources", id="search-save-srcs", variant="default")
        with Horizontal(classes="results-area"):
            yield ListView(id="providers-list", classes="providers-list")
            yield Log(id="synthesis-view", classes="synthesis-view")
        yield Log(id="sources-view", classes="sources-view")

    @on(Button.Pressed, "#search-save-synth")
    def save_synth(self) -> None:
        _save_log_to_file(self.query_one("#synthesis-view", Log), prefix="synth", parent=self)

    @on(Button.Pressed, "#search-save-srcs")
    def save_srcs(self) -> None:
        _save_log_to_file(self.query_one("#sources-view", Log), prefix="sources", parent=self)

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
                if self.app.history:
                    self.app.history.add(
                        "search", query,
                        result_summary=f"{len(res.hits)} hits, {len(report['valid'])} valid cites",
                        elapsed_ms=int(elapsed * 1000),
                        model=self.app.default_model,
                    )
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
    .llm-toolbar {
        height: 3;
        padding: 0 1;
    }
    .llm-toolbar Select {
        width: 1fr;
    }
    .llm-toolbar Button {
        width: 14;
    }
    """

    def compose(self) -> ComposeResult:
        with Horizontal(classes="llm-toolbar"):
            # Model picker — populated in on_mount via list_models()
            yield Select([(self.app.default_model, self.app.default_model)],
                         id="llm-model", allow_blank=False, value=self.app.default_model)
            yield Button("Refresh", id="llm-refresh", variant="primary")
            yield Button("Save output", id="llm-save", variant="default")
        with Vertical(classes="llm-row"):
            yield Label("System prompt:")
            yield TextArea(id="llm-system", text="You are a helpful assistant.")
            yield Label("User message:")
            yield Input(placeholder="Hello", id="llm-user", classes="llm-input")
        yield Log(id="llm-output")

    def on_mount(self) -> None:
        # Populate the model picker in the background
        self.run_worker(self._populate_models, exclusive=True)

    async def _populate_models(self) -> None:
        try:
            async with AsyncDeepSearchClient(self.app.base_url) as client:
                models, err = await client.list_models()
            sel = self.query_one("#llm-model", Select)
            if err or not models:
                return
            options = [(m.id, m.id) for m in models]
            sel.set_options(options)
            # Keep current value if still present
            if self.app.default_model in [o[0] for o in options]:
                sel.value = self.app.default_model
        except Exception:
            pass

    @on(Select.Changed, "#llm-model")
    def model_changed(self, event: Select.Changed) -> None:
        # Update app-level default so subsequent LLM calls use it
        self.app.default_model = str(event.value)
        self.app._config.default_model = str(event.value)
        self.app.status_message = f"model → {event.value}"

    @on(Button.Pressed, "#llm-refresh")
    def refresh_models(self) -> None:
        self.run_worker(self._populate_models, exclusive=True)
        self.app.status_message = "refreshing model list..."

    @on(Button.Pressed, "#llm-save")
    def save_output(self) -> None:
        out = self.query_one("#llm-output", Log)
        _save_log_to_file(out, prefix="llm", parent=self)

    @on(Input.Submitted, "#llm-user")
    async def submit(self, event: Input.Submitted) -> None:
        user_msg = event.value.strip()
        if not user_msg:
            return
        out = self.query_one("#llm-output", Log)
        out.clear()
        out.write_line(f"[bold]Streaming:[/bold]\n")
        system = self.query_one("#llm-system", TextArea).text
        model = self.query_one("#llm-model", Select).value or self.app.default_model
        start = time.time()
        try:
            async with AsyncDeepSearchClient(self.app.base_url) as client:
                n_chunks = 0
                async for ch in client.llm_stream(
                    [{"role": "system", "content": system}, {"role": "user", "content": user_msg}],
                    model=model,
                ):
                    n_chunks += 1
                    out.write(ch)
                elapsed = time.time() - start
                out.write_line(f"\n\n[dim]{n_chunks} chunks in {elapsed:.2f}s[/dim]")
            if self.app.history:
                self.app.history.add(
                    "llm", user_msg,
                    result_summary=f"{n_chunks} chunks",
                    elapsed_ms=int((time.time() - start) * 1000),
                    model=model,
                )
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
    """Settings tab: edit config + save to ~/.config/deepsearch/tui.toml."""

    DEFAULT_CSS = """
    SettingsTab {
        padding: 1;
        layout: vertical;
    }
    SettingsTab Label.field {
        padding-top: 1;
        color: $accent;
    }
    SettingsTab Input {
        margin-bottom: 1;
    }
    SettingsTab #cfg-status {
        padding: 1;
        color: $success;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("Settings (edit + save to ~/.config/deepsearch/tui.toml)", classes="header")
        yield Static("")
        yield Label("Base URL", classes="field")
        yield Input(value=self.app.base_url, id="cfg-base-url")
        yield Label("LLM Base URL (blank = infer from base)", classes="field")
        yield Input(value=self.app.llm_base_url or "", id="cfg-llm-url", placeholder="(inferred)")
        yield Label("Default model", classes="field")
        yield Input(value=self.app.default_model, id="cfg-model")
        yield Label("Providers (comma-separated)", classes="field")
        yield Input(value=", ".join(self.app.default_providers), id="cfg-providers")
        yield Label("History limit", classes="field")
        yield Input(value=str(self.app._config.history_limit), id="cfg-history-limit")
        with Horizontal():
            yield Button("Save", id="cfg-save", variant="primary")
            yield Button("Reload", id="cfg-reload", variant="default")
            yield Button("Clear history", id="cfg-clear-history", variant="warning")
        yield Static("", id="cfg-status")
        yield Static(f"Config file: {CONFIG_PATH}", id="cfg-file")
        yield Static(f"History DB:  {HISTORY_DB_PATH}", id="cfg-db")

    @on(Button.Pressed, "#cfg-save")
    def save(self) -> None:
        cfg = self.app._config
        cfg.base_url = self.query_one("#cfg-base-url", Input).value.strip() or cfg.base_url
        cfg.llm_base_url = (self.query_one("#cfg-llm-url", Input).value.strip() or None)
        cfg.default_model = self.query_one("#cfg-model", Input).value.strip() or cfg.default_model
        provs = self.query_one("#cfg-providers", Input).value
        cfg.default_providers = [p.strip() for p in provs.split(",") if p.strip()]
        try:
            cfg.history_limit = int(self.query_one("#cfg-history-limit", Input).value.strip() or "200")
        except ValueError:
            cfg.history_limit = 200
        try:
            cfg.save()
            # Apply live
            self.app.base_url = cfg.base_url
            self.app.llm_base_url = cfg.resolved_llm_base_url()
            self.app.default_model = cfg.default_model
            self.app.default_providers = list(cfg.default_providers)
            self.query_one("#cfg-status", Static).update(f"saved {len(cfg.default_providers)} providers, model={cfg.default_model}")
            self.app.status_message = f"config saved → {CONFIG_PATH}"
        except Exception as e:
            self.query_one("#cfg-status", Static).update(f"save failed: {e}")

    @on(Button.Pressed, "#cfg-reload")
    def reload(self) -> None:
        cfg = TUIConfig.load()
        self.query_one("#cfg-base-url", Input).value = cfg.base_url
        self.query_one("#cfg-llm-url", Input).value = cfg.llm_base_url or ""
        self.query_one("#cfg-model", Input).value = cfg.default_model
        self.query_one("#cfg-providers", Input).value = ", ".join(cfg.default_providers)
        self.query_one("#cfg-history-limit", Input).value = str(cfg.history_limit)
        self.query_one("#cfg-status", Static).update("reloaded from disk")

    @on(Button.Pressed, "#cfg-clear-history")
    def clear_history(self) -> None:
        if self.app.history:
            n = self.app.history.clear()
            self.query_one("#cfg-status", Static).update(f"cleared {n} history events")
        else:
            self.query_one("#cfg-status", Static).update("history disabled")


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
        Binding("ctrl+s", "save_config", "Save cfg", show=True),
    ]

    status_message: reactive[str] = reactive("ready")

    def __init__(
        self,
        base_url: Optional[str] = None,
        llm_base_url: Optional[str] = None,
        default_model: Optional[str] = None,
        default_providers: Optional[list] = None,
        config: Optional[TUIConfig] = None,
    ) -> None:
        super().__init__()
        # Load config: explicit > file > env-var defaults
        self._config = config or load_or_default()
        # CLI/env overrides
        if base_url:
            self._config.base_url = base_url
        if llm_base_url:
            self._config.llm_base_url = llm_base_url
        if default_model:
            self._config.default_model = default_model
        if default_providers:
            self._config.default_providers = default_providers
        # Flatten onto the app for backward compat
        self.base_url = self._config.base_url
        self.llm_base_url = self._config.resolved_llm_base_url()
        self.default_model = self._config.default_model
        self.default_providers = list(self._config.default_providers)
        self.last_citation_report = None
        # History
        self.history: Optional[HistoryDB] = None
        if self._config.auto_save_history:
            try:
                self.history = HistoryDB(limit=self._config.history_limit)
            except Exception as e:
                self.status_message = f"history disabled: {e}"

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

    def action_save_config(self) -> None:
        """Persist current config to disk."""
        try:
            self._config.save()
            self.status_message = f"config saved → {CONFIG_PATH}"
        except Exception as e:
            self.status_message = f"config save failed: {e}"


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


# ─── Output export helper (referenced by Save buttons in each tab) ──────


def _save_log_to_file(log_widget, prefix: str = "output", parent=None) -> None:
    """Save a Log widget's content to ~/Documents/deepsearch-{prefix}-{ts}.md.

    Used by the per-tab Save buttons.
    """
    from datetime import datetime as _dt
    try:
        lines = []
        for ln in log_widget.lines:
            if isinstance(ln, str):
                lines.append(ln)
            else:
                try:
                    lines.append(str(ln))
                except Exception:
                    lines.append(repr(ln))
        body = "\n".join(lines)
        docs = Path(os.environ.get("XDG_DOCUMENTS_DIR", str(Path.home() / "Documents")))
        docs.mkdir(parents=True, exist_ok=True)
        ts = _dt.now().strftime("%Y%m%d-%H%M%S")
        out = docs / f"deepsearch-{prefix}-{ts}.md"
        out.write_text(body)
        if parent is not None:
            parent.app.status_message = f"saved → {out}"
    except Exception as e:
        if parent is not None:
            parent.app.status_message = f"save failed: {e}"
