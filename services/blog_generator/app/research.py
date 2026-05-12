"""Topic research via DeepSearch service."""
import logging
import httpx

log = logging.getLogger("blog_generator.research")

DEEPSEARCH_URL = "http://deepsearch:8001"
DEEPSEARCH_URL_FALLBACK = "http://localhost:8007"


async def research_topic(topic: str, max_results: int = 5) -> dict:
    """Query DeepSearch for sources and a research summary.

    Returns: {"sources": [...], "answer": str, "query": str}
    """
    log.info(f"Researching topic via deepsearch: {topic[:80]}")

    url = DEEPSEARCH_URL
    for attempt_url in [DEEPSEARCH_URL, DEEPSEARCH_URL_FALLBACK]:
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    f"{attempt_url}/deepsearch/quick",
                    json={"query": topic, "max_results": max_results},
                )
                resp.raise_for_status()
                return resp.json()
        except httpx.ConnectError:
            log.warning(f"DeepSearch unreachable at {attempt_url}, trying fallback")
        except Exception as e:
            log.error(f"DeepSearch error at {attempt_url}: {e}")
            break

    return {"sources": [], "answer": "", "query": topic}
