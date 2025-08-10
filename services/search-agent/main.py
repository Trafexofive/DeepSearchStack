#
# services/search-agent/main.py (Definitive Resilience Fix)
#
import os
import httpx
import asyncio
import logging
import json
from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import StreamingResponse
from contextlib import asynccontextmanager
from typing import List

from .common.models import SynthesizeRequest, StreamingChunk, Message, SearchResult
from .common.llm_client import LLMClient

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("synthesizer_agent")

class SynthesizerAgent:
    def __init__(self):
        self.llm_client = LLMClient()
        self.version = "9.0.0"

    async def _yield_synthesis_chunks(self, request: SynthesizeRequest, synthesis_provider: str):
        """The 'happy path' generator. An exception here will be caught by the calling generator."""
        context = "".join(f"Source [{i+1}]: {res.title}\nURL: {res.url}\nContent: {res.description}\n\n" for i, res in enumerate(request.sources))
        messages = [
            Message(role="system", content="You are a world-class research assistant. Your sole purpose is to answer the user's query accurately and concisely based *only* on the provided search context. Synthesize the information from the sources into a coherent answer. Cite the sources using bracket notation, like [1], [2], etc., at the end of every sentence or claim that is supported by a source. If the provided context does not contain enough information to answer the query, you must state that you were unable to find a definitive answer."),
            Message(role="user", content=f"User Query: {request.query}\n\nSearch Context:\n{context}")
        ]
        
        content_streamed = False
        async for chunk in self.llm_client.get_streaming_completion(messages, provider=synthesis_provider):
            content_streamed = True
            yield f'data: {json.dumps(StreamingChunk(content=chunk, finished=False).dict())}\n\n'
        
        if not content_streamed:
            raise ValueError("LLM provider returned an empty stream.")

        yield f'data: {json.dumps(StreamingChunk(content="", finished=True, sources=request.sources).dict())}\n\n'

    async def _generate_and_handle_stream(self, request: SynthesizeRequest):
        """A single, robust generator that handles the entire process, including errors."""
        synthesis_provider = request.llm_provider or "ollama"
        try:
            async for chunk in self._yield_synthesis_chunks(request, synthesis_provider):
                yield chunk
        except Exception as e:
            logger.error(f"A critical error occurred during synthesis stream: {e}")
            error_content = "\n\n**Error during synthesis:** An issue occurred while generating the answer."
            error_chunk = StreamingChunk(content=error_content, finished=True, sources=request.sources)
            yield f'data: {json.dumps(error_chunk.dict())}\n\n'

    def synthesize(self, request: SynthesizeRequest) -> StreamingResponse:
        """Prepares and returns the streaming response, handling cases with no sources."""
        if not request.sources:
            async def empty_streamer(answer: str):
                yield f'data: {json.dumps(StreamingChunk(content=answer, finished=True, sources=[]).dict())}\n\n'
            return StreamingResponse(empty_streamer("No sources provided to synthesize an answer."), media_type="text/event-stream")
        
        return StreamingResponse(self._generate_and_handle_stream(request), media_type="text/event-stream")

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.agent = SynthesizerAgent()
    yield

app = FastAPI(title="DeepSearch Synthesizer Agent", version="9.0.0", lifespan=lifespan)

@app.post("/synthesize/stream")
async def synthesize_stream_endpoint(request: SynthesizeRequest, agent: SynthesizerAgent = Depends(lambda: app.state.agent)):
    return agent.synthesize(request)
    
@app.get("/health")
async def health(agent: SynthesizerAgent = Depends(lambda: app.state.agent)):
    return {"status": "healthy", "version": agent.version}
