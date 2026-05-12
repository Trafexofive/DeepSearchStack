"""Crawler Service — crawl4ai-based web scraper for DeepSearch pipeline.

Extracts clean markdown/content from URLs. Supports optional LLM-structured extraction.
"""
import time
import logging
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from crawl4ai import AsyncWebCrawler, CacheMode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [crawler] %(message)s",
)
log = logging.getLogger("crawler")

app = FastAPI(title="DeepSearch Crawler", version="1.0.0")


# ─── Models ──────────────────────────────────────────────────────────────────

class CrawlRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)
    extraction_strategy: str = Field(
        default="markdown",
        pattern="^(markdown|text|llm|json_css)$",
    )
    llm_instruction: Optional[str] = Field(default=None)
    css_selector: Optional[str] = Field(default=None)
    timeout: int = Field(default=30, ge=5, le=120)


class CrawlResponse(BaseModel):
    url: str
    content: str
    markdown: str
    title: Optional[str] = None
    success: bool
    content_length: int = 0
    crawled_at: float
    error_message: Optional[str] = None


class BatchCrawlRequest(BaseModel):
    urls: List[str] = Field(..., min_items=1, max_items=20)
    extraction_strategy: str = "markdown"
    timeout: int = 30


class BatchCrawlResponse(BaseModel):
    results: List[CrawlResponse]
    success_count: int
    failure_count: int
    total_duration_ms: float


# ─── Startup / Shutdown ──────────────────────────────────────────────────────

_crawler: Optional[AsyncWebCrawler] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _crawler
    log.info("Starting crawl4ai AsyncWebCrawler...")
    _crawler = AsyncWebCrawler(verbose=False)
    await _crawler.start()
    log.info("Crawler ready")
    yield
    log.info("Shutting down crawler...")
    if _crawler:
        await _crawler.close()
    log.info("Crawler stopped")


app.router.lifespan_context = lifespan


# ─── Endpoints ───────────────────────────────────────────────────────────────

@app.post("/crawl", response_model=CrawlResponse)
async def crawl_url(req: CrawlRequest, request: Request):
    """Crawl a single URL and extract markdown content."""
    rid = request.headers.get("X-Request-ID", "")
    log.info(f"Crawl request [%s] url=%s strategy=%s", rid, req.url[:120], req.extraction_strategy)

    if not _crawler:
        raise HTTPException(status_code=503, detail="Crawler not initialized")

    try:
        kwargs = {
            "url": req.url,
            "cache_mode": CacheMode.BYPASS,
        }

        if req.extraction_strategy == "llm" and req.llm_instruction:
            from crawl4ai.extraction_strategy import LLMExtractionStrategy
            kwargs["extraction_strategy"] = LLMExtractionStrategy(
                provider="deepseek",
                instruction=req.llm_instruction,
            )
        elif req.extraction_strategy == "json_css" and req.css_selector:
            from crawl4ai.extraction_strategy import JsonCssExtractionStrategy
            kwargs["extraction_strategy"] = JsonCssExtractionStrategy(
                schema=req.css_selector,
            )

        started = time.monotonic()
        result = await asyncio.wait_for(
            _crawler.arun(**kwargs),
            timeout=req.timeout,
        )

        if not result or not result.success:
            error = getattr(result, "error_message", "Unknown crawl error") if result else "No result"
            log.warning(f"Crawl failed [%s] url=%s: %s", rid, req.url[:120], error)
            return CrawlResponse(
                url=req.url,
                content="",
                markdown="",
                success=False,
                error_message=str(error),
                crawled_at=time.time(),
            )

        # Extract markdown content
        markdown = ""
        if hasattr(result, "markdown") and result.markdown:
            markdown = str(result.markdown)
        elif hasattr(result, "markdown_v2") and result.markdown_v2:
            markdown = str(result.markdown_v2.text) if hasattr(result.markdown_v2, "text") else str(result.markdown_v2)

        # Plain text fallback
        text_content = markdown or getattr(result, "cleaned_html", "") or ""

        elapsed = (time.monotonic() - started) * 1000
        log.info(
            f"Crawl completed [%s] url=%s title=%s len=%d duration=%.0fms",
            rid, req.url[:120],
            getattr(result, "title", result.metadata.get("title", "")) if hasattr(result, "metadata") else "",
            len(markdown), elapsed,
        )

        title = None
        if hasattr(result, "metadata") and isinstance(result.metadata, dict):
            title = result.metadata.get("title")

        return CrawlResponse(
            url=req.url,
            content=text_content,
            markdown=markdown,
            title=title,
            success=True,
            content_length=len(markdown),
            crawled_at=time.time(),
        )

    except asyncio.TimeoutError:
        log.error(f"Crawl timeout [%s] url=%s after %ds", rid, req.url[:120], req.timeout)
        return CrawlResponse(
            url=req.url,
            content="",
            markdown="",
            success=False,
            error_message=f"Timeout after {req.timeout}s",
            crawled_at=time.time(),
        )
    except Exception as e:
        log.error(f"Crawl error [%s] url=%s: %s", rid, req.url[:120], str(e))
        return CrawlResponse(
            url=req.url,
            content="",
            markdown="",
            success=False,
            error_message=str(e),
            crawled_at=time.time(),
        )


@app.post("/crawl/batch", response_model=BatchCrawlResponse)
async def crawl_batch(req: BatchCrawlRequest, request: Request):
    """Crawl multiple URLs concurrently."""
    rid = request.headers.get("X-Request-ID", "")
    started = time.monotonic()

    sem = asyncio.Semaphore(5)  # Max 5 concurrent crawls

    async def crawl_one(url: str) -> CrawlResponse:
        async with sem:
            inner_req = CrawlRequest(
                url=url,
                extraction_strategy=req.extraction_strategy,
                timeout=req.timeout,
            )
            return await crawl_url(inner_req, request)

    tasks = [crawl_one(u) for u in req.urls]
    results = await asyncio.gather(*tasks)

    ok = sum(1 for r in results if r.success)
    elapsed = (time.monotonic() - started) * 1000
    log.info(f"Batch crawl complete [%s]: %d/%d ok, %.0fms", rid, ok, len(results), elapsed)

    return BatchCrawlResponse(
        results=list(results),
        success_count=ok,
        failure_count=len(results) - ok,
        total_duration_ms=elapsed,
    )


@app.get("/health")
async def health():
    if not _crawler:
        return {"status": "degraded", "message": "Crawler not initialized"}
    return {"status": "healthy", "service": "crawler"}


@app.get("/")
async def root():
    return {
        "service": "crawler",
        "version": "1.0.0",
        "endpoints": {
            "POST /crawl": "Crawl a single URL → markdown",
            "POST /crawl/batch": "Crawl multiple URLs concurrently",
            "GET /health": "Health check",
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
