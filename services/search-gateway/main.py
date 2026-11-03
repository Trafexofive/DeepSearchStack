import os
import re
import time
import httpx
import asyncio
import logging
from typing import List, Optional, Dict, Any
from fastapi import FastAPI, Depends
from contextlib import asynccontextmanager
import redis.asyncio as redis

from .common.models import SearchGatewayRequest, SearchResult, SearchProvider, SortMethod
from .providers.provider_manager import SearchProviderManager
from .ranking.result_ranker import ResultRanker
from .utils.system_components import MetricsCollector, CircuitBreaker

logger = logging.getLogger("search_gateway")
PROVIDER_TIMEOUT_DEFAULT = float(os.environ.get("PROVIDER_TIMEOUT", "7.0"))

DOMAIN_PRESETS = {
    "tech": [
        SearchProvider.GITHUB,
        SearchProvider.STACKEXCHANGE,
        SearchProvider.HACKERNEWS,
        SearchProvider.DUCKDUCKGO,
        SearchProvider.WIKIPEDIA,
    ],
    "code": [
        SearchProvider.GITHUB,
        SearchProvider.STACKEXCHANGE,
        SearchProvider.HACKERNEWS,
    ],
    "academic": [
        SearchProvider.ARXIV,
        SearchProvider.PUBMED,
        SearchProvider.CROSSREF,
        SearchProvider.WIKIPEDIA,
    ],
    "science": [
        SearchProvider.ARXIV,
        SearchProvider.PUBMED,
        SearchProvider.CROSSREF,
    ],
    "biomedical": [
        SearchProvider.PUBMED,
        SearchProvider.CROSSREF,
        SearchProvider.ARXIV,
        SearchProvider.WIKIPEDIA,
    ],
    "discussions": [
        SearchProvider.HACKERNEWS,
        SearchProvider.REDDIT,
        SearchProvider.STACKEXCHANGE,
    ],
    "all": [
        SearchProvider.ARXIV,
        SearchProvider.PUBMED,
        SearchProvider.CROSSREF,
        SearchProvider.GITHUB,
        SearchProvider.STACKEXCHANGE,
        SearchProvider.HACKERNEWS,
        SearchProvider.DUCKDUCKGO,
        SearchProvider.WIKIPEDIA,
        SearchProvider.REDDIT,
        SearchProvider.INTERNET_ARCHIVE,
    ],
}

class SearchGateway:
    def __init__(self, redis_client: redis.Redis):
        self.provider_manager = SearchProviderManager(MetricsCollector(), CircuitBreaker(redis_client))
        self.ranker = ResultRanker()
        self.version = "1.0.0"

    async def _query_with_timeout(self, client, provider, query, request, timeout):
        """Wrap a single provider call in a timeout. Returns None on timeout/error."""
        try:
            return await asyncio.wait_for(
                self.provider_manager.query_provider(client, provider, query, request),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(f"Provider {provider.value} timed out after {timeout}s")
            return None
        except Exception as e:
            logger.warning(f"Provider {provider.value} error: {type(e).__name__}: {e}")
            return None

    def resolve_providers(self, request: SearchGatewayRequest) -> List[SearchProvider]:
        """Strict precedence provider resolution:
        1. Explicit caller override (request.providers)
        2. Configurable domain preset (request.domain)
        3. Automatic heuristic intent classification
        """
        if request.providers is not None and len(request.providers) > 0:
            return request.providers

        if request.domain:
            domain_key = request.domain.lower().strip()
            if domain_key in DOMAIN_PRESETS:
                return DOMAIN_PRESETS[domain_key]

        return self._classify_intent(request.query)

    def _classify_intent(self, query: str) -> List[SearchProvider]:
        q = query.lower()
        tokens = set(re.findall(r"\w+", q))

        bio_terms = {
            "crispr", "gene", "dna", "rna", "protein", "disease", "clinical", "cell",
            "therapy", "drug", "trial", "patient", "syndrome", "virus", "cancer", "antibody"
        }
        if tokens.intersection(bio_terms):
            return DOMAIN_PRESETS["biomedical"]

        tech_terms = {
            "algorithm", "consensus", "rust", "python", "golang", "cpp", "c", "linux",
            "kernel", "docker", "kubernetes", "database", "sql", "postgres", "redis",
            "async", "thread", "mutex", "segv", "sigsegv", "api", "bug", "error",
            "raft", "paxos", "vector", "llm", "git", "github", "compile", "heap", "stack"
        }
        if tokens.intersection(tech_terms) or "_" in q:
            return DOMAIN_PRESETS["tech"]

        academic_terms = {
            "paper", "arxiv", "theorem", "proof", "model", "benchmark", "quantum",
            "evaluation", "survey", "formal", "verification", "complexity", "hypothesis"
        }
        if tokens.intersection(academic_terms):
            return DOMAIN_PRESETS["academic"]

        # Default balanced fallback across core ground-truth providers
        return [
            SearchProvider.DUCKDUCKGO,
            SearchProvider.WIKIPEDIA,
            SearchProvider.GITHUB,
            SearchProvider.ARXIV,
            SearchProvider.STACKEXCHANGE,
            SearchProvider.HACKERNEWS,
        ]

    async def search(self, request: SearchGatewayRequest) -> List[SearchResult]:
        start_time = time.time()
        # Per-provider timeout capped at the request-level timeout.
        per_provider_timeout = min(PROVIDER_TIMEOUT_DEFAULT, request.timeout)

        active_providers = self.resolve_providers(request)
        logger.info(f"Query '{request.query}' resolved to {len(active_providers)} providers: {[p.value for p in active_providers]}")

        async with httpx.AsyncClient(timeout=request.timeout) as client:
            tasks = [
                self._query_with_timeout(client, p, request.query, request, per_provider_timeout)
                for p in active_providers
            ]
            results = await asyncio.gather(*tasks)

        provider_pairs = [
            (p.value, res)
            for p, res in zip(active_providers, results)
            if res
        ]
        total_raw = sum(len(res) for _, res in provider_pairs)
        logger.info(f"Got {total_raw} raw results from {len(provider_pairs)} responsive providers.")

        limited_results = self.ranker.fuse_and_rank(
            query=request.query,
            provider_results=provider_pairs,
            sort_method=request.sort_by,
            max_results=request.max_results
        )

        execution_time = time.time() - start_time
        logger.info(f"Search completed in {execution_time:.2f}s (per-provider timeout: {per_provider_timeout}s).")

        return limited_results

    def _fuse_and_deduplicate(self, all_results: List[SearchResult]) -> List[SearchResult]:
        """Dedupe by URL with normalization (audit L74).

        Without normalization, 'https://example.com' and
        'https://example.com/' (and 'HTTPS://Example.com/foo?utm_source=x')
        are treated as distinct. Now all canonicalize to the same key.
        """
        from libs.common.text import normalize_url
        return list({
            normalize_url(result.url): result
            for result in all_results
            if result.url
        }.values())

@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_client = redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)
    app.state.gateway = SearchGateway(redis_client)
    yield
    await redis_client.close()

app = FastAPI(title="DeepSearch Gateway", version="1.0.0", lifespan=lifespan)

@app.post("/search", response_model=List[SearchResult])
async def search_endpoint(request: SearchGatewayRequest, gateway: SearchGateway = Depends(lambda: app.state.gateway)):
    return await gateway.search(request)
    
@app.get("/health")
async def health(gateway: SearchGateway = Depends(lambda: app.state.gateway)):
    return {"status": "healthy", "version": gateway.version}

@app.get("/providers/registered")
async def list_registered_providers(gateway: SearchGateway = Depends(lambda: app.state.gateway)):
    """List all registered providers (static config, not runtime health).

    The 'enabled' status is a static string indicating the provider is
    configured, not that it is currently healthy. For per-provider runtime
    health, check the upstream service's /health endpoint.
    """
    return gateway.provider_manager.get_provider_status()

# Backwards-compatible alias. Deprecated; use /providers/registered.
@app.get("/providers", deprecated=True)
async def list_providers_legacy(gateway: SearchGateway = Depends(lambda: app.state.gateway)):
    return gateway.provider_manager.get_provider_status()
