"""
DeepSearchStack - Common Models Module
Shared Pydantic models across services
"""
from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime


# ==================== ENUMS ====================
class SearchProvider(str, Enum):
    WHOOGLE = "whoogle"
    SEARXNG = "searxng"
    YACY = "yacy"
    WIKIPEDIA = "wikipedia"
    DUCKDUCKGO = "duckduckgo"
    STACKEXCHANGE = "stackexchange"
    ARXIV = "arxiv"
    CUSTOM = "custom"


class SortMethod(str, Enum):
    RELEVANCE = "relevance"
    DATE = "date"


# ==================== SEARCH MODELS ====================
class SearchResult(BaseModel):
    title: str
    url: str
    description: str
    source: str
    confidence: float = 1.0
    domain_authority: Optional[float] = None
    rank: Optional[int] = None
    published_date: Optional[datetime] = None
    snippet: Optional[str] = None


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
    filters: Optional[Dict[str, Any]] = None


# ==================== LLM & MESSAGING MODELS ====================
class Message(BaseModel):
    role: str
    content: str


class SynthesizeRequest(BaseModel):
    query: str
    sources: List[SearchResult]
    llm_provider: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


class StreamingChunk(BaseModel):
    content: str
    finished: bool = False
    sources: Optional[List[SearchResult]] = None
    error: Optional[str] = None


# ==================== CONTENT & RAG MODELS ====================
class ScrapedContent(BaseModel):
    url: str
    title: str
    content: str
    markdown: Optional[str] = None
    success: bool = True
    word_count: Optional[int] = None
    error_message: Optional[str] = None
    extracted_at: Optional[datetime] = None


class VectorChunk(BaseModel):
    chunk_id: str
    content: str
    url: str
    title: str
    similarity_score: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None


# ==================== DEEP SEARCH MODELS ====================
class DeepSearchRequest(BaseModel):
    query: str
    providers: Optional[List[SearchProvider]] = None
    max_results: Optional[int] = None
    enable_scraping: bool = True
    max_scrape_urls: Optional[int] = None
    enable_rag: bool = True
    rag_top_k: Optional[int] = None
    enable_synthesis: bool = True
    llm_provider: Optional[str] = None
    temperature: Optional[float] = None
    stream: bool = True
    session_id: Optional[str] = None
    sort_by: Optional[SortMethod] = None


class DeepSearchResponse(BaseModel):
    query: str
    answer: str
    sources: List[SearchResult]
    scraped_content: Optional[List[ScrapedContent]] = None
    rag_chunks: Optional[List[VectorChunk]] = None
    session_id: Optional[str] = None
    execution_time: float
    provider_used: str
    total_results: int
    results_scraped: int
    chunks_retrieved: int


class DeepSearchProgress(BaseModel):
    stage: str
    message: str
    progress: float


class StreamChunk(BaseModel):
    type: str  # "progress", "content", "sources", "complete", "error"
    data: Any


# ==================== SESSION MODELS ====================
class SessionMessage(BaseModel):
    role: str
    content: str
    timestamp: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None


class Session(BaseModel):
    session_id: str
    created_at: datetime
    updated_at: datetime
    title: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class SessionCreate(BaseModel):
    title: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class SessionListResponse(BaseModel):
    sessions: List[Session]
    total: int


# ==================== HEALTH & CONFIG MODELS ====================
class HealthCheck(BaseModel):
    status: str
    version: str
    uptime: float
    dependencies: Dict[str, bool]
    cache_enabled: bool
    rag_enabled: bool


class ServiceMetrics(BaseModel):
    requests_per_minute: float
    active_connections: int
    error_rate: float
    avg_response_time: float
    status: str = "unknown"