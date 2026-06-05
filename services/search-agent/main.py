#
# services/search-agent/main.py (Definitive Resilience Fix)
#
import asyncio
import json
import logging
import os
import re
from contextlib import asynccontextmanager
from typing import List

import httpx
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import StreamingResponse

from .common.llm_client import LLMClient
from .common.models import Message, SearchResult, StreamingChunk, SynthesizeRequest

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("synthesizer_agent")


# Pattern for [N] citation marks. Matches digit-only bracketed numbers.
_CITATION_RE = re.compile(r"\[(\d+)\]")


def validate_citations(content: str, num_sources: int) -> dict:
    """Parse [N] citations from LLM output and detect out-of-range ones.

    LLMs occasionally hallucinate citations — e.g., citing [7] when only
    5 sources were provided, or citing [0]. This is a known failure mode
    that makes the synthesis look authoritative but is in fact wrong.

    Returns:
      {
        "total":       int  # total [N] tokens found
        "valid":       list[int]  # in-range citation numbers (1..num_sources), in order
        "invalid":     list[int]  # out-of-range citation numbers, deduped, in first-seen order
        "invalid_strs": list[str]  # the literal [N] strings the user saw, deduped
      }
    """
    found = _CITATION_RE.findall(content)
    total = len(found)
    valid: list[int] = []
    invalid: list[int] = []
    invalid_strs: list[str] = []
    seen_invalid: set[int] = set()
    for s in found:
        n = int(s)
        if 1 <= n <= num_sources:
            valid.append(n)
        else:
            if n not in seen_invalid:
                seen_invalid.add(n)
                invalid.append(n)
                invalid_strs.append(f"[{n}]")
    return {
        "total": total,
        "valid": valid,
        "invalid": invalid,
        "invalid_strs": invalid_strs,
    }


class SynthesizerAgent:
    def __init__(self):
        self.llm_client = LLMClient()
        self.version = "9.0.0"

    async def _yield_synthesis_chunks(
        self, request: SynthesizeRequest, synthesis_provider: str
    ):
        """The 'happy path' generator. An exception here will be caught by the calling generator."""
        context = "".join(
            f"Source [{i+1}]: {res.title}\nURL: {res.url}\nContent: {res.description}\n\n"
            for i, res in enumerate(request.sources)
        )
        messages = [
            Message(
                role="system",
                content="You are a world-class research assistant. Your sole purpose is to answer the user's query accurately and concisely based *only* on the provided search context. Synthesize the information from the sources into a coherent answer. Cite the sources using bracket notation, like [1], [2], etc., at the end of every sentence or claim that is supported by a source. If the provided context does not contain enough information to answer the query, you must state that you were unable to find a definitive answer.",
            ),
            Message(
                role="user",
                content=f"User Query: {request.query}\n\nSearch Context:\n{context}",
            ),
        ]

        # Resolve which model name to send to the gateway.
        # `llm_model` is the preferred field — it's where 'virtual/free-coder'
        # (the cascade) lives. Fall back to `llm_provider` (legacy), then
        # to the cascade default. The previous code sent `llm_provider`
        # directly, which bypassed the cascade entirely and hit deepseek
        # (out of credits) → 402 → "peer closed connection".
        synthesis_model = (
            request.llm_model
            or request.llm_provider
            or "virtual/free-coder"
        )

        content_streamed = False
        accumulated: list[str] = []
        async for chunk in self.llm_client.get_streaming_completion(
            messages, provider=synthesis_model
        ):
            content_streamed = True
            accumulated.append(chunk)
            yield f"data: {json.dumps(StreamingChunk(content=chunk, finished=False).dict())}\n\n"

        if not content_streamed:
            raise ValueError("LLM provider returned an empty stream.")

        # Citation validation: detect hallucinated [N] marks the LLM
        # output that don't refer to a real source. LLMs occasionally
        # invent citations; this surfaces them to the user.
        full_content = "".join(accumulated)
        report = validate_citations(full_content, len(request.sources))
        if report["invalid"]:
            logger.warning(
                "Citation validation: %d invalid of %d total — %s",
                len(report["invalid"]),
                report["total"],
                report["invalid_strs"],
            )
            warning_text = (
                f"\n\n_Note: {len(report['invalid'])} citation(s) in this "
                f"response do not refer to a provided source "
                f"({', '.join(report['invalid_strs'])}). The LLM may have "
                f"hallucinated these. Only the numbered sources in the list "
                f"below are real._"
            )
            yield f"data: {json.dumps(StreamingChunk(content=warning_text, finished=False).dict())}\n\n"

        yield f'data: {json.dumps(StreamingChunk(content="", finished=True, sources=request.sources).dict())}\n\n'

    async def _generate_and_handle_stream(self, request: SynthesizeRequest):
        """A single, robust generator that handles the entire process, including errors."""
        # synthesis_provider is kept for log/error messages; the actual
        # model resolution happens inside _yield_synthesis_chunks.
        synthesis_provider = request.llm_provider or "virtual/free-coder"
        try:
            async for chunk in self._yield_synthesis_chunks(
                request, synthesis_provider
            ):
                yield chunk
        except Exception as e:
            logger.exception("A critical error occurred during synthesis stream")
            error_type = type(e).__name__
            error_summary = str(e)[:200] if str(e) else "(no message)"
            error_content = (
                f"\n\n**Error during synthesis:** `{error_type}: {error_summary}`.\n"
                f"Check the search-agent container logs for the full traceback."
            )
            error_chunk = StreamingChunk(
                content=error_content, finished=True, sources=request.sources
            )
            yield f"data: {json.dumps(error_chunk.dict())}\n\n"

    def synthesize(self, request: SynthesizeRequest) -> StreamingResponse:
        """Prepares and returns the streaming response, handling cases with no sources."""
        if not request.sources:

            async def empty_streamer(answer: str):
                yield f"data: {json.dumps(StreamingChunk(content=answer, finished=True, sources=[]).dict())}\n\n"

            return StreamingResponse(
                empty_streamer("No sources provided to synthesize an answer."),
                media_type="text/event-stream",
            )

        return StreamingResponse(
            self._generate_and_handle_stream(request), media_type="text/event-stream"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.agent = SynthesizerAgent()
    yield


app = FastAPI(title="DeepSearch Synthesizer Agent", version="9.0.0", lifespan=lifespan)


@app.post("/synthesize/stream")
async def synthesize_stream_endpoint(
    request: SynthesizeRequest,
    agent: SynthesizerAgent = Depends(lambda: app.state.agent),
):
    return agent.synthesize(request)


@app.get("/health")
async def health(agent: SynthesizerAgent = Depends(lambda: app.state.agent)):
    return {"status": "healthy", "version": agent.version}
