#
# services/search-agent/main.py
#
import os
import time
import httpx
import asyncio
import logging
import json
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager
import redis.asyncio as redis
import traceback
from datetime import datetime
from typing import List, Union, Dict

from common.models import *
from utils.system_components import *
from ranking.result_ranker import ResultRanker
from providers.provider_manager import SearchProviderManager
from common.llm_client import LLMClient, Message

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("search_agent")

class SearchGateway:
    def __init__(self, redis_client: redis.Redis):
        self.llm_client = LLMClient()
        self.provider_manager = SearchProviderManager(MetricsCollector(), CircuitBreaker(redis_client))
        self.ranker = ResultRanker()
        self.version = "2.5.2"
        self.start_time = time.time()

    async def _generate_streaming_response(self, query: str, context: str, sources: List[SearchResult], llm_provider: str | None):
        messages = [
            Message(role="system", content="You are a helpful research assistant..."),
            Message(role="user", content=f"User Query: {query}\n\nSearch Context:\n{context}")
        ]
        try:
            async for chunk in self.llm_client.get_streaming_completion(messages=messages, provider=llm_provider):
                yield f'data: {json.dumps(StreamingChunk(content=chunk, finished=False).dict())}\n\n'
            
            final_sources = [source.dict() for source in sources]
            yield f'data: {json.dumps({"content": "", "finished": True, "sources": final_sources})}\n\n'
        except Exception as e:
            logger.error(f"Streaming error: {e}")
            error_content = f"\nError during synthesis: {e}"
            # FIX: Ensure sources are properly serialized to dicts before JSON dumping.
            final_sources = [source.dict() for source in sources]
            error_chunk = {"content": error_content, "finished": True, "sources": final_sources}
            yield f'data: {json.dumps(error_chunk)}\n\n'

    async def search(self, request: SearchRequest) -> Union[GatewayResponse, StreamingResponse]:
        start_time = time.time()
        async with httpx.AsyncClient(timeout=request.timeout) as client:
            tasks = [self.provider_manager.query_provider(client, p, request.query, request) for p in request.providers]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        
        all_results = [res for pres in results if isinstance(pres, list) for res in pres]
        fused_results = self._fuse_and_deduplicate(all_results)
        ranked_results = self.ranker.rank_results(request.query, fused_results, request.sort_by)
        limited_results = ranked_results[:request.max_results]

        if not limited_results:
            answer = "No relevant information found."
            if request.stream:
                async def empty_stream(): yield f'data: {json.dumps({"content": answer, "finished": True, "sources": []})}\n\n'
                return StreamingResponse(empty_stream(), media_type="text/event-stream")
            return GatewayResponse(answer=answer, sources=[], execution_time=time.time() - start_time, query_time=datetime.now().isoformat(), search_providers_used=[p.value for p in request.providers], total_results_found=0)
            
        context = "".join(f"Source [{i+1}]: {res.title}\\nURL: {res.url}\\nContent: {res.description}\\n\\n" for i, res in enumerate(limited_results))
        
        if request.stream:
            return StreamingResponse(self._generate_streaming_response(request.query, context, limited_results, request.llm_provider), media_type="text/event-stream")
        
        try:
            messages = [Message(role="system", content="You are a research assistant..."), Message(role="user", content=f"Query: {request.query}\\nContext:\\n{context}")]
            answer = await self.llm_client.get_completion(messages=messages, provider=request.llm_provider)
            return GatewayResponse(answer=answer, sources=limited_results, execution_time=time.time() - start_time, query_time=datetime.now().isoformat(), search_providers_used=[p.value for p in request.providers], total_results_found=len(all_results))
        except Exception as e:
            logger.error(f"LLM error: {e}\\n{traceback.format_exc()}")
            raise HTTPException(status_code=502, detail=f"Error synthesizing answer: {e}")

    def _fuse_and_deduplicate(self, all_results: List[SearchResult]) -> List[SearchResult]:
        unique_urls = {r.url: r for r in all_results if r.url}
        return list(unique_urls.values())

@asynccontextmanager
async def lifespan(app: FastAPI):
    redis_client = redis.from_url(os.environ.get("REDIS_URL", "redis://redis:6379/0"))
    app.state.search_gateway = SearchGateway(redis_client)
    yield
    await redis_client.close()

app = FastAPI(title="DeepSearch Agent", version="2.5.2", lifespan=lifespan)

def get_gateway(request: Request) -> SearchGateway:
    return request.app.state.search_gateway

@app.post("/search", response_model=GatewayResponse, tags=["Search"])
async def search_endpoint(request: SearchRequest, gateway: SearchGateway = Depends(get_gateway)):
    request.stream = False
    return await gateway.search(request)

@app.post("/search/stream", tags=["Search"])
async def search_stream_endpoint(request: SearchRequest, gateway: SearchGateway = Depends(get_gateway)):
    request.stream = True
    return await gateway.search(request)
    
@app.get("/health", status_code=200, tags=["System"])
async def health_check():
    return {"status": "healthy", "version": "2.5.2"}

@app.get("/providers", tags=["System"], response_model=Dict[str, Dict[str, str]])
async def list_providers(gateway: SearchGateway = Depends(get_gateway)):
    return {"providers": gateway.provider_manager.get_provider_status()}
