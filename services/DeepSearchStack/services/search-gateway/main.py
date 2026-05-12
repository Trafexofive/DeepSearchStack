
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

class SearchGateway:
    def __init__(self, redis_client: redis.Redis):
        self.provider_manager = SearchProviderManager(MetricsCollector(), CircuitBreaker(redis_client))
        self.ranker = ResultRanker()
        self.version = "1.0.0"

    async def search(self, request: SearchGatewayRequest) -> List[SearchResult]:
        start_time = time.time()
        
        async with httpx.AsyncClient(timeout=request.timeout) as client:
            tasks = [self.provider_manager.query_provider(client, p, request.query, request) for p in request.providers]
            results = await asyncio.gather(*tasks)
        
        all_results = [res for pres in results if pres for res in pres]
        logger.info(f"Got {len(all_results)} total results from {len(request.providers)} providers.")

        fused_results = self._fuse_and_deduplicate(all_results)
        ranked_results = self.ranker.rank_results(request.query, fused_results, request.sort_by)
        limited_results = ranked_results[:request.max_results]

        execution_time = time.time() - start_time
        logger.info(f"Search completed in {execution_time:.2f} seconds.")
        
        return limited_results

    def _fuse_and_deduplicate(self, all_results: List[SearchResult]) -> List[SearchResult]:
        return list({result.url: result for result in all_results if result.url}.values())

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

@app.get("/providers")
async def list_providers(gateway: SearchGateway = Depends(lambda: app.state.gateway)):
    return gateway.provider_manager.get_provider_status()
