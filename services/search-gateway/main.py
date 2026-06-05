
#
# services/search-gateway/main.py
#
import os
import time
import httpx
import asyncio
import logging
from fastapi import FastAPI, Depends
from contextlib import asynccontextmanager
import redis.asyncio as redis
from typing import List

# Corrected relative imports for the new service structure
from .common.models import SearchGatewayRequest, SearchResult
from .providers.provider_manager import SearchProviderManager
from .ranking.result_ranker import ResultRanker
from .utils.system_components import MetricsCollector, CircuitBreaker

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("search_gateway")

# Per-provider timeout (audit N5): if a single provider is slow, the
# whole gather() waits for it. Wrapping each in asyncio.wait_for cuts
# off the slow ones so fast providers don't get held up.
PROVIDER_TIMEOUT_DEFAULT = float(os.environ.get("PROVIDER_TIMEOUT", "4.0"))


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

    async def search(self, request: SearchGatewayRequest) -> List[SearchResult]:
        start_time = time.time()
        # Per-provider timeout capped at the request-level timeout.
        per_provider_timeout = min(PROVIDER_TIMEOUT_DEFAULT, request.timeout)

        async with httpx.AsyncClient(timeout=request.timeout) as client:
            tasks = [
                self._query_with_timeout(client, p, request.query, request, per_provider_timeout)
                for p in request.providers
            ]
            results = await asyncio.gather(*tasks)

        all_results = [res for pres in results if pres for res in pres]
        logger.info(f"Got {len(all_results)} total results from {len(request.providers)} providers.")

        fused_results = self._fuse_and_deduplicate(all_results)
        ranked_results = self.ranker.rank_results(request.query, fused_results, request.sort_by)
        limited_results = ranked_results[:request.max_results]

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
