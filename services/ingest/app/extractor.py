"""Content extraction — delegates to crawler service."""

import logging

import httpx

log = logging.getLogger("ingest.extractor")


async def extract_content(
    client: httpx.AsyncClient,
    crawler_url: str,
    url: str,
    timeout: float = 60.0,
) -> str:
    """Extract full-page markdown content via crawler service."""
    try:
        resp = await client.post(
            f"{crawler_url}/crawl",
            json={"url": url, "format": "markdown"},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        content = data.get("content", "") or data.get("markdown", "")
        if len(content) < 100:
            log.warning("short_content", url=url, length=len(content))
        return content
    except Exception as e:
        log.warning("extraction_failed", url=url, error=str(e))
        return ""
