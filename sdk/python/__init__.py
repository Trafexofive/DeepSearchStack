"""
DeepSearchStack Python SDK - Package Initialization
"""

from .deepsearch import (
    DeepSearchClient,
    SyncDeepSearchClient,
    CrawlResult,
    SearchResult,
    crawl_sync,
    search_sync,
    llm_complete_sync
)

__version__ = "0.1.0"
__author__ = "Trafexofive"
__license__ = "MIT"

__all__ = [
    "DeepSearchClient",
    "SyncDeepSearchClient", 
    "CrawlResult",
    "SearchResult",
    "crawl_sync",
    "search_sync",
    "llm_complete_sync"
]