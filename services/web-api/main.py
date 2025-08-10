#
# services/web-api/main.py (Refactored for Decoupling & Resilience)
#
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx
import os
import json
from typing import List, Optional
import logging

# --- Basic Logger Configuration ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("web_api_orchestrator")

app = FastAPI(title="DeepSearch Web API (Orchestrator)", version="6.0.0")

# --- Service URLs ---
SEARCH_AGENT_URL = os.environ.get("SEARCH_AGENT_URL", "http://search-agent:8001")
LLM_GATEWAY_URL = os.environ.get("LLM_GATEWAY_URL", "http://llm-gateway:8080")
SEARCH_GATEWAY_URL = os.environ.get("SEARCH_GATEWAY_URL", "http://search-gateway:8002")

# --- Pydantic Models for API Contracts ---
class ClientSearchRequest(BaseModel):
    query: str
    llm_provider: Optional[str] = None

class CompletionRequest(BaseModel):
    messages: List[dict]
    provider: Optional[str] = None

# --- Orchestration Logic ---

async def search_and_synthesize_stream(request: ClientSearchRequest):
    """Orchestrates the search and synthesis process with robust stream proxying."""
    # 1. Get search results from the gateway
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            gateway_payload = {"query": request.query}
            gateway_response = await client.post(f"{SEARCH_GATEWAY_URL}/search", json=gateway_payload)
            gateway_response.raise_for_status()
            sources = gateway_response.json()
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.error(f"Failed to get results from Search Gateway: {e}")
        error_payload = {"content": "Error: Could not retrieve search results.", "finished": True, "sources": []}
        yield f"data: {json.dumps(error_payload)}\n\n".encode('utf-8')
        return

    # 2. Prepare to stream synthesis from the agent
    agent_payload = {
        "query": request.query,
        "llm_provider": request.llm_provider,
        "sources": sources
    }

    try:
        async with httpx.AsyncClient(timeout=180.0) as client:
            async with client.stream("POST", f"{SEARCH_AGENT_URL}/synthesize/stream", json=agent_payload) as agent_response:
                agent_response.raise_for_status()
                async for chunk in agent_response.aiter_bytes():
                    yield chunk

    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.error(f"Failed to stream from Synthesizer Agent: {e}")
        error_payload = {"content": "Error: The answer generation service is unavailable.", "finished": True, "sources": sources}
        yield f"data: {json.dumps(error_payload)}\n\n".encode('utf-8')

# --- API Endpoints ---

@app.post("/api/search/stream")
async def stream_search(request: ClientSearchRequest):
    """Handles streaming search requests from the client."""
    return StreamingResponse(search_and_synthesize_stream(request), media_type="text/event-stream")

@app.post("/api/completion/stream")
async def stream_completion(request: CompletionRequest):
    """Proxies direct chat completion requests to the LLM Gateway."""
    payload = request.dict(exclude_unset=True)
    async def stream_proxy():
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                async with client.stream("POST", f"{LLM_GATEWAY_URL}/completion", json=payload) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        yield chunk
        except Exception as e:
            logger.error(f"LLM Gateway stream proxy failed: {e}")
            error_payload = {"type": "error", "payload": str(e)}
            yield f"data: {json.dumps(error_payload)}\n\n".encode('utf-8')

    return StreamingResponse(stream_proxy(), media_type="text/event-stream")

@app.get("/api/providers")
async def get_providers():
    """Fetches the list of available LLM providers from the gateway."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{LLM_GATEWAY_URL}/providers")
            response.raise_for_status()
            return response.json()
    except httpx.RequestError as e:
        logger.error(f"Could not fetch providers from LLM Gateway: {e}")
        raise HTTPException(status_code=503, detail="LLM Gateway unavailable")

@app.get("/")
async def read_root():
    return {"message": "DeepSearch Web API Orchestrator is operational."}
