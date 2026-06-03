# DSS Python SDK — Use Cases

> Async Python SDK for DeepSearchStack (DSS): web crawling, multi-engine search,
> vector embeddings, knowledge warehouse, and LLM synthesis.

## Use Cases

### 1. Deep Research Pipeline

Search → scrape → synthesize — the full DSS pipeline from Python.

```python
import asyncio
from deepsearch import DeepSearchClient, crawl_sync

async def research_topic(topic: str):
    async with DeepSearchClient() as client:
        # Search across multiple providers
        search = await client.search(topic, max_results=10)
        print(f"Found {len(search.results)} sources")

        # Crawl top results for full content
        urls = [r["url"] for r in search.results[:3] if r.get("url")]
        for url in urls:
            result = crawl_sync(url)
            if result.success:
                print(f"Crawled {url}: {len(result.content)} chars")

        # LLM synthesis
        messages = [
            {"role": "system", "content": "Synthesize findings."},
            {"role": "user", "content": f"Summarize research on: {topic}"},
        ]
        response = await client.llm_complete(messages)
        return response

result = asyncio.run(research_topic("WebAssembly vs JavaScript"))
print(result)
```

### 2. Batch Content Ingestion

Crawl + store multiple URLs in parallel.

```python
from deepsearch import crawl_sync, search_sync

urls = [
    "https://www.rust-lang.org",
    "https://en.wikipedia.org/wiki/Rust_(programming_language)",
    "https://doc.rust-lang.org/book/",
]

for url in urls:
    result = crawl_sync(url)
    if result.success:
        print(f"✓ {url}: {result.word_count} words")
    else:
        print(f"✗ {url}: {result.error_message}")
```

### 3. Sync Wrapper for Scripts

Use from quick scripts without `async/await`.

```python
from deepsearch import SyncDeepSearchClient

with SyncDeepSearchClient() as client:
    # Crawl
    crawl = client.crawl("https://example.com")
    print(f"Crawled: {len(crawl.content)} chars")

    # Search
    search = client.search("Rust async", max_results=5)
    for r in search.results:
        print(f"  {r['title']}")

    # LLM
    response = client.llm_complete([
        {"role": "user", "content": "What is Rust?"},
    ], provider="deepseek-chat", max_tokens=100)
    print(f"LLM: {response[:200]}")
```

### 4. Convenience Functions (One-Liners)

```python
from deepsearch import crawl_sync, search_sync, llm_complete_sync

crawl_sync("https://example.com")                     # Crawl → CrawlResult
search_sync("Rust programming", max_results=3)          # Search → SearchResult
llm_complete_sync([{"role":"user","content":"Hi"}])    # LLM → str
```

## Test Commands

```bash
cd stacks/dss/sdk/python
pip install -r requirements.txt  # aiohttp, requests
python -c "from deepsearch import DeepSearchClient; print('OK')"

# Run examples
python examples/main.py
```

## Architecture Notes

- `DeepSearchClient` — async context manager (`async with`)
- `SyncDeepSearchClient` — sync wrapper for scripts and REPL
- `crawl_sync / search_sync / llm_complete_sync` — one-liner convenience functions
- Service URL resolution via port map (`_get_service_url` maps service→port)
- See `examples/main.py` for runnable usage
