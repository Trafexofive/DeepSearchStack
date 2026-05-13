"""DeepSearch Core Engine — composes pipeline stages from modular components.

Pipeline: search → scrape → embed → retrieve → synthesize
Recursive Research: iterative search-refine-synthesize (Local Deep Research pattern)
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


# ── Module-level helpers ─────────────────────────────────────────────────────

def _build_gap_analysis_prompt(original_query: str, current_query: str, scraped: list) -> str:
    """Build prompt for identifying research gaps."""
    excerpts = []
    for s in scraped[:5]:
        excerpts.append(f"- {s.title}: {s.content[:300]}...")
    return f"""Original research question: {original_query}
Current sub-query: {current_query}

Results so far:
{chr(10).join(excerpts)}

What important aspects of the original question remain unanswered?
Generate 2-3 refined search queries to fill these gaps. Output one query per line."""


# ── Engine ───────────────────────────────────────────────────────────────────

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

    # ── Standard Deep Search (5-stage pipeline) ──────────────────────────

    async def deep_search(self, request: DeepSearchRequest) -> AsyncIterator[StreamChunk]:
        """Execute full pipeline, yielding progress + content + completion events."""
        start_time = time.time()

        try:
            # ── Stage 1: Search ──
            yield self._progress("searching", "Searching across providers...", 0.1)
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

    # ── Recursive Research (Local Deep Research pattern) ─────────────────

    async def recursive_research(
        self,
        request: "RecursiveResearchRequest",
    ) -> AsyncIterator[StreamChunk]:
        """Local Deep Research pattern — iterative search-refine-synthesize.

        Each iteration:
        1. Search for current query
        2. Scrape top results
        3. Synthesize quick analysis → identify gaps
        4. Generate 2-3 refined follow-up queries
        5. Loop with new queries

        Final iteration: full synthesis from all accumulated context.
        """
        start_time = time.time()
        all_search_results: list = []
        all_scraped: list = []
        refinement_queries: list = []
        current_query = request.query

        try:
            for iteration in range(request.max_iterations):
                is_final = (iteration == request.max_iterations - 1)
                stage_prefix = f"[iter {iteration + 1}/{request.max_iterations}]"
                pct_base = iteration / request.max_iterations

                # ── Search ──
                yield self._progress("searching", f"{stage_prefix} Searching: {current_query[:80]}...", pct_base + 0.05)
                search_results = await search_stage(
                    self.http_client,
                    DeepSearchRequest(query=current_query, max_results=request.max_results_per_iter, providers=request.providers),
                    self.search_gateway_url,
                )
                if not search_results:
                    yield self._error(f"No results for: {current_query}")
                    if iteration == 0:
                        return
                    continue

                all_search_results.extend(search_results)

                # ── Scrape ──
                scraped = []
                if config.scraping_config.get("enabled", True):
                    yield self._progress("scraping", f"{stage_prefix} Scraping {min(len(search_results), request.max_scrape_per_iter)} pages...", pct_base + 0.1)
                    scraped = await scrape_stage(
                        self.http_client, search_results, self.crawler_url,
                        request.max_scrape_per_iter,
                    )
                    all_scraped.extend(scraped)

                # ── Gap analysis (skip on final iteration) ──
                if not is_final and scraped:
                    yield self._progress("synthesizing", f"{stage_prefix} Analyzing gaps...", pct_base + 0.15)

                    gap_prompt = _build_gap_analysis_prompt(request.query, current_query, scraped)
                    refined = await self._quick_synthesize(gap_prompt, request)
                    refinement_queries.append(refined)

                    # Parse refined queries (one per line, up to 3)
                    new_queries = [q.strip("- •123456789. ") for q in refined.strip().split("\n") if q.strip() and len(q) > 10]
                    if new_queries:
                        current_query = new_queries[0]
                        yield self._progress("searching", f"{stage_prefix} Refined → {current_query[:80]}...", pct_base + 0.18)
                    else:
                        break

            # ── Final synthesis ──
            yield self._progress("synthesizing", f"Synthesizing from {len(all_search_results)} sources across {len(all_scraped)} scraped pages...", 0.85)

            context = build_context(all_search_results[-20:], all_scraped[-20:])
            answer_parts = []
            async for chunk in synthesis_stage(
                self.http_client, request.query, context,
                self.inference_gateway_url, request.llm_provider, request.temperature,
            ):
                answer_parts.append(chunk)
                yield self._content(chunk)
            answer = "".join(answer_parts)

            yield self._sources(all_search_results)
            yield self._recursive_done(request, answer, all_search_results, all_scraped, refinement_queries, time.time() - start_time)

        except Exception as e:
            logger.error(f"Recursive research error: {e}", exc_info=True)
            yield self._error(f"Recursive research error: {str(e)}")

    async def _quick_synthesize(self, prompt: str, request: "RecursiveResearchRequest") -> str:
        """Fast synthesis for gap analysis — low token, non-streaming."""
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "You are a research gap analyzer. Output 2-3 refined search queries, one per line. Be specific and technical."},
                {"role": "user", "content": prompt},
            ],
            "max_tokens": 200,
            "temperature": 0.7,
            "stream": False,
        }
        try:
            resp = await self.http_client.post(
                f"{self.inference_gateway_url}/v1/chat/completions",
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.warning(f"Gap analysis failed: {e}")
            return ""

    def _recursive_done(self, request, answer, sources, scraped, refinements, elapsed) -> StreamChunk:
        return StreamChunk(
            type="complete",
            data={
                "query": request.query,
                "answer": answer,
                "iterations": request.max_iterations,
                "all_sources": [s.dict() for s in sources],
                "all_scraped": [s.dict() for s in scraped] if scraped else None,
                "refinement_queries": refinements,
                "session_id": request.session_id,
                "execution_time": elapsed,
            },
        )

    # ── Event builders ──

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
