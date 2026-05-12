"""DeepSearch Core Engine — composes pipeline stages from modular components.

Pipeline: search → scrape → embed → retrieve → synthesize
Each stage is a standalone module in core/ — the engine wires them together.
"""
import time
import logging
from typing import Optional, AsyncIterator
import httpx

from models import (
    DeepSearchRequest, DeepSearchResponse, DeepSearchProgress,
    StreamChunk,
)
from config import config
from core.search import execute as search_stage
from core.scraper import execute as scrape_stage
from core.rag import embed as embed_stage, retrieve as retrieve_stage
from core.synthesis import stream as synthesis_stage, build_context

logger = logging.getLogger("deepsearch.core")


class DeepSearchEngine:
    """DeepSearch orchestration — thin compose layer over stage modules."""

    def __init__(self):
        self.search_gateway_url = config.get_service_url("search_gateway")
        self.inference_gateway_url = config.get_service_url("inference_gateway")
        self.vector_store_url = config.get_service_url("vector_store")
        self.crawler_url = config.get_service_url("crawler")
        self.http_client: Optional[httpx.AsyncClient] = None

    async def initialize(self):
        self.http_client = httpx.AsyncClient(timeout=60.0)

    async def shutdown(self):
        if self.http_client:
            await self.http_client.aclose()

    async def deep_search(self, request: DeepSearchRequest) -> AsyncIterator[StreamChunk]:
        """Execute full pipeline, yielding progress + content + completion events."""
        start_time = time.time()

        try:
            # ── Stage 1: Search ──
            yield self._progress("searching", f"Searching across providers...", 0.1)
            search_results = await search_stage(self.http_client, request, self.search_gateway_url)
            if not search_results:
                yield self._error("No search results found")
                return

            # ── Stage 2: Scrape ──
            scraped = []
            if request.enable_scraping and config.scraping_config.get("enabled", True):
                max_urls = request.max_scrape_urls or config.scraping_config.get("max_scrape_urls", 50)
                yield self._progress("scraping", f"Scraping {min(len(search_results), max_urls)} URLs...", 0.3)
                scraped = await scrape_stage(self.http_client, search_results, self.crawler_url, max_urls)

            # ── Stage 3: Embed ──
            if request.enable_rag and config.rag_config.get("enabled", True) and scraped:
                yield self._progress("embedding", f"Embedding {len(scraped)} documents...", 0.5)
                await embed_stage(self.http_client, request.query, scraped, self.vector_store_url)

            # ── Stage 4: Retrieve ──
            rag_chunks = []
            if request.enable_rag and config.rag_config.get("enabled", True):
                yield self._progress("retrieving", "Retrieving relevant chunks...", 0.6)
                top_k = request.rag_top_k or config.rag_config.get("top_k", 10)
                rag_chunks = await retrieve_stage(self.http_client, request.query, top_k, self.vector_store_url)

            # ── Stage 5: Synthesize ──
            if request.enable_synthesis:
                yield self._progress("synthesizing", "Generating answer...", 0.7)
                context = build_context(rag_chunks if rag_chunks else search_results, scraped)
                answer_parts = []
                async for chunk in synthesis_stage(
                    self.http_client, request.query, context,
                    self.inference_gateway_url, request.llm_provider, request.temperature,
                ):
                    answer_parts.append(chunk)
                    yield self._content(chunk)
                answer = "".join(answer_parts)
            else:
                answer = "Search completed. Synthesis disabled."

            # ── Complete ──
            yield self._sources(search_results)
            yield self._done(request, answer, search_results, scraped, rag_chunks, time.time() - start_time)

        except Exception as e:
            logger.error(f"Pipeline error: {e}", exc_info=True)
            yield self._error(f"Pipeline error: {str(e)}")

    # ── Event builders ── (small, pure helpers — not worth a separate file)

    def _progress(self, stage: str, msg: str, pct: float) -> StreamChunk:
        return StreamChunk(type="progress", data=DeepSearchProgress(stage=stage, message=msg, progress=pct).dict())

    def _error(self, msg: str) -> StreamChunk:
        return StreamChunk(type="error", data={"message": msg})

    def _content(self, text: str) -> StreamChunk:
        return StreamChunk(type="content", data={"content": text})

    def _sources(self, results) -> StreamChunk:
        return StreamChunk(type="sources", data={"sources": [r.dict() for r in results]})

    def _done(self, request, answer, search_results, scraped, rag_chunks, elapsed) -> StreamChunk:
        return StreamChunk(
            type="complete",
            data=DeepSearchResponse(
                query=request.query,
                answer=answer,
                sources=search_results,
                scraped_content=scraped if scraped else None,
                rag_chunks=rag_chunks if rag_chunks else None,
                session_id=request.session_id,
                execution_time=elapsed,
                provider_used=config.synthesis_config.get("model", "deepseek-chat"),
                total_results=len(search_results),
                results_scraped=len(scraped),
                chunks_retrieved=len(rag_chunks),
            ).dict(),
        )
