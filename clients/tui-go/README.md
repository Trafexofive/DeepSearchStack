# dss-tui — DeepSearchStack TUI (Go / Bubble Tea)

Single static Go binary. Talks to the DSS stack via nginx (`/dss/...`).
No Python deps, no SDK.

## Tabs

- **Agent** — the research agent. Query → aggregate across providers (with scraping + reconciliation) → stream cited synthesis from the search-agent.
- **Search** — `POST /dss/api/aggregate` raw. Source breakdown by real origin, meta-search channels labeled `via:searxng` / `via:yacy`. Consensus claims with quality markers.
- **Crawl** — `POST /dss/crawl/crawl` with `render_mode={auto,fast,browser,ocr}` and bypass-cache toggle. Shows `extraction_method`, `escalations`, blocked status, and a data-quality verdict on the lead 250 chars.
- **Warehouse** — list / FTS5 search / open-by-id / stats. Every row shows a clean-lead verdict from the real markdown lead (post-fix `/list` returns actual content, not the title).
- **Render** — direct `POST /dss/render/render` to the browser-renderer. Shows trafilatura-extracted article text + RapidOCR text side-by-side.
- **Models** — inference-gateway catalog.
- **Providers** — search-gateway registry (meta-search channels labeled).

## Build / Run

```
make build         # → ./dss-tui
make run           # build + run, base=http://localhost:8083
DSS_BASE_URL=http://192.168.1.10:8083 ./dss-tui
./dss-tui -base http://nas.local:8083
```

## Tests

```
make test          # live integration tests against $DSS_BASE_URL
```

Tests skip cleanly when the stack is down (CI-safe). When up they verify:
health, models catalog, providers list, warehouse list/stats, aggregate
attribution (must surface ≥2 distinct sources — guard against searxng-only
regression), crawl extraction telemetry on Hacker News.

## Keys

- `Tab` / `Shift+Tab` — cycle tabs (only when not typing in an input)
- `Enter` — submit on input tabs
- `ctrl+r` — reset / refresh on most tabs
- `ctrl+m` — cycle mode (Crawl: render mode; Warehouse: action mode)
- `ctrl+b` — toggle bypass-cache (Crawl)
- `ctrl+o` — toggle OCR (Render)
- `ctrl+f` — toggle full-page screenshot (Render)
- `q` / `ctrl+c` — quit

## File layout

```
clients/tui-go/
├── main.go            # root model, tab routing, keymap
├── client.go          # HTTP client: Aggregate, SynthesizeStream (SSE),
│                      #             Crawl, Render, WarehouseList/Search/Get/Stats,
│                      #             Models, Providers, Health
├── client_test.go     # live integration tests
├── styles.go          # lipgloss palette + reusable styles
├── tab_agent.go       # Agent (the headline tab)
├── tab_search.go      # Aggregate (raw)
├── tab_crawl.go       # Crawl + render_mode
├── tab_warehouse.go   # list / search / open / stats
├── tab_render.go      # browser-renderer direct
├── tab_models.go      # inference catalog
└── tab_providers.go   # search-gateway providers
```
