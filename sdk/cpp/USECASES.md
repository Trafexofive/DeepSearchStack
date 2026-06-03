# DSS C++ SDK — Use Cases

> Single-header C++17 SDK for the DeepSearchStack (DSS): full-stack web research,
> crawling, semantic search, and cross-domain fact reconciliation.

## Use Cases

### 1. Automated Web Research Pipeline

Crawl → store → search → synthesize, all programmatically.

```cpp
#include "dss.hpp"

// 1. Crawl a page
dss::CrawlerClient crawler("http://crawler:8000");
auto page = crawler.crawl("https://en.wikipedia.org/wiki/Rust_%28programming_language%29");

// 2. Store in knowledge warehouse
dss::WarehouseClient wh("http://knowledge-warehouse:8009");
wh.ingest(page.url, page.markdown, page.content, page.title,
          page.author, page.published, page.language, page.word_count);

// 3. Full-text search
auto hits = wh.search("Rust borrow checker");
for (const auto& h : hits) {
    std::cout << h.title << " (" << h.snippet << ")\n";
}

// 4. Aggregate cross-domain research
dss::WebAPIClient api("http://web-api:8014");
auto research = api.aggregate("Rust async runtime comparison", 10);
std::cout << research.answer << "\n";
```

### 2. Real-Time Monitoring Agent

Watch a set of URLs, cache aggressively, only fetch fresh content on change.

```cpp
dss::CrawlerClient crawler("http://crawler:8000");

// Check cache stats before deciding to crawl
auto cache = crawler.cache_stats();
std::cout << cache.fresh_entries << "/" << cache.total_entries << " fresh\n";

// Crawl with cache bypass only when needed
auto result = crawler.crawl("https://news.ycombinator.com", "markdown",
                            15, /*bypass_cache=*/true);
```

### 3. Semantic RAG over Custom Documents

Embed documents → semantic search → LLM synthesis — no external vector DB needed.

```cpp
dss::VectorStoreClient vs("http://vector-store:8004");

// Embed documents
std::vector<dss::Document> docs = {
    {"", "WebAssembly (Wasm) defines a portable binary format...",
     R"({"source":"guide","topic":"wasm"})", ""},
    {"", "Rust compiles to WebAssembly via wasm-pack...",
     R"({"source":"tutorial","topic":"rust-wasm"})", ""},
};
vs.embed(docs, "dev-docs");

// Semantic query
auto results = vs.query("compile Rust to Wasm", 3);
// results.documents[0] contains ranked chunks with metadata
```

### 4. Multi-Provider Search Aggregation

Query multiple search engines through a single interface.

```cpp
dss::SearchGatewayClient sg("http://search-gateway:8002");

// Query across 3 providers
auto results = sg.search("Rust vs C++ performance",
    {"searxng", "wikipedia", "stackexchange"}, 10);

// Ranked, deduplicated, source-tagged results
for (const auto& r : results) {
    std::cout << "[" << r.source << "] " << r.title << "\n"
              << "  confidence: " << r.confidence << "\n";
}
```

### 5. Bulk URL Ingestion Pipeline

Ingest RSS feeds or URL lists at scale.

```cpp
dss::WebAPIClient api("http://web-api:8014");

// Ingest from RSS feed
// POST /api/ingest/feed — extracts article URLs, queues crawl
// (access via http_post_raw if no dedicated method yet)

// Ingest URLs in bulk
// POST /api/ingest/urls — up to 100 URLs, parallel crawl + warehouse store
```

### 6. Session-Based Research Assistant

Multi-turn research with session persistence.

```cpp
dss::DeepSearchClient ds("http://deepsearch:8001");

// Create a session
auto session = ds.create_session();
std::cout << "Session: " << session.session_id << "\n";

// Quick search within context
auto result = ds.quick_search("What is WebAssembly?", 5);
std::cout << "Answer: " << result.answer << "\n";

// List and manage sessions
auto sessions = ds.list_sessions();
ds.delete_session(session.session_id);
```

## Test Commands

```bash
# Build and run all tests
cd stacks/dss/sdk/cpp/build && cmake .. && cmake --build . && ./tests/dss-sdk-tests

# Build example
cd stacks/dss/sdk/cpp/examples && g++ -std=c++17 -I.. main.cpp -lcurl -o dss_example && ./dss_example
```

## Architecture Notes

- Each client connects to one DSS service by host:port
- Services resolve via Docker DNS when run inside the stack network
- All methods throw `std::runtime_error` on transport/protocol errors
- JSON parsing is minimal hand-rolled — no external dependency beyond libcurl
- See `tests/test_dss.cpp` for 48 integration tests covering all services
