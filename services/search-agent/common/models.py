#
# services/search-agent/common/models.py
#
from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any

# --- Constants ---
DEFAULT_TIMEOUT = 15.0
DEFAULT_RESULTS_LIMIT = 10

# --- Enums ---
class SearchProvider(str, Enum):
    WHOOGLE = "whoogle"
    SEARXNG = "searxng"
    YACY = "yacy"
    BRAVE = "brave"
    QWANT = "qwant"
    WIKIPEDIA = "wikipedia"
    DUCKDUCKGO = "duckduckgo"
    GOOGLE_CSE = "google_cse"

class ResponseFormat(str, Enum):
    STANDARD = "standard"
    DETAILED = "detailed"
    MARKDOWN = "markdown"
    CONCISE = "concise"
    STREAMING = "streaming"

class SortMethod(str, Enum):
    RELEVANCE = "relevance"
    DATE = "date"
    SOURCE_QUALITY = "source_quality"

# --- Pydantic Models ---
class SearchResult(BaseModel):
    title: str
    url: str
    description: str
    source: str
    confidence: float = 1.0
    published_date: Optional[str] = None
    rank: Optional[int] = None
    domain_authority: Optional[float] = None
    keywords: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class SearchRequest(BaseModel):
    query: str
    # FIX: Changed default_factory to a simple default to resolve 422 errors.
    providers: List[SearchProvider] = [SearchProvider.WHOOGLE, SearchProvider.SEARXNG]
    max_results: int = DEFAULT_RESULTS_LIMIT
    response_format: ResponseFormat = ResponseFormat.STANDARD
    sort_by: SortMethod = SortMethod.RELEVANCE
    timeout: float = DEFAULT_TIMEOUT
    filter_domains: List[str] = Field(default_factory=list)
    exclude_domains: List[str] = Field(default_factory=list)
    stream: bool = False
    safe_search: bool = True
    region: Optional[str] = None
    language: str = "en-US"
    time_range: Optional[str] = None
    llm_provider: Optional[str] = None

class GatewayResponse(BaseModel):
    answer: str
    sources: List[SearchResult]
    query_understanding: Optional[Dict[str, Any]] = None
    execution_time: float
    query_time: str
    search_providers_used: List[str]
    total_results_found: int
    cached: bool = False

class StreamingChunk(BaseModel):
    content: str
    finished: bool = False
    sources: Optional[List[SearchResult]] = None

class HealthStatus(BaseModel):
    status: str
    version: str
    uptime: float
    search_providers: Dict[str, str]
    llm_status: str

class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    timestamp: str
