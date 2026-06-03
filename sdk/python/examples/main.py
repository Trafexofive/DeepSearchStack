"""
DSS Python SDK — Usage Examples

Usage:
    # With DSS services running:
    python main.py

    # Test with connection errors (if services are down):
    python main.py
"""

import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from deepsearch import DeepSearchClient, SyncDeepSearchClient


async def example_web_api():
    """Aggregate search via web-api (port 8014)."""
    print("\n=== WebAPI (aggregate search) ===")
    async with DeepSearchClient(base_url="http://localhost:8080") as client:
        result = await client.search("What is WebAssembly?", max_results=5)
        print(f"Query: {result.query}")
        print(f"Sources: {len(result.results)}")
        for r in result.results[:3]:
            print(f"  - {r.get('title', 'N/A')} ({r.get('source', '?')})")


async def example_crawl():
    """Crawl a URL via crawler service."""
    print("\n=== Crawler ===")
    from deepsearch import crawl_sync
    result = crawl_sync("https://example.com")
    if result.success:
        print(f"Crawled: {result.url}")
        print(f"Content length: {len(result.content)} chars")
    else:
        print(f"Crawl failed: {result.error_message}")


async def example_llm():
    """LLM completion via inference gateway."""
    print("\n=== LLM Completion ===")
    from deepsearch import llm_complete_sync

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is Rust?"},
    ]
    try:
        response = llm_complete_sync(messages, provider="deepseek-chat", max_tokens=100)
        print(f"Response: {response[:200]}...")
    except Exception as e:
        print(f"LLM error (expected if service down): {e}")


def example_sync_wrapper():
    """Synchronous usage with SyncDeepSearchClient."""
    print("\n=== Sync Client ===")
    with SyncDeepSearchClient(base_url="http://localhost:8080") as client:
        # Search
        result = client.search("Rust programming", max_results=3)
        print(f"Sync search: {len(result.results)} results")

        # Crawl
        crawl_result = client.crawl("https://www.rust-lang.org")
        if crawl_result.success:
            print(f"Sync crawl: {crawl_result.url}, {crawl_result.word_count} words")


async def main():
    print("DSS Python SDK Examples")
    print("=======================")
    print("Note: Run with DSS services up (make up core + stacks/dss)")
    print()

    await example_web_api()
    await example_crawl()
    await example_llm()
    example_sync_wrapper()

    print("\nDone.")


if __name__ == "__main__":
    asyncio.run(main())
