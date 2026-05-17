"""Topic research via DeepSearch Web API + warehouse."""
import logging
import httpx

log = logging.getLogger("blog_generator.research")

WEB_API_URL = "http://dss-web-api:8014"
WEB_API_FALLBACK = "http://localhost:8014"
WAREHOUSE_URL = "http://dss-knowledge-warehouse:8009"


async def research_topic(topic: str, max_results: int = 5) -> dict:
    """Query DeepSearch aggregate for sources and consensus facts."""
    log.info(f"Researching via web-api: {topic[:80]}")
    for url in [WEB_API_URL, WEB_API_FALLBACK]:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"{url}/api/aggregate",
                    json={"query": topic, "max_results": max_results, "reconcile": True, "include_warehouse": True},
                )
                resp.raise_for_status()
                data = resp.json()
                return {
                    "sources": [{"title": s["title"], "url": s["url"], "description": s.get("description","")} for s in data.get("sources", [])],
                    "consensus": [c["claim"] for c in data.get("consensus", [])],
                    "answer": data.get("synthesis", ""),
                    "query": topic,
                }
        except httpx.ConnectError:
            log.warning(f"Web-API unreachable at {url}")
        except Exception as e:
            log.error(f"Web-API error: {e}")
            break
    return {"sources": [], "consensus": [], "answer": "", "query": topic}


async def fetch_warehouse_context(topic: str, limit: int = 5) -> str:
    """Search warehouse for relevant context snippets."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{WAREHOUSE_URL}/search",
                params={"q": topic, "limit": limit},
            )
            resp.raise_for_status()
            results = resp.json()
            if not results:
                return ""
            lines = []
            for r in results[:limit]:
                title = r.get("title", "")
                snippet = r.get("snippet", "")[:300]
                domain = r.get("source_domain", "")
                if title:
                    lines.append(f"- {title} ({domain}): {snippet}")
            return "\n".join(lines)
    except Exception:
        return ""
