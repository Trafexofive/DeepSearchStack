#
# services/search-gateway/common/models.py
#
from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Optional

class SearchProvider(str, Enum):
    WHOOGLE = "whoogle"
    SEARXNG = "searxng"
    YACY = "yacy"
    WIKIPEDIA = "wikipedia"
    DUCKDUCKGO = "duckduckgo"
    STACKEXCHANGE = "stackexchange"
    ARXIV = "arxiv"

class SortMethod(str, Enum):
    RELEVANCE = "relevance"
    DATE = "date"

class SearchResult(BaseModel):
    title: str
    url: str
    description: str
    source: str
    confidence: float = 1.0
    domain_authority: Optional[float] = None
    rank: Optional[int] = None

class SearchGatewayRequest(BaseModel):
    query: str
    providers: List[SearchProvider] = [
        SearchProvider.WHOOGLE, 
        SearchProvider.SEARXNG, 
        SearchProvider.DUCKDUCKGO, 
        SearchProvider.WIKIPEDIA
    ]
    max_results: int = 10
    sort_by: SortMethod = SortMethod.RELEVANCE
    timeout: float = 15.0
