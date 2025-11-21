#!/usr/bin/env python3
"""
SearXNG Data Format Examples and Parser Reference

Query formats:
  HTML: http://searxng:8080/?q=query
  JSON: http://searxng:8080/search?q=query&format=json
  CSV:  http://searxng:8080/search?q=query&format=csv
  RSS:  http://searxng:8080/search?q=query&format=rss
"""

import json
import requests
from typing import Dict, List, Any

# =============================================================================
# JSON FORMAT (Most useful for backend parsing)
# =============================================================================

JSON_RESPONSE_EXAMPLE = {
    "query": "arch linux kernel",
    "number_of_results": 1523400,
    "results": [
        {
            "url": "https://wiki.archlinux.org/title/Kernel",
            "title": "Kernel - ArchWiki",
            "content": "The kernel is the core of an operating system. This article covers compiling, patching and configuring the Linux kernel.",
            "engine": "google",
            "parsed_url": [
                "https",
                "wiki.archlinux.org",
                "/title/Kernel",
                "",
                "",
                ""
            ],
            "template": "default.html",
            "engines": ["google", "bing", "duckduckgo"],  # Which engines returned this result
            "positions": [1, 3, 2],  # Position in each engine's results
            "score": 9.5,  # Aggregated relevance score
            "category": "general"
        },
        {
            "url": "https://github.com/torvalds/linux",
            "title": "torvalds/linux: Linux kernel source tree",
            "content": "Linux kernel source tree. Contribute to torvalds/linux development by creating an account on GitHub.",
            "engine": "github",
            "parsed_url": ["https", "github.com", "/torvalds/linux", "", "", ""],
            "template": "default.html",
            "engines": ["github", "google"],
            "positions": [1, 8],
            "score": 8.2,
            "category": "it"
        }
    ],
    "answers": [],  # Instant answers (currency conversion, calculations, etc.)
    "corrections": [],  # Spelling corrections
    "infoboxes": [  # Rich structured data (Wikipedia boxes, etc.)
        {
            "infobox": "Linux kernel",
            "content": "The Linux kernel is a free and open-source, monolithic, modular...",
            "engine": "wikipedia",
            "urls": [
                {"title": "Wikipedia", "url": "https://en.wikipedia.org/wiki/Linux_kernel"}
            ],
            "attributes": [
                {"label": "Original author", "value": "Linus Torvalds"},
                {"label": "Written in", "value": "C, Assembly"},
                {"label": "License", "value": "GPLv2"}
            ]
        }
    ],
    "suggestions": [  # Search suggestions
        "arch linux kernel parameters",
        "arch linux kernel modules",
        "arch linux kernel headers"
    ],
    "unresponsive_engines": [  # Failed engines
        ["ecosia", "HTTP error 429"]
    ]
}

# =============================================================================
# CSV FORMAT (Good for simple logging/analysis)
# =============================================================================

CSV_RESPONSE_EXAMPLE = """title,url,content,engine,score
"Kernel - ArchWiki","https://wiki.archlinux.org/title/Kernel","The kernel is the core of an operating system...","google",9.5
"torvalds/linux","https://github.com/torvalds/linux","Linux kernel source tree...","github",8.2
"""

# =============================================================================
# RSS FORMAT (For feed aggregation)
# =============================================================================

RSS_RESPONSE_EXAMPLE = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>arch linux kernel - SearXNG</title>
    <link>http://searxng:8080/</link>
    <description>Search results for "arch linux kernel"</description>
    <item>
      <title>Kernel - ArchWiki</title>
      <link>https://wiki.archlinux.org/title/Kernel</link>
      <description>The kernel is the core of an operating system...</description>
      <pubDate>Tue, 21 Oct 2025 00:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

# =============================================================================
# PRACTICAL PARSER IMPLEMENTATIONS
# =============================================================================

class SearXNGParser:
    """Production-ready SearXNG result parser"""
    
    def __init__(self, base_url: str = "http://searxng:8080"):
        self.base_url = base_url
        
    def search_json(self, query: str, categories: List[str] = None, 
                   engines: List[str] = None, lang: str = "auto") -> Dict[str, Any]:
        """
        Query SearXNG and get JSON results
        
        Args:
            query: Search query
            categories: Filter by categories (general, images, videos, news, etc.)
            engines: Specific engines to use (google, bing, github, etc.)
            lang: Language code (en, auto, etc.)
        """
        params = {
            "q": query,
            "format": "json",
            "lang": lang
        }
        
        if categories:
            params["categories"] = ",".join(categories)
        if engines:
            params["engines"] = ",".join(engines)
            
        resp = requests.get(f"{self.base_url}/search", params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()
    
    def extract_top_results(self, data: Dict[str, Any], n: int = 10) -> List[Dict[str, Any]]:
        """Extract top N results sorted by score"""
        results = data.get("results", [])
        return sorted(results, key=lambda x: x.get("score", 0), reverse=True)[:n]
    
    def deduplicate_by_domain(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Keep only best result per domain"""
        seen_domains = set()
        deduped = []
        
        for result in results:
            domain = result["parsed_url"][1]  # Extract domain
            if domain not in seen_domains:
                seen_domains.add(domain)
                deduped.append(result)
                
        return deduped
    
    def filter_by_engines(self, results: List[Dict[str, Any]], 
                         min_engines: int = 2) -> List[Dict[str, Any]]:
        """Keep only results confirmed by multiple engines"""
        return [r for r in results if len(r.get("engines", [])) >= min_engines]
    
    def extract_by_category(self, data: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        """Group results by category"""
        categorized = {}
        for result in data.get("results", []):
            cat = result.get("category", "general")
            if cat not in categorized:
                categorized[cat] = []
            categorized[cat].append(result)
        return categorized
    
    def get_engine_stats(self, data: Dict[str, Any]) -> Dict[str, int]:
        """Count results per engine"""
        stats = {}
        for result in data.get("results", []):
            for engine in result.get("engines", []):
                stats[engine] = stats.get(engine, 0) + 1
        return stats


# =============================================================================
# USAGE EXAMPLES
# =============================================================================

def example_basic_search():
    """Simple search and parse"""
    parser = SearXNGParser("http://localhost:8080")
    
    # Basic search
    data = parser.search_json("arch linux kernel")
    
    print(f"Query: {data['query']}")
    print(f"Total results: {data['number_of_results']}")
    print(f"Results returned: {len(data['results'])}\n")
    
    # Get top 5
    top5 = parser.extract_top_results(data, n=5)
    for i, result in enumerate(top5, 1):
        print(f"{i}. [{result['score']:.1f}] {result['title']}")
        print(f"   {result['url']}")
        print(f"   Engines: {', '.join(result['engines'])}\n")


def example_filtered_search():
    """Search with filters and deduplication"""
    parser = SearXNGParser()
    
    # Search only code repositories
    data = parser.search_json(
        query="neural network implementation",
        categories=["it"],
        engines=["github", "gitlab", "codeberg"]
    )
    
    # Filter: only results from 2+ engines, deduplicate domains
    results = parser.filter_by_engines(data["results"], min_engines=2)
    results = parser.deduplicate_by_domain(results)
    
    for r in results[:10]:
        print(f"[{len(r['engines'])}x] {r['title']}")
        print(f"    {r['url']}\n")


def example_multi_category_aggregation():
    """Aggregate across multiple categories"""
    parser = SearXNGParser()
    
    data = parser.search_json("linux kernel security")
    
    # Group by category
    by_category = parser.extract_by_category(data)
    
    for category, results in by_category.items():
        print(f"\n=== {category.upper()} ({len(results)} results) ===")
        for r in results[:3]:
            print(f"  - {r['title']}")
    
    # Engine statistics
    print("\n=== ENGINE STATS ===")
    stats = parser.get_engine_stats(data)
    for engine, count in sorted(stats.items(), key=lambda x: x[1], reverse=True):
        print(f"  {engine}: {count} results")


def example_structured_data_extraction():
    """Extract infoboxes and instant answers"""
    parser = SearXNGParser()
    
    data = parser.search_json("linux kernel")
    
    # Instant answers (calculations, conversions, etc.)
    if data.get("answers"):
        print("=== INSTANT ANSWERS ===")
        for answer in data["answers"]:
            print(f"  {answer}")
    
    # Infoboxes (Wikipedia, etc.)
    if data.get("infoboxes"):
        print("\n=== INFOBOXES ===")
        for box in data["infoboxes"]:
            print(f"\n{box['infobox']}")
            print(f"Engine: {box['engine']}")
            if box.get("attributes"):
                for attr in box["attributes"]:
                    print(f"  {attr['label']}: {attr['value']}")
    
    # Suggestions
    if data.get("suggestions"):
        print("\n=== SUGGESTIONS ===")
        for suggestion in data["suggestions"]:
            print(f"  - {suggestion}")


# =============================================================================
# ADVANCED: PARALLEL MULTI-QUERY AGGREGATION
# =============================================================================

from concurrent.futures import ThreadPoolExecutor, as_completed

def example_parallel_search():
    """Search multiple queries in parallel"""
    parser = SearXNGParser()
    
    queries = [
        "linux kernel",
        "systemd",
        "arch linux installation",
        "docker containers",
        "nginx configuration"
    ]
    
    results_map = {}
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_query = {
            executor.submit(parser.search_json, q): q 
            for q in queries
        }
        
        for future in as_completed(future_to_query):
            query = future_to_query[future]
            try:
                data = future.result()
                results_map[query] = data
                print(f"✓ {query}: {len(data['results'])} results")
            except Exception as e:
                print(f"✗ {query}: {e}")
    
    return results_map


# =============================================================================
# BACKEND INTEGRATION PATTERNS
# =============================================================================

"""
PATTERN 1: Simple REST proxy
    client -> your_api -> searxng -> response
    
PATTERN 2: Aggregation + caching
    client -> your_api -> [cache check] -> searxng -> [cache store] -> response
    
PATTERN 3: Multi-source fusion
    client -> your_api -> [searxng + yacy + whoogle] -> merge/dedupe -> response
    
PATTERN 4: Async job queue
    client -> enqueue job -> background worker polls searxng -> store in DB -> notify client

For your stack:
- Use requests for sync calls
- Use aiohttp for async (if high concurrency needed)
- Redis for result caching (TTL 1-24h depending on query type)
- PostgreSQL for persistent storage of aggregated results
"""

if __name__ == "__main__":
    print("=== BASIC SEARCH ===")
    example_basic_search()
    
    print("\n=== FILTERED SEARCH ===")
    example_filtered_search()
    
    print("\n=== MULTI-CATEGORY ===")
    example_multi_category_aggregation()
    
    print("\n=== STRUCTURED DATA ===")
    example_structured_data_extraction()
    
    print("\n=== PARALLEL SEARCH ===")
    example_parallel_search()
