#
# services/search-agent/providers/provider_manager.py
#
import os
import httpx
import time
import logging
import json
import re
import html
from typing import List, Dict, Optional
import xml.etree.ElementTree as ET

# dictionary sources, oxford, wikipedia, etc. since this will evolve later on to include more providers.
# FUTURE: Add As much free providers as possible, including dictionary sources, oxford, wikipedia, etc. We might even store some of the data in a local database for faster access (wikipedia can just be fully downloaded the same for similar sites). This will probably go hand in hand with the future scraper service. Where our agents and services rely on curated data from the scraper service, which will be used to populate the local database. This will allow us to have a more robust and reliable search experience for our users (The paypal mafia, aka. The Boys).

# MODIFIED: Corrected relative import paths
from search_gateway.common.models import SearchProvider, SearchResult, SearchGatewayRequest as SearchRequest
from search_gateway.utils.system_components import MetricsCollector, CircuitBreaker

logger = logging.getLogger("providers.provider_manager")

class SearchProviderManager:
    """Manages connections and requests to various free, high-quality search providers."""
    
    def __init__(self, metrics: MetricsCollector, circuit_breaker: CircuitBreaker):
        self.metrics = metrics
        self.circuit_breaker = circuit_breaker
        self.providers = {
            SearchProvider.WHOOGLE: {
                "url": os.environ.get("WHOOGLE_URL", "http://whoogle:5000"),
                "weight": 1.0, "parser": self._parse_whoogle
            },
            SearchProvider.SEARXNG: {
                "url": os.environ.get("SEARXNG_URL", "http://searxng:8080"),
                "weight": 1.0, "parser": self._parse_searxng
            },
            SearchProvider.YACY: {
                "url": os.environ.get("YACY_URL", "http://yacy:8090"),
                "weight": 0.8, "parser": self._parse_yacy
            },
            SearchProvider.WIKIPEDIA: {
                "url": "https://en.wikipedia.org/w/api.php",
                "weight": 1.2, "parser": self._parse_wikipedia
            },
            SearchProvider.DUCKDUCKGO: {
                "url": "https://api.duckduckgo.com/",
                "weight": 1.1, "parser": self._parse_duckduckgo
            },
            SearchProvider.STACKEXCHANGE: {
                "url": "https://api.stackexchange.com/2.3/search/advanced",
                "weight": 1.2, "parser": self._parse_stackexchange
            },
            SearchProvider.ARXIV: {
                "url": "http://export.arxiv.org/api/query",
                "weight": 1.2, "parser": self._parse_arxiv
            }
        }
        
    def get_provider_status(self) -> Dict[str, str]:
        return { name.value: "enabled" for name in self.providers }
        
    async def query_provider(self, client: httpx.AsyncClient, provider: SearchProvider, query: str, request: SearchRequest) -> Optional[List[SearchResult]]:
        provider_config = self.providers.get(provider)
        if not provider_config: return None

        if await self.circuit_breaker.is_open(provider.value):
            logger.warning(f"Circuit breaker for {provider.value} is open. Skipping.")
            return None
        
        try:
            params: Dict[str, any] = {}
            headers = {"User-Agent": "DeepSearchStack/1.0"}
            url = provider_config["url"]

            if provider == SearchProvider.WHOOGLE: url = f"{url}/search"; params = {"q": query, "format": "json"}
            elif provider == SearchProvider.SEARXNG: url = f"{url}/search"; params = {"q": query, "format": "json"}
            elif provider == SearchProvider.YACY: url = f"{url}/yacysearch.json"; params = {"query": query, "maximumRecords": 20}
            elif provider == SearchProvider.WIKIPEDIA: params = {"action": "query", "list": "search", "srsearch": query, "format": "json"}
            elif provider == SearchProvider.DUCKDUCKGO: params = {"q": query, "format": "json", "no_html": 1}
            elif provider == SearchProvider.STACKEXCHANGE: params = {"order": "desc", "sort": "relevance", "q": query, "site": "stackoverflow"}
            elif provider == SearchProvider.ARXIV: params = {"search_query": f"all:{query}", "start": 0, "max_results": 10}

            response = await client.get(url, params=params, headers=headers, timeout=request.timeout)
            logger.info("Provider: %s, Status: %s", provider.value, response.status_code)
            response.raise_for_status()
            logger.info("Raw response from %s: %s", provider.value, response.text)

            if provider == SearchProvider.ARXIV:
                results = self._parse_arxiv(response.text, provider_config["weight"])
            else:
                raw_results = response.json()
                results = self._parse_whoogle(raw_results, provider_config["weight"]) if provider == SearchProvider.WHOOGLE else self._parse_searxng(raw_results, provider_config["weight"]) if provider == SearchProvider.SEARXNG else self._parse_yacy(raw_results, provider_config["weight"]) if provider == SearchProvider.YACY else self._parse_wikipedia(raw_results, provider_config["weight"]) if provider == SearchProvider.WIKIPEDIA else self._parse_duckduckgo(raw_results, provider_config["weight"]) if provider == SearchProvider.DUCKDUCKGO else self._parse_stackexchange(raw_results, provider_config["weight"])
            
            await self.circuit_breaker.record_success(provider.value)
            return results

        except Exception as e:
            logger.error(f"Provider '{provider.value}' failed: {type(e).__name__} - {e}", exc_info=False)
            await self.circuit_breaker.record_failure(provider.value)
            return None
    
    def _parse_whoogle(self, data, w):
        if not isinstance(data, dict) or "results" not in data:
            return []
        return [SearchResult(title=i.get("title",""), url=i.get("url",""), description=i.get("snippet",""), source="whoogle", confidence=w) for i in data.get("results", []) if i.get("url")]
    def _parse_searxng(self, data, w): return [SearchResult(title=i.get("title",""), url=i.get("url",""), description=i.get("content",""), source="searxng", confidence=w) for i in data.get("results", []) if i.get("url")]
    def _parse_yacy(self, data, w): return [SearchResult(title=i.get("title",""), url=i.get("link",""), description=i.get("description",""), source="yacy", confidence=w*0.8) for i in data.get("channels", [{}])[0].get("items", []) if i.get("link")]
    def _parse_wikipedia(self, data, w): return [SearchResult(title=i.get("title",""), url=f"https://en.wikipedia.org/wiki/{i.get('title','').replace(' ','_')}", description=re.sub(r'<.*?>','',i.get("snippet","")), source="wikipedia", confidence=w*1.2) for i in data.get("query",{}).get("search",[])]
    def _parse_duckduckgo(self, data, w):
        if not isinstance(data, dict):
            return []
        results = []
        topics = data.get("RelatedTopics", [])
        for topic in topics:
            if "Topics" in topic: topics.extend(topic["Topics"])
            if topic.get("FirstURL") and topic.get("Text"):
                results.append(SearchResult(title=topic.get("Text").split(" - ")[0], url=topic.get("FirstURL"), description=topic.get("Text"), source="duckduckgo", confidence=w))
        if data.get("AbstractURL") and data.get("AbstractText"):
             results.append(SearchResult(title=data.get("Heading", "Abstract"), url=data.get("AbstractURL"), description=data.get("AbstractText"), source="duckduckgo", confidence=w*1.1))
        return results
    def _parse_stackexchange(self, data, w):
        results = []
        for item in data.get("items", []):
            desc = f"Score: {item.get('score', 0)}, Answers: {item.get('answer_count', 0)}. By: {item.get('owner',{}).get('display_name', 'N/A')}"
            results.append(SearchResult(title=html.unescape(item.get("title", "")), url=item.get("link", ""), description=desc, source="stackexchange", confidence=w*1.2))
        return results
    def _parse_arxiv(self, xml_data, w):
        results = []
        try:
            if not xml_data.strip().startswith("<?xml"):
                return []
            xml_data = re.sub(' xmlns="[^"]+"', '', xml_data, count=1)
            root = ET.fromstring(xml_data)
            for entry in root.findall('entry'):
                title = entry.find('title').text.strip().replace('\n', ' ').replace('  ', ' ')
                url = entry.find('id').text.strip()
                summary = entry.find('summary').text.strip().replace('\n', ' ')
                results.append(SearchResult(title=title, url=url, description=summary, source="arxiv", confidence=w*1.3))
        except ET.ParseError as e:
            logger.error(f"Failed to parse arXiv XML feed: {e}")
        return results
