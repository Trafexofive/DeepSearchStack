"""Synthesis stage — LLM generation via inference-gateway with streaming."""
import json
import logging
from typing import List, Optional, AsyncIterator

from models import SearchResult, ScrapedContent, VectorChunk
from config import config

logger = logging.getLogger("deepsearch.synthesis")


async def stream(
    client,
    query: str,
    context: str,
    inference_gateway_url: str,
    llm_provider: Optional[str] = None,
    temperature: Optional[float] = None,
) -> AsyncIterator[str]:
    """Stream LLM synthesis via inference-gateway (OpenAI-compatible API)."""
    model = config.synthesis_config.get("model", "deepseek-chat")
    temp = temperature or config.synthesis_config.get("temperature", 0.3)
    system_prompt = config.synthesis_config.get("system_prompt", "")
    max_tokens = config.synthesis_config.get("max_tokens", 4096)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"User Query: {query}\n\nSearch Context:\n{context}"},
    ]

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temp,
        "max_tokens": max_tokens,
        "stream": True,
    }

    headers = {"Content-Type": "application/json"}
    if llm_provider:
        headers["x-provider"] = llm_provider

    try:
        async with client.stream(
            "POST",
            f"{inference_gateway_url}/v1/chat/completions",
            json=payload,
            headers=headers,
            timeout=config.synthesis_config.get("timeout", 120.0),
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        delta = data["choices"][0].get("delta", {})
                        if delta.get("content"):
                            yield delta["content"]
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
    except Exception as e:
        logger.error(f"LLM synthesis error: {e}")
        yield f"\n\n**Error during synthesis:** {str(e)}"


def build_context(
    chunks_or_results: List,
    scraped_content: Optional[List[ScrapedContent]] = None,
) -> str:
    """Build context string for LLM from RAG chunks or search results."""
    context_parts = []

    if chunks_or_results and isinstance(chunks_or_results[0], VectorChunk):
        for i, chunk in enumerate(chunks_or_results, 1):
            context_parts.append(
                f"Source [{i}]: {chunk.title}\n"
                f"URL: {chunk.url}\n"
                f"Content: {chunk.content}\n"
            )
    else:
        for i, result in enumerate(chunks_or_results, 1):
            content = getattr(result, "description", "")
            if scraped_content:
                for scraped in scraped_content:
                    if scraped.url == result.url and scraped.success:
                        content = scraped.content[:2000]
                        break
            context_parts.append(
                f"Source [{i}]: {result.title}\n"
                f"URL: {result.url}\n"
                f"Content: {content}\n"
            )

    return "\n\n".join(context_parts)
