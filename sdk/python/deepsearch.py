"""
DeepSearchStack - Python SDK
Easy-to-use client for interacting with DeepSearchStack services
"""

import asyncio
import json
from typing import Dict, List, Optional, Union, Any
from dataclasses import dataclass
import aiohttp
import requests


@dataclass
class CrawlResult:
    """Result from a crawl operation"""
    url: str
    content: str
    extracted_data: Optional[Dict] = None
    success: bool = True
    error_message: Optional[str] = None


@dataclass
class SearchResult:
    """Result from a search operation"""
    query: str
    results: List[Dict]
    sources: List[str]
    timestamp: str


class DeepSearchClient:
    """
    Comprehensive Python client for DeepSearchStack services
    
    Usage:
    ```python
    from deepsearch_sdk import DeepSearchClient
    
    # Initialize client
    client = DeepSearchClient(base_url="http://localhost:8080")
    
    # Crawl a URL
    result = client.crawl("https://example.com", formats=["markdown"])
    print(result.content)
    
    # Search
    results = client.search("What is AI?", max_results=5)
    print(results.results)
    ```
    """
    
    def __init__(self, base_url: str = "http://localhost:8080", timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.session = None
        
    async def __aenter__(self):
        """Async context manager entry"""
        self.session = aiohttp.ClientSession(timeout=self.timeout)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.close()
    
    def _get_service_url(self, service: str, endpoint: str) -> str:
        """Map service names to their respective ports"""
        service_ports = {
            "crawler": "8004",
            "search": "8003",
            "llm": "8081",
            "deepsearch": "8001"
        }
        port = service_ports.get(service)
        # Return the correct service URL based on port
        base = self.base_url.rsplit(':', 1)[0] if ':' in self.base_url else self.base_url
        return f"http://localhost:{port}{endpoint}"
    
    async def crawl(self, url: str, formats: List[str] = ["markdown"],
                   extract_metadata: bool = True, timeout: int = 10) -> CrawlResult:
        """
        Crawl a URL and convert to specified format

        Args:
            url: URL to crawl
            formats: List of output formats (e.g., ["markdown", "structured_text"])
            extract_metadata: Whether to extract metadata
            timeout: Request timeout in seconds

        Returns:
            CrawlResult with content and metadata
        """
        if not self.session:
            raise RuntimeError("SDK not initialized. Use 'async with DeepSearchClient() as client:' or call connect()")

        try:
            # For crawler service, use port 8004
            crawler_url = self._get_service_url("crawler", "/crawl")

            payload = {
                "url": url,
                "formats": formats,
                "extract_metadata": extract_metadata,
                "timeout": timeout
            }

            async with self.session.post(crawler_url, json=payload) as response:
                response.raise_for_status()
                data = await response.json()

                return CrawlResult(
                    url=data.get("url", url),
                    content=data.get("content", ""),
                    extracted_data=data.get("extracted_data"),
                    success=data.get("success", True),
                    error_message=data.get("error_message")
                )
        except Exception as e:
            return CrawlResult(
                url=url,
                content="",
                extracted_data=None,
                success=False,
                error_message=str(e)
            )
    
    async def search(self, query: str, max_results: int = 10,
                    search_depth: str = "basic", include_domains: List[str] = None,
                    exclude_domains: List[str] = None) -> SearchResult:
        """
        Perform a search using the search gateway

        Args:
            query: Search query string
            max_results: Maximum number of results to return
            search_depth: Search depth level ("basic", "advanced", "deep")
            include_domains: Domains to specifically include
            exclude_domains: Domains to exclude

        Returns:
            SearchResult with query results
        """
        if not self.session:
            raise RuntimeError("SDK not initialized. Use 'async with DeepSearchClient() as client:' or call connect()")

        try:
            # For search gateway, use port 8003
            search_url = self._get_service_url("search", "/search")

            payload = {
                "query": query,
                "max_results": max_results,
                "search_depth": search_depth,
                "include_domains": include_domains or [],
                "exclude_domains": exclude_domains or []
            }

            async with self.session.post(search_url, json=payload) as response:
                response.raise_for_status()
                data = await response.json()

                # The API returns a list of search results directly
                results_list = data if isinstance(data, list) else data.get("results", [])
                sources = list(set([result.get("source", "") for result in results_list if result.get("source")]))

                return SearchResult(
                    query=query,
                    results=results_list,
                    sources=sources,
                    timestamp=""
                )
        except Exception as e:
            raise RuntimeError(f"Search failed: {str(e)}")
            
    async def llm_complete(self, messages: List[Dict[str, str]],
                         provider: str = "gemini", temperature: float = 0.7,
                         max_tokens: int = 500) -> str:
        """
        Get completion from the LLM gateway

        Args:
            messages: List of messages in OpenAI format
            provider: Provider to use ("gemini", "groq", etc.)
            temperature: Temperature for generation
            max_tokens: Maximum tokens to generate

        Returns:
            Generated text response
        """
        if not self.session:
            raise RuntimeError("SDK not initialized. Use 'async with DeepSearchClient() as client:' or call connect()")

        try:
            # For LLM gateway, use port 8081
            llm_url = self._get_service_url("llm", "/v1/chat/completions")

            payload = {
                "model": provider,  # Standard OpenAI format
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }

            async with self.session.post(llm_url, json=payload) as response:
                response.raise_for_status()
                data = await response.json()

                # Return the content from the response
                choices = data.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "")
                else:
                    return data.get("content", "")
        except Exception as e:
            raise RuntimeError(f"LLM completion failed: {str(e)}")


# Synchronous wrapper for simpler usage
class SyncDeepSearchClient:
    """
    Synchronous wrapper around the async DeepSearchClient for simpler usage
    """

    def __init__(self, base_url: str = "http://localhost:8080", timeout: int = 30):
        self.client = DeepSearchClient(base_url, timeout)
        self.loop = None

    def __enter__(self):
        # Create asyncio event loop for sync wrapper
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.client.__aenter__())
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if hasattr(self.client, 'session') and self.client.session:
            self.loop.run_until_complete(self.client.session.close())
        if self.loop and not self.loop.is_closed():
            self.loop.close()

    def crawl(self, url: str, formats: List[str] = ["markdown"],
              extract_metadata: bool = True, timeout: int = 10) -> CrawlResult:
        """Synchronous wrapper for crawl method"""
        if self.loop is None:
            # Handle case where used outside context manager
            with self as sync_client:
                return sync_client.crawl(url, formats, extract_metadata, timeout)
        return self.loop.run_until_complete(
            self.client.crawl(url, formats, extract_metadata, timeout)
        )

    def search(self, query: str, max_results: int = 10,
               search_depth: str = "basic", include_domains: List[str] = None,
               exclude_domains: List[str] = None) -> SearchResult:
        """Synchronous wrapper for search method"""
        if self.loop is None:
            with self as sync_client:
                return sync_client.search(query, max_results, search_depth,
                                        include_domains, exclude_domains)
        return self.loop.run_until_complete(
            self.client.search(query, max_results, search_depth,
                              include_domains, exclude_domains)
        )

    def llm_complete(self, messages: List[Dict[str, str]],
                     provider: str = "gemini", temperature: float = 0.7,
                     max_tokens: int = 500) -> str:
        """Synchronous wrapper for llm_complete method"""
        if self.loop is None:
            with self as sync_client:
                return sync_client.llm_complete(messages, provider, temperature, max_tokens)
        return self.loop.run_until_complete(
            self.client.llm_complete(messages, provider, temperature, max_tokens)
        )


# Convenience functions for simple usage
def crawl_sync(url: str, formats: List[str] = ["markdown"],
              extract_metadata: bool = True, timeout: int = 10,
              base_url: str = "http://localhost:8080") -> CrawlResult:
    """Convenience function to crawl a URL synchronously"""
    with SyncDeepSearchClient(base_url=base_url) as client:
        return client.crawl(url, formats=formats,
                           extract_metadata=extract_metadata, timeout=timeout)


def search_sync(query: str, max_results: int = 10,
               search_depth: str = "basic", include_domains: List[str] = None,
               exclude_domains: List[str] = None,
               base_url: str = "http://localhost:8080") -> SearchResult:
    """Convenience function to search synchronously"""
    with SyncDeepSearchClient(base_url=base_url) as client:
        return client.search(query, max_results=max_results,
                            search_depth=search_depth,
                            include_domains=include_domains,
                            exclude_domains=exclude_domains)


def llm_complete_sync(messages: List[Dict[str, str]],
                     provider: str = "gemini", temperature: float = 0.7,
                     max_tokens: int = 500,
                     base_url: str = "http://localhost:8080") -> str:
    """Convenience function to get LLM completion synchronously"""
    with SyncDeepSearchClient(base_url=base_url) as client:
        return client.llm_complete(messages, provider=provider,
                                 temperature=temperature, max_tokens=max_tokens)


__all__ = [
    "DeepSearchClient",
    "SyncDeepSearchClient",
    "CrawlResult",
    "SearchResult",
    "crawl_sync",
    "search_sync",
    "llm_complete_sync"
]