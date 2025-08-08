from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx
import os

app = FastAPI()

# Correctly point to the search-agent service
SEARCH_AGENT_URL = os.environ.get("SEARCH_AGENT_URL", "http://search-agent-1:8001")

class SearchRequest(BaseModel):
    query: str

@app.post("/api/search")
async def search(request: SearchRequest):
    """Handles standard, non-streaming search requests."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{SEARCH_AGENT_URL}/search", json=request.dict())
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
    except httpx.RequestError as e:
        raise HTTPException(status_code=503, detail=f"Service unavailable: {e}")

@app.post("/api/search/stream")
async def stream_search(request: SearchRequest):
    """Handles streaming search requests for the interactive chat UI."""
    async def stream_generator():
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                async with client.stream("POST", f"{SEARCH_AGENT_URL}/search/stream", json=request.dict()) as response:
                    response.raise_for_status()
                    async for chunk in response.aiter_bytes():
                        yield chunk
        except httpx.HTTPStatusError as e:
            # Yield a JSON error message that the frontend can parse
            error_message = f'{{"type": "error", "payload": "{e.response.text}"}}'
            yield f"data: {error_message}\n\n".encode('utf-8')
        except httpx.RequestError as e:
            error_message = f'{{"type": "error", "payload": "Could not connect to the search agent."}}'
            yield f"data: {error_message}\n\n".encode('utf-8')

    return StreamingResponse(stream_generator(), media_type="text/event-stream")

@app.get("/")
def read_root():
    return {"message": "Web UI/API is running and ready to proxy requests."}
