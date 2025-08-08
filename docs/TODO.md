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
