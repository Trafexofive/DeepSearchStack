"""Scraping stage — parallel content extraction via crawler service."""
import asyncio
import logging
from typing import List, Optional

from models import SearchResult, ScrapedContent
from config import config

logger = logging.getLogger("deepsearch.scraper")


async def execute(
    client,
    search_results: List[SearchResult],
    crawler_url: str,
    max_urls: int = 50,
) -> List[ScrapedContent]:
    """Scrape content from search result URLs in parallel with controlled concurrency."""
    urls_to_scrape = [r.url for r in search_results[:max_urls]]
    concurrency = config.scraping_config.get("concurrency", 10)
    semaphore = asyncio.Semaphore(concurrency)

    async def scrape_one(url: str, title: str) -> Optional[ScrapedContent]:
        async with semaphore:
            try:
                response = await client.post(
                    f"{crawler_url}/crawl",
                    json={
                        "url": url,
                        "extraction_strategy": config.scraping_config.get("extraction_strategy", "markdown"),
                    },
                    timeout=config.scraping_config.get("timeout", 15.0),
                )
                response.raise_for_status()
                data = response.json()
                return ScrapedContent(
                    url=url,
                    title=title,
                    content=data.get("content", ""),
                    markdown=data.get("content", ""),
                    success=data.get("success", False),
                    word_count=len(data.get("content", "").split()),
                    error_message=data.get("error_message"),
                )
            except Exception as e:
                logger.warning(f"Scrape failed for {url}: {e}")
                return ScrapedContent(url=url, title=title, content="", success=False, error_message=str(e))

    tasks = [scrape_one(r.url, r.title) for r in search_results[:max_urls]]
    results = await asyncio.gather(*tasks)

    min_length = config.scraping_config.get("min_content_length", 100)
    return [r for r in results if r and r.success and len(r.content) >= min_length]
