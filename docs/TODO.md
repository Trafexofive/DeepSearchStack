# DeepSearchStack - Weekly Sprint Plan
**Objective:** Evolve from a functional prototype to a robust and performant application by implementing a RAG pipeline, caching, and a CI/CD foundation.

---

### **EPIC 1: Performance - Implement Caching Layer in `llm-gateway`**
- **Priority:** High
- **Est. Time:** 1 Day
- **Description:** Implement a Redis-based caching layer for the `/completion` endpoint to significantly reduce latency and external API calls for repeated queries.

- **Tasks:**
    - **`[ ]` 1.1: Infrastructure Setup**
        - `[ ]` 1.1.1: Add `redis` service to `docker-compose.yml` using the `redis:7-alpine` image.
        - `[ ]` 1.1.2: Expose port `6379` and configure a named volume `redis_data` for persistence.
        - `[ ]` 1.1.3: Add `redis` to the `depends_on` list for the `llm-gateway` service.
        - `[ ]` 1.1.4: Add `redis` to `llm_gateway/requirements.txt`.

    - **`[ ]` 1.2: Implement Cache Manager**
        - `[ ]` 1.2.1: Create a new file: `llm_gateway/cache_manager.py`.
        - `[ ]` 1.2.2: Inside `cache_manager.py`, create a `RedisClient` class to manage the connection pool to `redis:6379`.
        - `[ ]` 1.2.3: Implement `async def get_from_cache(key: str) -> Optional[str]:` which fetches and returns a value from Redis.
        - `[ ]` 1.2.4: Implement `async def set_to_cache(key: str, value: str, ttl: int):` which stores a value with a time-to-live (e.g., 86400 seconds for 24 hours).

    - **`[ ]` 1.3: Integrate Caching into API Gateway**
        - `[ ]` 1.3.1: In `llm_gateway/api_gateway.py`, import and instantiate the `RedisClient`.
        - `[ ]` 1.3.2: In the `/completion` endpoint, generate a unique cache key from the request payload (a SHA256 hash of the provider name + messages is ideal).
        - `[ ]` 1.3.3: Call `get_from_cache` at the beginning of the endpoint. If a result is found, deserialize it and return it immediately.
        - `[ ]` 1.3.4: After a successful response is received from an LLM provider, serialize the `CompletionResponse` object to a JSON string and call `set_to_cache`.

---

### **EPIC 2: AI - Implement RAG Pipeline**
- **Priority:** High
- **Est. Time:** 2 Days
- **Description:** Upgrade the `search-agent` from basic context-stuffing to a sophisticated Retrieval-Augmented Generation (RAG) pipeline, using the vector store to find and rank relevant information before synthesis.

- **Tasks:**
    - **`[ ]` 2.1: Build the Vector Store Microservice**
        - `[ ]` 2.1.1: Update `vector-store/Dockerfile` to install `fastapi`, `uvicorn`, `sentence-transformers`, `chromadb`, and `pydantic`.
        - `[ ]` 2.1.2: In `vector-store/main.py`, create a FastAPI application.
        - `[ ]` 2.1.3: On startup, initialize a ChromaDB client and load a sentence-transformer model (e.g., `all-MiniLM-L6-v2`).
        - `[ ]` 2.1.4: Implement `POST /embed` endpoint that takes a list of documents, generates embeddings, and upserts them into a ChromaDB collection. Each document should be stored with its URL and title as metadata.
        - `[ ]` 2.1.5: Implement `POST /query` endpoint that takes a query string, creates an embedding, and returns the top 5 most similar document chunks from the collection.
        - `[ ]` 2.1.6: Update the `vector-store` service in `docker-compose.yml` to expose a port (e.g., `8003`) and ensure it starts correctly.

    - **`[ ]` 2.2: Integrate RAG into the Search Agent**
        - `[ ]` 2.2.1: In `search-agent/main.py`, after `_fuse_and_deduplicate`, add a call to the vector store's `/embed` endpoint to index the new search results. (Note: This can be a fire-and-forget background task).
        - `[ ]` 2.2.2: **Crucially, modify the core logic:** Before building the LLM context, make an `httpx` call to the vector store's `/query` endpoint using the user's original query.
        - `[ ]` 2.2.3: Re-implement the context-building step. Instead of using all fused results, construct the context *only* from the top-k results returned by the `/query` endpoint.
        - `[ ]` 2.2.4: Ensure the citations in the final answer still correctly reference the original source URLs.

---

### **EPIC 3: DevOps - Establish CI Pipeline**
- **Priority:** Medium
- **Est. Time:** 1 Day
- **Description:** Create a GitHub Actions workflow to automate code quality checks and tests, ensuring the `main` branch remains stable and maintainable.

- **Tasks:**
    - **`[ ]` 3.1: Code Quality & Formatting**
        - `[ ]` 3.1.1: Create a `requirements-dev.txt` file in the root directory and add `ruff` and `black`.
        - `[ ]` 3.1.2: Create the workflow file: `.github/workflows/ci.yml`.
        - `[ ]` 3.1.3: Define a job named `lint-and-format` that triggers on `push` and `pull_request`.
        - `[ ]` 3.1.4: This job should check out the code, set up Python 3.11, install dev dependencies, and run `black --check .` and `ruff .`.

    - **`[ ]` 3.2: Automated Testing**
        - `[ ]` 3.2.1: Add a second job to `ci.yml` named `pytest`.
        - `[ ]` 3.2.2: This job should install all dependencies from `llm_gateway/requirements.txt`, `search-agent/requirements.txt`, and `testing/requirements.txt`.
        - `[ ]` 3.2.3: Add a step to run the command `pytest`.

    - **`[ ]` 3.3: Docker Build Verification**
        - `[ ]` 3.3.1: Add a third job named `verify-docker-builds`.
        - `[ ]` 3.3.2: This job only needs to run `docker compose build`. Its purpose is to fail the CI run if any Dockerfile is broken.

---

### **EPIC 4: Testing & Documentation**
- **Priority:** Medium
- **Est. Time:** 1 Day
- **Description:** Harden the `llm-gateway` by testing failure modes and update the project's `README.md` to reflect the new architecture and features.

- **Tasks:**
    - **`[ ]` 4.1: Expand Pytest Suite for Failure Cases**
        - `[ ]` 4.1.1: Add `pytest-httpx` to the dev requirements.
        - `[ ]` 4.1.2: In `testing/test_api.py`, write a new test `test_completion_fallback` that uses `httpx_mock` to simulate a 500 error from the primary provider and asserts that the response comes from a fallback provider.
        - `[ ]` 4.1.3: Write a test `test_completion_with_all_providers_failing` that mocks all providers to fail and asserts the API returns a `503` status code.

    - **`[ ]` 4.2: Update Project Documentation**
        - `[ ]` 4.2.1: In `README.md`, add a new `## Architecture` section.
        - `[ ]` 4.2.2: Use Mermaid.js syntax to draw an architecture diagram showing all services (including the new Redis and Vector Store).
        - `[ ]` 4.2.3: Update the `## Configuration` section to document the new environment variables: `ENABLE_GEMINI`, `ENABLE_GROQ`, and `OLLAMA_DEFAULT_MODEL`.
        - `[ ]` 4.2.4: Add a new section `## API Reference` with `curl` examples for the `/search`, `/completion`, and `/providers` endpoints.

---

### **EPIC 5.5: UX - Clean & Comprehensive E2E TUI (using the SDK)**
- **Priority:** Medium
- **Est. Time:** 2 Days
- **Description:** Build a **production-quality** terminal UI client that exercises the entire DeepSearchStack pipeline end-to-end through the Python SDK (`sdk/python/deepsearch.py`). This is a real developer tool, not a demo. It must logically call the SDK so it stays a true consumer of the public API surface — every gap in the SDK that the TUI needs filled is a real gap, and that's the point of building it. The user explicitly said "I dont play with my TUIs" — a half-day proof-of-concept is not acceptable; the bar is a real client that someone would actually use daily.

- **Tasks:**

    - **`[ ]` 5.5.1: Pick TUI framework**
        - `[ ]` 5.5.1.1: Evaluate: `textual` (async-native, CSS-like styling, mouse + keyboard), `prompt_toolkit` (lighter, prompt-style), `rich.live` (no widgets). Default: `textual` — production-grade and modern.
        - `[ ]` 5.5.1.2: Add to `sdk/python/requirements.txt`. Pin version.

    - **`[ ]` 5.5.2: SDK contract (do this FIRST, before any UI work)**
        - `[ ]` 5.5.2.1: Audit `sdk/python/deepsearch.py`. List every method the TUI needs:
            - `search(query, providers, max_results, timeout)` — non-streaming
            - `aggregate(query, providers, max_results)` — non-streaming
            - `synthesize(query, sources, llm_model, llm_provider, stream=True)` — streaming
            - `crawl(url, formats, forward_to_warehouse)` — single + batch
            - `llm_complete(messages, model, stream)` — direct LLM
            - `embed(documents, namespace)` — vector store
            - `warehouse_search(query, domain, limit)` — knowledge warehouse
            - `list_providers()` / `list_models()` — introspection
        - `[ ]` 5.5.2.2: Add **every** missing method. The TUI surfaces SDK gaps by demanding real methods.
        - `[ ]` 5.5.2.3: Every method gets a `*_stream()` async generator variant where applicable.
        - `[ ]` 5.5.2.4: Type hints everywhere. Runtime validation (pydantic) on the response side.
        - `[ ]` 5.5.2.5: Error envelope: every method returns `(result, error)` tuple, never raises on transport. TUI displays the error nicely.

    - **`[ ]` 5.5.3: TUI shell + navigation**
        - `[ ]` 5.5.3.1: Full-screen layout (Textual `App`).
        - `[ ]` 5.5.3.2: Bottom status bar: `stack: up | model: virtual/free-coder | session: abc123 | 12 results in 3.4s`.
        - `[ ]` 5.5.3.3: Top tabs: `Search | Synthesize | Crawl | LLM | Embed | Warehouse | Settings | Help`.
        - `[ ]` 5.5.3.4: Keyboard shortcuts everywhere. `?` opens help, `Ctrl+C` exits, `Ctrl+L` clears, `Tab` cycles focus, `Esc` cancels in-flight.
        - `[ ]` 5.5.3.5: Mouse support (clicking a tab, scrolling, selecting sources).
        - `[ ]` 5.5.3.6: Resize handling — panels reflow, no overflow.

    - **`[ ]` 5.5.4: Search tab (E2E the pipeline)**
        - `[ ]` 5.5.4.1: Multi-line input prompt (Enter inserts newline, Ctrl+Enter submits).
        - `[ ]` 5.5.4.2: Provider picker: checkbox list, defaults from `AGGREGATE_PROVIDERS` env. Visible count of selected.
        - `[ ]` 5.5.4.3: Submit → call `client.aggregate()`.
        - `[ ]` 5.5.4.4: Side panel: per-provider result list with status (hit count, latency, error if any).
        - `[ ]` 5.5.4.5: Main panel: auto-synthesize with `client.synthesize(stream=True)`. Render citations `[1]`, `[2]` as clickable. **Validate citations live** (call `validate_citations` from the SDK and show a warning banner if any [N] are out of range).
        - `[ ]` 5.5.4.6: Bottom panel: source list (URL, title, domain). `Enter` to open in browser, `y` to copy URL, `o` to open in `$BROWSER`.
        - `[ ]` 5.5.4.7: `/scrape` subcommand: select N sources, scrape, show markdown.

    - **`[ ]` 5.5.5: Synthesize tab (LLM-only)**
        - `[ ]` 5.5.5.1: Paste sources (JSON or text), prompt input.
        - `[ ]` 5.5.5.2: Model picker: dropdown of `client.list_models()`. **Default to `virtual/free-coder` cascade** (deepseek wallet is unreliable; opencode free is the safe default).
        - `[ ]` 5.5.5.3: Stream the synthesis. Show token/sec, TTFT (time to first token).
        - `[ ]` 5.5.5.4: Citation validation warning (same as Search tab).
        - `[ ]` 5.5.5.5: Re-run button (same prompt, different model — for A/B).

    - **`[ ]` 5.5.6: LLM tab (direct completion)**
        - `[ ]` 5.5.6.1: System prompt editor (multi-line).
        - `[ ]` 5.5.6.2: User message input.
        - `[ ]` 5.5.6.3: Model picker (same as Synthesize).
        - `[ ]` 5.5.6.4: Stream the completion. Show raw reasoning_content (if `deepseek-reasoner` style).
        - `[ ]` 5.5.6.5: Token count, latency. Save conversation to history.

    - **`[ ]` 5.5.7: Crawl tab**
        - `[ ]` 5.5.7.1: Single URL mode: progress indicator during crawl, show extracted markdown.
        - `[ ]` 5.5.7.2: Batch mode: paste N URLs, see per-URL status, download all as a single markdown bundle.
        - `[ ]` 5.5.7.3: Toggle `forward_to_warehouse`. Show warehouse confirmation.

    - **`[ ]` 5.5.8: Embed + Warehouse tabs**
        - `[ ]` 5.5.8.1: Embed: paste text or upload file, choose namespace, embed + show returned IDs + counts.
        - `[ ]` 5.5.8.2: Warehouse: query, domain filter, see results in a table (URL, title, snippet, ingested_at, word_count).

    - **`[ ]` 5.5.9: Settings tab**
        - `[ ]` 5.5.9.1: Override `DEEPSEEK_BASE_URL` (e.g., point at `localhost:8083` for stack).
        - `[ ]` 5.5.9.2: Set default model.
        - `[ ]` 5.5.9.3: Toggle streaming on/off.
        - `[ ]` 5.5.9.4: Set per-request timeout.
        - `[ ]` 5.5.9.5: Persist settings to `~/.config/deepsearch/tui.toml` (TOML, not JSON — hand-editable).
        - `[ ]` 5.5.9.6: Reload settings without restart.

    - **`[ ]` 5.5.10: History + session**
        - `[ ]` 5.5.10.1: Every query is logged to a session file (`~/.local/share/deepsearch/sessions/<id>.jsonl`).
        - `[ ]` 5.5.10.2: `/history` shows last 50 queries; `↑`/`↓` to recall.
        - `[ ]` 5.5.10.3: `/resume <id>` restores a session: replays queries into the chat panel.

    - **`[ ]` 5.5.11: Help + error UX**
        - `[ ]` 5.5.11.1: `?` opens full help (keyboard map, command list, examples).
        - `[ ]` 5.5.11.2: Errors are **never** silent. Every transport / parse / validation error shows a banner with the exception type and message + a hint. No bare tracebacks — they're logged, not displayed.
        - `[ ]` 5.5.11.3: Cancellation (Esc) cleans up the in-flight task. No zombie connections.

    - **`[ ]` 5.5.12: Containerize**
        - `[ ]` 5.5.12.1: `sdk/python/tui/Dockerfile` (python:3.12-slim + textual + SDK in editable mode).
        - `[ ]` 5.5.12.2: Add `tui` service to `infra/docker-compose.yml` — `tty: true`, `stdin_open: true`, no port, depends_on web-api healthy.
        - `[ ]` 5.5.12.3: `make tui` target → `docker compose -f infra/docker-compose.yml run --rm tui`.

    - **`[ ]` 5.5.13: Smoke tests + docs**
        - `[ ]` 5.5.13.1: Script `sdk/python/tui/test_e2e.sh` that runs the TUI against `make up`, exercises each tab, captures screenshots via `textual screenshot` (headless mode).
        - `[ ]` 5.5.13.2: Screenshots committed under `sdk/python/tui/screenshots/` for the README.
        - `[ ]` 5.5.13.3: New `sdk/python/README.md` section "TUI" with screenshots, install, quickstart.
        - `[ ]` 5.5.13.4: Final pass: every SDK method touched by the TUI is documented in the SDK README.

    - **`[ ]` 5.5.14: SDK gap report** (the whole point)
        - `[ ]` 5.5.14.1: As the TUI is built, every time you needed a method that didn't exist, file a follow-up in `docs/TODO.md` (or open a TODO under a new "SDK gaps" EPIC).
        - `[ ]` 5.5.14.2: At the end, the TUI should drive a meaningful chunk of new SDK work. If it didn't, the SDK is too thin.

### **EPIC 5: UI/UX - Integrate Chimera Frontend**
- **Priority:** Low
- **Est. Time:** 2 Days
- **Description:** Replace the default simple frontend with the more advanced `chimera-frontend` from the `ollama-api-server-docker` repository. This provides a path to full user, auth, and API key management.

- **Tasks:**
    - **`[ ]` 5.1: Replace Nginx with Traefik**
        - `[ ]` 5.1.1: Remove the `reverse-proxy` (Nginx) service from `infra/docker-compose.yml`.
        - `[ ]` 5.1.2: Add and configure the `traefik` service.
    - **`[ ]` 5.2: Integrate the Frontend Service**
        - `[ ]` 5.2.1: Remove the existing `frontend` and `web-api` services.
        - `[ ]` 5.2.2: Add the `chimera-frontend` service to `infra/docker-compose.yml`.
        - `[ ]` 5.2.3: Configure environment variables (`NEXTAUTH_SECRET`, etc.) in `.env.example`.
        - `[ ]` 5.2.4: Configure a persistent volume for the frontend's SQLite database.
    - **`[ ]` 5.3: Connect Frontend to DeepSearch Services**
        - `[ ]` 5.3.1: Modify the `chimera-frontend` application to make requests to the `search-agent` and `search-gateway`.
        - `[ ]` 5.3.2: Implement UI components to display synthesized search results and sources.
