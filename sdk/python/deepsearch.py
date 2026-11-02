"""
DeepSearchStack - Python SDK v2
Comprehensive client for the full DeepSearchStack pipeline.
Async-first, with a sync wrapper for scripts.

EPIC 5.5.2: This is the SDK contract the TUI depends on. Every
method the TUI needs is here, plus streaming variants where
applicable. Errors are returned as (result, error) tuples — the
TUI never has to wrap calls in try/except for transport errors.

Usage (async):
    async with AsyncDeepSearchClient("http://localhost:8083") as client:
        models, err = await client.list_models()
        if err:
            print(f"failed: {err}")
            return
        result, err = await client.search("what is rust", providers=["searxng"])
        async for chunk in client.synthesize_stream("what is rust", sources=result):
            print(chunk, end="")

Usage (sync):
    with DeepSearchClient("http://localhost:8083") as client:
        models, err = client.list_models()
        result, err = client.search("what is rust")
        text = client.llm_complete([{"role": "user", "content": "hi"}])
"""

from __future__ import annotations

import asyncio
import json
import os
import warnings
from dataclasses import dataclass, field
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
    Tuple,
    Union,
)

import httpx


# ─── Type aliases ────────────────────────────────────────────────────────

# An "error envelope" — every method returns (result, error). The error
# is None on success, or a string describing the failure. The TUI
# pattern-matches on this and never has to wrap calls in try/except
# for transport-layer failures.
Result = Tuple[Any, Optional[str]]


# ─── Result dataclasses ─────────────────────────────────────────────────


@dataclass
class CrawlResult:
    """Result from a crawl operation."""
    url: str
    content: str
    markdown: Optional[str] = None
    title: Optional[str] = None
    success: bool = True
    error_message: Optional[str] = None
    word_count: int = 0
    extracted_at: Optional[str] = None
    # Escalation telemetry (set by crawler 2026-06-12+)
    extraction_method: str = "html"  # html | browser | ocr
    blocked: bool = False
    block_reason: Optional[str] = None
    escalations: List[str] = field(default_factory=list)
    screenshot_b64: Optional[str] = None
    screenshot_path: Optional[str] = None


@dataclass
class RenderResult:
    """Result from a /dss/render/render call (browser-renderer service)."""
    url: str
    final_url: str
    status: Optional[int]
    html: str
    html_length: int
    blocked: bool
    block_reason: Optional[str] = None
    screenshot_b64: Optional[str] = None
    screenshot_path: Optional[str] = None
    elapsed_ms: int = 0


@dataclass
class SearchHit:
    """A single search result."""
    title: str
    url: str
    description: str
    source: str
    confidence: float = 1.0
    snippet: Optional[str] = None
    domain_authority: Optional[float] = None
    rank: Optional[int] = None
    published_date: Optional[str] = None


@dataclass
class SearchResult:
    """Result from a search operation."""
    query: str
    hits: List[SearchHit] = field(default_factory=list)
    provider_results: Dict[str, List[SearchHit]] = field(default_factory=dict)
    elapsed_seconds: float = 0.0


@dataclass
class SynthesizedChunk:
    """One chunk from a streaming synthesis."""
    content: str
    finished: bool = False
    warning: Optional[str] = None  # citation validation warning, set near end


@dataclass
class ModelInfo:
    """A model in the inference-gateway catalog."""
    id: str
    provider: str
    owned_by: str = ""
    context_length: Optional[int] = None


@dataclass
class EmbedResult:
    """Result from an /embed call."""
    ids: List[str]
    count: int


@dataclass
class WarehouseHit:
    """A hit from knowledge-warehouse /search."""
    id: int
    url: str
    title: Optional[str]
    snippet: Optional[str]
    source_domain: Optional[str]
    word_count: int
    ingested_at: str


# ─── Async client ───────────────────────────────────────────────────────


class AsyncDeepSearchClient:
    """Async client for DeepSearchStack. Use as `async with`."""

    def __init__(
        self,
        base_url: str = "http://localhost:8083",
        timeout: float = 30.0,
        default_model: str = "virtual/free-coder",
        llm_base_url: Optional[str] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        # The LLM gateway isn't exposed via nginx — it lives on
        # port 8005 directly. If llm_base_url isn't given, infer it
        # from the main base_url by swapping the port to 8005.
        if llm_base_url:
            self.llm_base_url = llm_base_url.rstrip("/")
        else:
            from urllib.parse import urlsplit, urlunsplit
            parts = urlsplit(self.base_url)
            new_netloc = parts.netloc.rsplit(":", 1)[0] + ":8005" if ":" in parts.netloc else parts.netloc + ":8005"
            self.llm_base_url = urlunsplit((parts.scheme, new_netloc, "", "", ""))
        self._client: Optional[httpx.AsyncClient] = None
        self._timeout = timeout

    async def __aenter__(self) -> "AsyncDeepSearchClient":
        self._client = httpx.AsyncClient(timeout=self._timeout)
        return self

    async def __aexit__(self, *args) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @property
    def client(self) -> httpx.AsyncClient:
        if not self._client:
            raise RuntimeError("client not initialized — use 'async with AsyncDeepSearchClient(...) as c'")
        return self._client

    # ── Catalog ────────────────────────────────────────────────────────

    async def list_models(self) -> Result:
        """List all models in the inference-gateway catalog."""
        try:
            r = await self.client.get(f"{self.base_url}/dss/api/providers")
            r.raise_for_status()
            data = r.json()
            models = [
                ModelInfo(
                    id=m["id"],
                    provider=m["provider"],
                    owned_by=m.get("owned_by", ""),
                    context_length=m.get("context_length"),
                )
                for m in data.get("models", [])
            ]
            return models, None
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    async def list_search_providers(self) -> Result:
        """List registered search providers (search-gateway's catalog)."""
        try:
            # Search-gateway isn't directly behind nginx — use its internal port
            # via nginx routing if exposed, otherwise direct.
            r = await self.client.get(f"{self.base_url}/dss/gateway/providers/registered")
            r.raise_for_status()
            return r.json(), None
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    # ── Search ────────────────────────────────────────────────────────

    async def search(
        self,
        query: str,
        providers: Optional[List[str]] = None,
        max_results: int = 10,
        timeout: Optional[float] = None,
    ) -> Result:
        """Search via the search-gateway.

        Args:
            query: The search query.
            providers: List of provider names (e.g. ['searxng', 'wikipedia']).
                None = use gateway default.
            max_results: Max hits to return.
            timeout: Per-request timeout override.

        Returns:
            (SearchResult, None) on success, (None, error_str) on failure.
        """
        payload: Dict[str, Any] = {"query": query, "max_results": max_results}
        if providers:
            payload["providers"] = providers
        if timeout:
            payload["timeout"] = timeout
        try:
            r = await self.client.post(
                f"{self.base_url}/dss/gateway/search",
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
            hits = [_hit_from_dict(h) for h in data]
            return SearchResult(query=query, hits=hits), None
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    # ── Aggregate (multi-provider search + dedup) ─────────────────────

    async def aggregate(
        self,
        query: str,
        providers: Optional[List[str]] = None,
        max_results: int = 5,
        timeout: float = 30.0,
    ) -> Result:
        """Aggregate search via the web-api /aggregate endpoint.

        Same as search() but goes through web-api which adds dedup,
        ranking, and per-domain type info. The TUI uses this for
        E2E pipeline demos because it shows the full multi-provider
        fan-out. Default timeout is 30s (was 15s) because the
        aggregate fans out to N providers in parallel and slow
        ones can hit the 12s search-gateway deadline.
        """
        payload: Dict[str, Any] = {
            "query": query,
            "max_results": max_results,
            "timeout": timeout,
        }
        if providers:
            payload["providers"] = providers
        try:
            r = await self.client.post(
                f"{self.base_url}/dss/api/aggregate",
                json=payload,
                timeout=float(timeout) + 10.0,
            )
            r.raise_for_status()
            data = r.json()
            hits = [_hit_from_dict(s) for s in data.get("sources", [])]
            return SearchResult(
                query=query,
                hits=hits,
                provider_results=data.get("provider_results", {}),
                elapsed_seconds=data.get("elapsed_seconds", 0.0),
            ), None
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    # ── Synthesize (LLM-stream with citation validation) ───────────────

    async def synthesize_stream(
        self,
        query: str,
        sources: List[Dict[str, Any]],
        llm_model: Optional[str] = None,
        llm_provider: Optional[str] = None,
    ) -> AsyncIterator[SynthesizedChunk]:
        """Stream a synthesis from search-agent.

        Args:
            query: The user's question.
            sources: List of source dicts (must have title, url, description).
            llm_model: Model name (e.g. 'virtual/free-coder'). Default = client.default_model.
            llm_provider: Legacy field. If llm_model is set, this is ignored.

        Yields:
            SynthesizedChunk objects. The last chunk has finished=True.
            If citations are hallucinated, the warning field on a near-end
            chunk will contain the validation message.
        """
        payload = {
            "query": query,
            "sources": sources,
            "llm_provider": llm_provider or "",
            "llm_model": llm_model or self.default_model,
        }
        async with self.client.stream(
            "POST",
            f"{self.base_url}/dss/agent/synthesize/stream",
            json=payload,
        ) as r:
            if r.status_code != 200:
                # try to read the error body
                body = await r.aread()
                raise RuntimeError(f"synthesize failed ({r.status_code}): {body[:200]!r}")
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    return
                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                content = data.get("content", "")
                finished = data.get("finished", False)
                # The search-agent's citation-validation warning arrives as
                # a regular content chunk with the "Note: " prefix.
                warning = None
                if content and "Note:" in content and "_Note:" in content:
                    warning = content
                yield SynthesizedChunk(content=content, finished=finished, warning=warning)

    # ── LLM direct ────────────────────────────────────────────────────

    async def llm_complete(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> Result:
        """One-shot LLM completion via the inference-gateway.

        Connects to the gateway DIRECTLY (not via nginx) since nginx
        doesn't expose /dss/llm/. The gateway is at the same host as
        base_url but on port 8005.
        """
        payload: Dict[str, Any] = {
            "messages": messages,
            "model": model or self.default_model,
            "temperature": temperature,
            "stream": False,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        try:
            r = await self.client.post(
                f"{self.llm_base_url}/v1/chat/completions",
                json=payload,
                timeout=120.0,
            )
            r.raise_for_status()
            data = r.json()
            # Gateway envelope: {content, usage, raw_response: {choices: [...]}}
            content = data.get("content", "")
            if not content:
                # Try the OpenAI-standard choices path
                raw = data.get("raw_response", {})
                choices = raw.get("choices", [])
                if choices:
                    content = choices[0].get("message", {}).get("content", "")
            return content, None
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    async def llm_stream(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[Tuple[str, Optional[str]]]:
        """Stream LLM tokens. Yields (chunk, error). Error is set on the last
        item if the connection drops mid-stream."""
        payload = {
            "messages": messages,
            "model": model or self.default_model,
            "temperature": temperature,
            "stream": True,
        }
        try:
            async with self.client.stream(
                "POST",
                f"{self.llm_base_url}/v1/chat/completions",
                json=payload,
                timeout=120.0,
            ) as r:
                if r.status_code != 200:
                    body = await r.aread()
                    yield "", f"synthesize failed ({r.status_code}): {body[:200]!r}"
                    return
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        return
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue
                    # Gateway streams the raw OpenAI format for streaming
                    # responses (no envelope): {choices: [{delta: {content,
                    # reasoning_content}}]}. For non-streaming, it wraps
                    # in {content, raw_response: ...}. Handle both.
                    chunk = data.get("content", "")
                    if not chunk:
                        choices = data.get("choices", [])
                        if not choices:
                            raw = data.get("raw_response", {})
                            choices = raw.get("choices", [])
                        if choices:
                            delta = choices[0].get("delta", {})
                            chunk = delta.get("content", "") or delta.get("reasoning_content", "")
                    if chunk:
                        yield chunk, None
        except Exception as e:
            yield "", f"{type(e).__name__}: {e}"

    # ── Crawl ─────────────────────────────────────────────────────────

    async def crawl(
        self,
        url: str,
        formats: Optional[List[str]] = None,
        extract_metadata: bool = True,
        timeout: int = 30,
        forward_to_warehouse: bool = False,
        render_mode: str = "auto",
        enable_ocr_fallback: bool = True,
        return_screenshot: bool = False,
    ) -> Result:
        """Crawl a single URL via the crawler service.

        The route is /dss/crawl/crawl — nginx strips /dss/crawl/ and
        appends the rest, so /dss/crawl/crawl becomes /crawl on the
        crawler service (the actual endpoint name).

        render_mode (added 2026-06-12):
          - "auto"    fast crawl4ai; auto-escalate to browser/ocr on thin/blocked.
          - "fast"    crawl4ai only, no escalation.
          - "browser" force playwright via browser-renderer.
          - "ocr"     force screenshot+vision LLM (uses inference-gateway).
        """
        payload = {
            "url": url,
            "formats": formats or ["markdown"],
            "extract_metadata": extract_metadata,
            "timeout": timeout,
            "forward_to_warehouse": forward_to_warehouse,
            "render_mode": render_mode,
            "enable_ocr_fallback": enable_ocr_fallback,
            "return_screenshot": return_screenshot,
        }
        try:
            r = await self.client.post(
                f"{self.base_url}/dss/crawl/crawl",
                json=payload,
                timeout=float(timeout) + 90.0,  # leave room for browser+ocr escalation
            )
            r.raise_for_status()
            data = r.json()
            return CrawlResult(
                url=data.get("url", url),
                content=data.get("content", ""),
                markdown=data.get("markdown"),
                title=data.get("title") or data.get("extracted_data", {}).get("title"),
                success=data.get("success", True),
                error_message=data.get("error_message"),
                word_count=data.get("word_count", 0),
                extracted_at=data.get("extracted_at"),
                extraction_method=data.get("extraction_method", "html"),
                blocked=data.get("blocked", False),
                block_reason=data.get("block_reason"),
                escalations=data.get("escalations", []) or [],
                screenshot_b64=data.get("screenshot_b64"),
                screenshot_path=data.get("screenshot_path"),
            ), None
        except Exception as e:
            return CrawlResult(url=url, content="", success=False, error_message=str(e)), f"{type(e).__name__}: {e}"

    async def render(
        self,
        url: str,
        screenshot: bool = False,
        full_page_screenshot: bool = True,
        wait: str = "networkidle",
        timeout_ms: int = 25000,
        save_screenshot: bool = False,
    ) -> Result:
        """Render a URL via the browser-renderer (Playwright Chromium, realistic UA).

        Use this when you want raw HTML + optional screenshot, without the
        crawler's markdown/cache/warehouse layer. Route: /dss/render/render.
        """
        payload = {
            "url": url,
            "screenshot": screenshot,
            "full_page_screenshot": full_page_screenshot,
            "wait": wait,
            "timeout_ms": timeout_ms,
            "save_screenshot": save_screenshot,
        }
        try:
            r = await self.client.post(
                f"{self.base_url}/dss/render/render",
                json=payload,
                timeout=float(timeout_ms) / 1000.0 + 30.0,
            )
            r.raise_for_status()
            d = r.json()
            return RenderResult(
                url=d.get("url", url),
                final_url=d.get("final_url", url),
                status=d.get("status"),
                html=d.get("html", ""),
                html_length=d.get("html_length", 0),
                blocked=d.get("blocked", False),
                block_reason=d.get("block_reason"),
                screenshot_b64=d.get("screenshot_b64"),
                screenshot_path=d.get("screenshot_path"),
                elapsed_ms=d.get("elapsed_ms", 0),
            ), None
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    async def crawl_batch(
        self,
        urls: List[str],
        concurrency: int = 5,
        timeout: int = 30,
    ) -> Result:
        """Crawl multiple URLs in parallel. Returns a list of CrawlResults."""
        sem = asyncio.Semaphore(concurrency)
        async def _one(u: str) -> CrawlResult:
            async with sem:
                res, err = await self.crawl(u, timeout=timeout)
                return res or CrawlResult(url=u, content="", success=False, error_message=err)
        results = await asyncio.gather(*[_one(u) for u in urls])
        return results, None

    # ── Embed (vector store) ──────────────────────────────────────────

    async def embed(
        self,
        documents: List[Dict[str, Any]],
        namespace: str = "default",
    ) -> Result:
        """Embed documents into the vector store.

        documents: list of {id?, text, metadata?}. The vector-store
        returns {count, total_docs} on success (per-doc IDs are not
        echoed back, but the namespaced IDs are queryable via /query).
        """
        payload = {"namespace": namespace, "documents": documents}
        try:
            r = await self.client.post(
                f"{self.base_url}/dss/vectors/embed",
                json=payload,
            )
            r.raise_for_status()
            data = r.json()
            count = data.get("count", 0) or len(documents)
            return EmbedResult(ids=[], count=count), None
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    async def vector_query(
        self,
        query: str,
        namespace: str = "default",
        top_k: int = 5,
    ) -> Result:
        """Query the vector store for nearest neighbors."""
        payload = {"query": query, "namespace": namespace, "top_k": top_k}
        try:
            r = await self.client.post(
                f"{self.base_url}/dss/vectors/query",
                json=payload,
            )
            r.raise_for_status()
            return r.json(), None
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    # ── Warehouse ─────────────────────────────────────────────────────

    async def warehouse_search(
        self,
        query: str,
        domain: Optional[str] = None,
        limit: int = 20,
    ) -> Result:
        """Full-text search across persisted content."""
        params: Dict[str, Any] = {"q": query, "limit": limit}
        if domain:
            params["domain"] = domain
        try:
            r = await self.client.get(
                f"{self.base_url}/dss/warehouse/search",
                params=params,
            )
            r.raise_for_status()
            data = r.json()
            hits = [
                WarehouseHit(
                    id=h["id"],
                    url=h["url"],
                    title=h.get("title"),
                    snippet=h.get("snippet"),
                    source_domain=h.get("source_domain"),
                    word_count=h.get("word_count", 0),
                    ingested_at=h.get("ingested_at", ""),
                )
                for h in data
            ]
            return hits, None
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    async def warehouse_list(
        self,
        limit: int = 20,
        domain: Optional[str] = None,
    ) -> Result:
        """List the N most recent warehouse rows.

        Use this to audit what's actually landed (data-quality inspection)
        rather than only being able to query by keyword.
        """
        params: Dict[str, Any] = {"limit": limit}
        if domain:
            params["domain"] = domain
        try:
            r = await self.client.get(
                f"{self.base_url}/dss/warehouse/list",
                params=params,
            )
            r.raise_for_status()
            data = r.json()
            hits = [
                WarehouseHit(
                    id=h["id"],
                    url=h["url"],
                    title=h.get("title"),
                    snippet=h.get("snippet"),
                    source_domain=h.get("source_domain"),
                    word_count=h.get("word_count", 0),
                    ingested_at=h.get("ingested_at", ""),
                )
                for h in data
            ]
            return hits, None
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    async def warehouse_get(self, item_id: int) -> Result:
        """Get the full content of a single warehouse row by id."""
        try:
            r = await self.client.get(
                f"{self.base_url}/dss/warehouse/content/{item_id}",
            )
            r.raise_for_status()
            return r.json(), None
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    async def warehouse_stats(self) -> Result:
        """Get warehouse statistics (total docs, etc.)."""
        try:
            r = await self.client.get(f"{self.base_url}/dss/warehouse/stats")
            r.raise_for_status()
            return r.json(), None
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"

    # ── Health ────────────────────────────────────────────────────────

    async def health(self) -> Result:
        """Check the web-api's /health. Returns the JSON dict."""
        try:
            r = await self.client.get(f"{self.base_url}/health")
            r.raise_for_status()
            return r.json(), None
        except Exception as e:
            return None, f"{type(e).__name__}: {e}"


# ─── Sync wrapper ──────────────────────────────────────────────────────


class DeepSearchClient:
    """Synchronous wrapper around AsyncDeepSearchClient. For scripts.

    Usage:
        with DeepSearchClient() as client:
            models, err = client.list_models()
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8083",
        timeout: float = 30.0,
        default_model: str = "virtual/free-coder",
        llm_base_url: Optional[str] = None,
    ):
        self._async = AsyncDeepSearchClient(
            base_url=base_url, timeout=timeout,
            default_model=default_model, llm_base_url=llm_base_url,
        )
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def __enter__(self) -> "DeepSearchClient":
        self._loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(self._loop)
        except RuntimeError:
            pass
        self._loop.run_until_complete(self._async.__aenter__())
        return self

    def __exit__(self, *args) -> None:
        if self._loop and not self._loop.is_closed():
            try:
                self._loop.run_until_complete(self._async.__aexit__(*args))
            finally:
                self._loop.close()

    def _run(self, coro):
        if not self._loop or self._loop.is_closed():
            with self as c:
                return c._run(coro)
        return self._loop.run_until_complete(coro)

    # Catalog
    def list_models(self) -> Result:
        return self._run(self._async.list_models())

    def list_search_providers(self) -> Result:
        return self._run(self._async.list_search_providers())

    # Search
    def search(self, query: str, **kwargs) -> Result:
        return self._run(self._async.search(query, **kwargs))

    def aggregate(self, query: str, **kwargs) -> Result:
        return self._run(self._async.aggregate(query, **kwargs))

    # Synthesize (async generator → list)
    def synthesize(self, query: str, sources: List[Dict[str, Any]], **kwargs) -> Tuple[str, Optional[str]]:
        """Drain the synthesize stream and return (full_text, error)."""
        async def _drain():
            chunks = []
            err = None
            async for ch in self._async.synthesize_stream(query, sources, **kwargs):
                if ch.content and not ch.finished:
                    chunks.append(ch.content)
                if ch.warning:
                    chunks.append("\n\n" + ch.warning)
            return "".join(chunks), err
        return self._run(_drain())

    # LLM
    def llm_complete(self, messages, **kwargs) -> Result:
        return self._run(self._async.llm_complete(messages, **kwargs))

    def llm_stream(self, messages, **kwargs) -> Iterator[Tuple[str, Optional[str]]]:
        """Drain the async stream into a sync iterator."""
        async def _drain():
            out = []
            async for chunk, err in self._async.llm_stream(messages, **kwargs):
                if err:
                    return out, err
                if chunk:
                    out.append(chunk)
            return out, None
        chunks, err = self._run(_drain())
        if err:
            yield "", err
            return
        for c in chunks:
            yield c, None

    # Crawl
    def crawl(self, url: str, **kwargs) -> Result:
        return self._run(self._async.crawl(url, **kwargs))

    def crawl_batch(self, urls: List[str], **kwargs) -> Result:
        return self._run(self._async.crawl_batch(urls, **kwargs))

    # Embed
    def embed(self, documents, **kwargs) -> Result:
        return self._run(self._async.embed(documents, **kwargs))

    def vector_query(self, query, **kwargs) -> Result:
        return self._run(self._async.vector_query(query, **kwargs))

    # Warehouse
    def warehouse_search(self, query, **kwargs) -> Result:
        return self._run(self._async.warehouse_search(query, **kwargs))

    def warehouse_stats(self) -> Result:
        return self._run(self._async.warehouse_stats())

    # Health
    def health(self) -> Result:
        return self._run(self._async.health())


# ─── Citation validation (used by the TUI) ────────────────────────────

import re as _re
_CITATION_RE = _re.compile(r"\[(\d+)\]")


def validate_citations(content: str, num_sources: int) -> Dict[str, Any]:
    """Parse [N] citations and detect out-of-range ones.

    Returns:
      {
        "total": int,
        "valid": List[int],
        "invalid": List[int],   # deduped, in first-seen order
        "invalid_strs": List[str],
      }
    """
    found = _CITATION_RE.findall(content)
    total = len(found)
    valid: List[int] = []
    invalid: List[int] = []
    invalid_strs: List[str] = []
    seen: set = set()
    for s in found:
        n = int(s)
        if 1 <= n <= num_sources:
            valid.append(n)
        else:
            if n not in seen:
                seen.add(n)
                invalid.append(n)
                invalid_strs.append(f"[{n}]")
    return {"total": total, "valid": valid, "invalid": invalid, "invalid_strs": invalid_strs}


# ─── Helpers ────────────────────────────────────────────────────────────


def _hit_from_dict(d: Dict[str, Any]) -> SearchHit:
    """Convert a search-hit dict (from any of the gateway endpoints) to a SearchHit."""
    return SearchHit(
        title=d.get("title", ""),
        url=d.get("url", ""),
        description=d.get("description", "") or d.get("snippet", "") or "",
        source=d.get("source", ""),
        confidence=d.get("confidence", 1.0),
        snippet=d.get("snippet"),
        domain_authority=d.get("domain_authority"),
        rank=d.get("rank"),
        published_date=d.get("published_date"),
    )


__all__ = [
    "AsyncDeepSearchClient",
    "DeepSearchClient",
    "CrawlResult",
    "SearchHit",
    "SearchResult",
    "SynthesizedChunk",
    "ModelInfo",
    "EmbedResult",
    "WarehouseHit",
    "validate_citations",
]
