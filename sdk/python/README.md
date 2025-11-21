# DeepSearchStack Python SDK

Python SDK for interacting with DeepSearchStack services including:
- Web crawling and content extraction
- Search aggregation
- LLM completions

## Installation

```bash
pip install deepsearch-sdk
```

## Quick Start

```python
from deepsearch import DeepSearchClient

# Async usage (recommended)
async with DeepSearchClient(base_url="http://localhost:8080") as client:
    # Crawl a webpage
    result = await client.crawl("https://example.com", formats=["markdown"])
    print(result.content)
    
    # Search for information
    results = await client.search("What is AI?", max_results=5)
    print(results.results)
    
    # Get LLM completion
    messages = [{"role": "user", "content": "Explain quantum computing"}]
    response = await client.llm_complete(messages)
    print(response)
```

## Synchronous Usage

```python
from deepsearch import SyncDeepSearchClient

# Sync usage for simpler scripts
with SyncDeepSearchClient(base_url="http://localhost:8080") as client:
    result = client.crawl("https://example.com", formats=["markdown"])
    print(result.content)
    
    results = client.search("What is AI?")
    print(results.results)
```

## Convenience Functions

```python
from deepsearch import crawl_sync, search_sync, llm_complete_sync

# Direct function calls
content = crawl_sync("https://example.com")
results = search_sync("What is AI?")
response = llm_complete_sync([{"role": "user", "content": "Explain AI"}])
```

## API Reference

### DeepSearchClient

Main async client for all DeepSearchStack services.

#### crawl(url, formats=["markdown"], extract_metadata=True, timeout=10)
Crawls a URL and converts to specified format.

Parameters:
- `url`: URL to crawl
- `formats`: List of output formats ("markdown", "structured_text", etc.)
- `extract_metadata`: Extract metadata from page
- `timeout`: Request timeout in seconds

Returns: `CrawlResult` object

#### search(query, max_results=10, search_depth="basic", include_domains=None, exclude_domains=None)
Performs a search using the search gateway.

Parameters:
- `query`: Search query string
- `max_results`: Maximum number of results to return
- `search_depth`: Search depth ("basic", "advanced", "deep")
- `include_domains`: Domains to specifically include
- `exclude_domains`: Domains to exclude

Returns: `SearchResult` object

#### llm_complete(messages, provider="gemini", temperature=0.7, max_tokens=500)
Gets completion from the LLM gateway.

Parameters:
- `messages`: List of messages in OpenAI format
- `provider`: LLM provider to use
- `temperature`: Generation temperature
- `max_tokens`: Maximum tokens to generate

Returns: Generated text string

### SyncDeepSearchClient
Synchronous wrapper around the async client.

### Convenience Functions
- `crawl_sync()` - Synchronous crawl
- `search_sync()` - Synchronous search  
- `llm_complete_sync()` - Synchronous LLM completion

## Error Handling

All methods raise appropriate exceptions on error. Wrap calls in try/except blocks to handle errors gracefully.

## Configuration

The SDK connects to services running on ports:
- Crawler: 8004
- Search Gateway: 8003  
- LLM Gateway: 8081
- DeepSearch: 8001

Update the base_url parameter accordingly if your services run on different addresses.