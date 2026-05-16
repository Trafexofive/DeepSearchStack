"""DeepSearchStack SDK — single client for the entire DSS pipeline.

Usage:
    from sdk import DSSClient

    async with DSSClient() as dss:
        # Aggregate search with reconciliation
        result = await dss.aggregate("Rust memory safety", reconcile=True)
        print(f"{result.total_sources} sources, {len(result.consensus)} consensus facts")

        # Bulk URL ingestion
        ingest = await dss.ingest_urls(["https://example.com", "https://rust-lang.org"])
        print(f"{ingest.success_count}/{ingest.urls_submitted} ingested")

        # Health check
        health = await dss.health()
        for svc, status in health.items():
            print(f"  {svc}: {status}")
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional

import httpx

log = logging.getLogger("dss.sdk")

# Default service URLs (overridable via env or constructor)
DEFAULT_URLS = {
    "web_api": "http://localhost:8014",
    "search_gateway": "http://localhost:8002",
    "crawler": "http://localhost:8000",
    "warehouse": "http://localhost:8009",
    "vector_store": "http://localhost:8004",
    "search_agent": "http://localhost:8013",
    "deepsearch": "http://localhost:8001",
}


# ── Response models (dataclasses, no pydantic dep) ──────────────────────────

@dataclass
class ConsensusFact:
    claim: str
    confidence: float
    supporting_sources: list[str] = field(default_factory=list)
    conflicting_sources: list[str] = field(default_factory=list)


@dataclass
class SearchResult:
    title: str
    url: str
    source: str
    domain: str
    description: str = ""
    confidence: float = 0.5


@dataclass
class AggregateResponse:
    query: str
    total_sources: int
    domains_queried: list[str]
    sources: list[SearchResult]
    consensus: list[ConsensusFact]
    synthesis: Optional[str] = None
    execution_time_ms: int = 0
    scraped_urls: int = 0
    rag_chunks: int = 0

    @classmethod
    def from_json(cls, data: dict) -> "AggregateResponse":
        return cls(
            query=data["query"],
            total_sources=data["total_sources"],
            domains_queried=data["domains_queried"],
            sources=[SearchResult(**s) for s in data.get("sources", [])],
            consensus=[ConsensusFact(**c) for c in data.get("consensus", [])],
            synthesis=data.get("synthesis") or data.get("answer"),
            execution_time_ms=data.get("execution_time_ms", 0),
            scraped_urls=data.get("scraped_urls", 0),
            rag_chunks=data.get("rag_chunks", 0),
        )


@dataclass
class IngestResult:
    urls_submitted: int
    success_count: int
    failure_count: int
    cache_hits: int
    total_duration_ms: float
    warehouse_entries_after: int


@dataclass
class HealthStatus:
    service: str
    status: str
    details: dict = field(default_factory=dict)


# ── Client ──────────────────────────────────────────────────────────────────

class DSSClient:
    """DeepSearchStack client — wraps all services behind clean API."""

    def __init__(
        self,
        web_api_url: str | None = None,
        crawler_url: str | None = None,
        warehouse_url: str | None = None,
        vector_store_url: str | None = None,
        search_agent_url: str | None = None,
        search_gateway_url: str | None = None,
        deepsearch_url: str | None = None,
        timeout: float = 120.0,
    ):
        import os
        self.web_api = web_api_url or os.environ.get("DSS_WEB_API", DEFAULT_URLS["web_api"])
        self.crawler = crawler_url or os.environ.get("DSS_CRAWLER", DEFAULT_URLS["crawler"])
        self.warehouse = warehouse_url or os.environ.get("DSS_WAREHOUSE", DEFAULT_URLS["warehouse"])
        self.vector_store = vector_store_url or os.environ.get("DSS_VECTOR_STORE", DEFAULT_URLS["vector_store"])
        self.search_agent = search_agent_url or os.environ.get("DSS_SEARCH_AGENT", DEFAULT_URLS["search_agent"])
        self.search_gateway = search_gateway_url or os.environ.get("DSS_SEARCH_GATEWAY", DEFAULT_URLS["search_gateway"])
        self.deepsearch = deepsearch_url or os.environ.get("DSS_DEEPSEARCH", DEFAULT_URLS["deepsearch"])
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Use 'async with DSSClient() as dss:' or call dss.connect()")
        return self._client

    async def connect(self):
        """Open the HTTP client (if not using context manager)."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Aggregate (unified search) ─────────────────────────────────

    async def aggregate(
        self,
        query: str,
        max_results: int = 10,
        reconcile: bool = True,
        include_warehouse: bool = True,
        enable_scraping: bool = False,
        max_scrape_urls: int = 5,
        enable_rag: bool = False,
        rag_top_k: int = 10,
    ) -> AggregateResponse:
        """Cross-domain aggregate search with optional scraping, RAG, and LLM reconciliation."""
        payload = {
            "query": query,
            "max_results": max_results,
            "reconcile": reconcile,
            "include_warehouse": include_warehouse,
            "enable_scraping": enable_scraping,
            "max_scrape_urls": max_scrape_urls,
            "enable_rag": enable_rag,
            "rag_top_k": rag_top_k,
        }
        t0 = time.monotonic()
        resp = await self.client.post(f"{self.web_api}/api/aggregate", json=payload)
        resp.raise_for_status()
        data = resp.json()
        result = AggregateResponse.from_json(data)
        log.info("aggregate query=%s sources=%d consensus=%d time=%dms",
                 query, result.total_sources, len(result.consensus), data.get("execution_time_ms", 0))
        return result

    async def aggregate_stream(self, query: str, max_results: int = 10):
        """Streaming aggregate via /api/search/stream (SSE). Yields dicts."""
        async with self.client.stream(
            "POST",
            f"{self.web_api}/api/search/stream",
            json={"query": query, "max_results": max_results},
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    try:
                        yield json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue

    # ── Ingestion ────────────────────────────────────────────────

    async def ingest_urls(
        self,
        urls: list[str],
        timeout: int = 20,
        bypass_cache: bool = False,
    ) -> IngestResult:
        """Bulk URL ingestion — crawl + warehouse store."""
        payload = {
            "urls": urls,
            "timeout": timeout,
            "bypass_cache": bypass_cache,
        }
        resp = await self.client.post(f"{self.web_api}/api/ingest/urls", json=payload)
        resp.raise_for_status()
        data = resp.json()
        result = IngestResult(**data)
        log.info("ingest urls=%d ok=%d fail=%d cache=%d warehouse=%d",
                 result.urls_submitted, result.success_count,
                 result.failure_count, result.cache_hits,
                 result.warehouse_entries_after)
        return result

    async def warehouse_stats(self) -> dict:
        """Get knowledge warehouse statistics."""
        resp = await self.client.get(f"{self.warehouse}/stats")
        resp.raise_for_status()
        return resp.json()

    async def warehouse_search(self, query: str, limit: int = 10, domain: str | None = None) -> list[dict]:
        """Full-text search in the knowledge warehouse."""
        params = {"q": query, "limit": limit}
        if domain:
            params["domain"] = domain
        resp = await self.client.get(f"{self.warehouse}/search", params=params)
        resp.raise_for_status()
        return resp.json()

    # ── Crawler ──────────────────────────────────────────────────

    async def crawl(self, url: str, timeout: int = 20, bypass_cache: bool = False) -> dict:
        """Crawl a single URL."""
        resp = await self.client.post(
            f"{self.crawler}/crawl",
            json={"url": url, "timeout": timeout, "bypass_cache": bypass_cache},
        )
        resp.raise_for_status()
        return resp.json()

    async def crawler_stats(self) -> dict:
        """Get crawler cache stats."""
        resp = await self.client.get(f"{self.crawler}/cache/stats")
        resp.raise_for_status()
        return resp.json()

    async def crawler_pending(self) -> dict:
        """Get pending warehouse forwards."""
        resp = await self.client.get(f"{self.crawler}/crawl/pending")
        resp.raise_for_status()
        return resp.json()

    # ── Health ───────────────────────────────────────────────────

    async def health(self) -> dict[str, str]:
        """Check health of all DSS services."""
        services = {
            "web_api": self.web_api,
            "crawler": self.crawler,
            "warehouse": self.warehouse,
            "vector_store": self.vector_store,
            "search_agent": self.search_agent,
            "search_gateway": self.search_gateway,
            "deepsearch": self.deepsearch,
        }
        results = {}
        async def check(name: str, url: str):
            try:
                resp = await self.client.get(f"{url}/health", timeout=httpx.Timeout(5.0))
                data = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
                results[name] = data.get("status", f"HTTP {resp.status_code}")
            except Exception as e:
                results[name] = f"unreachable: {e}"

        await asyncio.gather(*[check(n, u) for n, u in services.items()])
        return results

    async def health_report(self) -> str:
        """Pretty-printed health report."""
        h = await self.health()
        lines = ["DeepSearchStack Health Report", "=" * 40]
        for svc, status in h.items():
            icon = "●" if status == "healthy" else "○" if status == "ok" else "✖"
            lines.append(f"  {icon} {svc:20s} {status}")
        return "\n".join(lines)
