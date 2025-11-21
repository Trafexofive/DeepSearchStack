"""
Example usage of the DeepSearchStack Python SDK
"""

import asyncio
from sdk.python.deepsearch import DeepSearchClient, SyncDeepSearchClient, crawl_sync, search_sync


async def example_async():
    """Example of using the async client"""
    async with DeepSearchClient(base_url="http://localhost:8080") as client:
        print("🔍 Crawling example.com...")
        crawl_result = await client.crawl(
            "https://example.com", 
            formats=["markdown"]
        )
        print(f"✅ Crawled successfully: {crawl_result.success}")
        print(f"📄 Content preview: {crawl_result.content[:100]}...\n")
        
        print("🔍 Searching for 'AI trends'...")
        search_result = await client.search(
            "What are the latest trends in AI?",
            max_results=3
        )
        print(f"✅ Found {len(search_result.results)} results")
        print(f"🔗 Sources: {search_result.sources[:3]}\n")
        
        # Example of LLM usage (if available)
        # Uncomment when your LLM gateway is properly configured:
        # messages = [{"role": "user", "content": "Summarize the importance of AI in 2025"}]
        # llm_response = await client.llm_complete(messages)
        # print(f"🤖 LLM Response: {llm_response}")


def example_sync():
    """Example of using the sync client"""
    with SyncDeepSearchClient(base_url="http://localhost:8080") as client:
        print("🔍 Sync crawling example.com...")
        crawl_result = client.crawl("https://example.com", formats=["markdown"])
        print(f"✅ Crawled successfully: {crawl_result.success}")
        print(f"📄 Content preview: {crawl_result.content[:100]}...\n")

        print("🔍 Sync searching for 'quantum computing'...")
        search_result = client.search("What is quantum computing?", max_results=2)
        print(f"✅ Found {len(search_result.results)} results")
        print(f"🔗 Sources: {search_result.sources[:2]}\n")


def example_convenience_functions():
    """Example of using convenience functions"""
    print("🔍 Using convenience function to crawl...")
    crawl_result = crawl_sync("https://httpbin.org/html")
    print(f"✅ Crawled successfully: {crawl_result.success}")
    print(f"📄 Content length: {len(crawl_result.content)} characters\n")

    print("🔍 Using convenience function to search...")
    search_result = search_sync("renewable energy benefits", max_results=2)
    print(f"✅ Found {len(search_result.results)} results")
    print(f"🔍 First result preview: {search_result.results[0] if search_result.results else 'None'}")


if __name__ == "__main__":
    print("🚀 DeepSearchStack Python SDK Examples")
    print("="*50)

    print("\n1. Async Example:")
    print("-" * 20)
    asyncio.run(example_async())

    print("\n2. Sync Example:")
    print("-" * 20)
    example_sync()

    print("\n3. Convenience Functions Example:")
    print("-" * 35)
    example_convenience_functions()

    print("\n✅ All examples completed successfully!")