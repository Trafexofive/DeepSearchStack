"""Search stage — parallel multi-provider search via search-gateway."""
import logging
from typing import List

from models import SearchResult, DeepSearchRequest
from config import config

logger = logging.getLogger("deepsearch.search")


async def execute(client, request: DeepSearchRequest, search_gateway_url: str) -> List[SearchResult]:
    """Query search providers in parallel via the search gateway service."""
    providers = request.providers or config.search_config.get("default_providers", [])
    max_results = request.max_results or config.search_config.get("max_results", 100)

    payload = {
        "query": request.query,
        "providers": providers,
        "max_results": max_results,
        "sort_by": request.sort_by,
        "timeout": config.search_config.get("timeout", 30.0),
    }

    try:
        response = await client.post(
            f"{search_gateway_url}/search",
            json=payload,
            timeout=config.search_config.get("timeout", 30.0),
        )
        response.raise_for_status()
        return [SearchResult(**r) for r in response.json()]
    except Exception as e:
        logger.error(f"Search gateway error: {e}")
        return []
