#
# services/search-agent/providers/provider_manager.py
#
import os
import httpx
import time
import logging
import json
import re
from typing import List, Dict

from common.models import SearchProvider, SearchResult, SearchRequest
from utils.system_components import MetricsCollector, CircuitBreaker

logger = logging.getLogger(__name__)

class SearchProviderManager:
    """Manages connections and requests to various search providers with resilience."""
    
    def __init__(self, metrics: MetricsCollector, circuit_breaker: CircuitBreaker):
        self.metrics = metrics
        self.circuit_breaker = circuit_breaker
        self.providers = {
            # --- Free Providers ---
            SearchProvider.WHOOGLE: {
                "url": os.environ.get("WHOOGLE_URL", "http://whoogle:5000"),
                "enabled": True, 
                "weight": 1.0,
                "parser": self._parse_whoogle
            },
            SearchProvider.SEARXNG: {
                "url": os.environ.get("SEARXNG_URL", "http://searxng:8080"),
                "enabled": True, 
                "weight": 1.0,
                "parser": self._parse_searxng
            },
            SearchProvider.YACY: {
                "url": os.environ.get("YACY_URL", "http://yacy:8090"),
                "enabled": os.environ.get("YACY_ENABLED", "true").lower() == "true", 
                "weight": 0.8,
                "parser": self._parse_yacy
            },
            SearchProvider.WIKIPEDIA: {
                "url": "https://en.wikipedia.org/w/api.php",
                "enabled": True, 
                "weight": 1.1,
                "parser": self._parse_wikipedia
            },

            # --- Paid/Key-Required Providers ---
            SearchProvider.BRAVE: {
                "url": "https://api.search.brave.com/res/v1/web/search",
                "api_key": os.environ.get("BRAVE_API_KEY"),
                "enabled": bool(os.environ.get("BRAVE_API_KEY")), 
                "weight": 1.2,
                "parser": self._parse_brave
            },
            SearchProvider.QWANT: {
                "url": "https://api.qwant.com/v3/search/web",
                "api_key": os.environ.get("QWANT_API_KEY"),
                "enabled": bool(os.environ.get("QWANT_API_KEY")), 
                "weight": 0.9,
                "parser": self._parse_qwant
            },
            SearchProvider.GOOGLE_CSE: {
                "url": "https://www.googleapis.com/customsearch/v1",
                "api_key": os.environ.get("GOOGLE_CSE_KEY"),
                "cx": os.environ.get("GOOGLE_CSE_CX"),
                "enabled": bool(os.environ.get("GOOGLE_CSE_KEY") and os.environ.get("GOOGLE_CSE_CX")),
                "weight": 1.3,
                "parser": self._parse_google_cse
            }
        }
        
    def get_enabled_providers(self) -> List[SearchProvider]:
        return [name for name, config in self.providers.items() if config.get("enabled")]
        
    def get_provider_status(self) -> Dict[str, str]:
        return { name.value: "enabled" if config.get("enabled") else "disabled" for name, config in self.providers.items() }
        
    async def query_provider(self, client: httpx.AsyncClient, provider: SearchProvider, query: str, request: SearchRequest) -> List[SearchResult]:
        provider_config = self.providers.get(provider)
        if not provider_config or not provider_config.get("enabled"):
            return []

        if await self.circuit_breaker.is_open(provider.value):
            logger.warning(f"Circuit breaker is open for {provider.value}. Skipping request.")
            return []
            
        start_time = time.time()
        success = False
        results = []
        response_text = ""

        try:
            params: Dict[str, any] = {"q": query}
            headers = {}
            url = provider_config["url"]

            # Provider-specific parameter and header setup
            if provider == SearchProvider.WHOOGLE: url = f"{url}/search"; params["format"] = "json" # <--- CRITICAL FIX
            elif provider == SearchProvider.SEARXNG: url = f"{url}/search"; params["format"] = "json"
            elif provider == SearchProvider.YACY: url = f"{url}/yacysearch.json"; params.update({"maximumRecords": 20, "fmt": "json"})
            elif provider == SearchProvider.BRAVE: headers["X-Subscription-Token"] = provider_config["api_key"]
            elif provider == SearchProvider.QWANT: params.update({"count": 20, "offset": 0}); headers["User-Agent"] = "SearxNG"
            elif provider == SearchProvider.WIKIPEDIA: params = {"action": "query", "list": "search", "srsearch": query, "format": "json"}
            elif provider == SearchProvider.GOOGLE_CSE: params.update({"key": provider_config["api_key"], "cx": provider_config["cx"]})

            response = await client.get(url, params=params, headers=headers, timeout=request.timeout)
            response_text = response.text
            response.raise_for_status()
            raw_results = response.json()

            # Extract results from nested structures
            if provider == SearchProvider.WHOOGLE: raw_results = raw_results.get("results", [])
            elif provider == SearchProvider.SEARXNG: raw_results = raw_results.get("results", [])
            elif provider == SearchProvider.YACY: raw_results = raw_results.get("channels", [{}])[0].get("items", [])
            elif provider == SearchProvider.BRAVE: raw_results = raw_results.get("web", {}).get("results", [])
            elif provider == SearchProvider.QWANT: raw_results = raw_results.get("data", {}).get("result", {}).get("items", [])
            elif provider == SearchProvider.WIKIPEDIA: raw_results = raw_results.get("query", {}).get("search", [])
            elif provider == SearchProvider.GOOGLE_CSE: raw_results = raw_results.get("items", [])

            results = provider_config["parser"](raw_results, provider_config.get("weight", 1.0))
            success = True

        except json.JSONDecodeError:
            logger.error(f"JSONDecodeError for {provider.value}. Response: {response_text[:200]}...")
            success = False
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            logger.warning(f"Request failed for {provider.value}: {e}")
            success = False
        except Exception as e:
            logger.error(f"Unexpected error querying {provider.value}: {e}", exc_info=True)
            success = False
            
        if success:
            await self.circuit_breaker.record_success(provider.value)
        else:
            await self.circuit_breaker.record_failure(provider.value)
            
        return results
    
    # --- Parsers ---
    def _parse_whoogle(self, r, w): return [SearchResult(title=i.get("title",""), url=i.get("url",""), description=i.get("snippet",""), source="whoogle", confidence=w) for i in r if i.get("url")]
    def _parse_searxng(self, r, w): return [SearchResult(title=i.get("title",""), url=i.get("url",""), description=i.get("content",""), source="searxng", confidence=w) for i in r if i.get("url")]
    def _parse_yacy(self, r, w): return [SearchResult(title=i.get("title",""), url=i.get("link",""), description=i.get("description",""), source="yacy", confidence=w*0.8) for i in r if i.get("link")]
    def _parse_brave(self, r, w): return [SearchResult(title=i.get("title",""), url=i.get("url",""), description=i.get("description",""), source="brave", confidence=w*1.1) for i in r if i.get("url")]
    def _parse_qwant(self, r, w): return [SearchResult(title=i.get("title",""), url=i.get("url",""), description=i.get("description",""), source="qwant", confidence=w) for i in r if i.get("url")]
    def _parse_google_cse(self, r, w): return [SearchResult(title=i.get("title",""), url=i.get("link",""), description=i.get("snippet",""), source="google_cse", confidence=w*1.2) for i in r if i.get("link")]
    def _parse_wikipedia(self, r, w):
        return [SearchResult(title=i.get("title",""), url=f"https://en.wikipedia.org/wiki/{i.get('title','').replace(' ','_')}", description=re.sub(r'<.*?>','',i.get("snippet","")), source="wikipedia", confidence=w*1.2) for i in r]
