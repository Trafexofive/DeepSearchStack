from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any, Literal
from datetime import datetime
from enum import Enum


# --- Enums ---
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
    CREDIBILITY = "credibility"


class LLMProvider(str, Enum):
    OLLAMA = "ollama"
    GROQ = "groq"
    GEMINI = "gemini"


# --- Core Models ---
class SearchResult(BaseModel):
    """Individual search result from a provider"""
    title: str
    url: str
    description: str
    source: str
    confidence: float = 1.0
    domain_authority: Optional[float] = None
    rank: Optional[int] = None
    timestamp: Optional[datetime] = None


class ScrapedContent(BaseModel):
    """Scraped and processed content from a URL"""
    url: str
    title: str
    content: str
    markdown: Optional[str] = None
    extracted_data: Optional[Dict[str, Any]] = None
    word_count: int = 0
    success: bool = True
    error_message: Optional[str] = None


class VectorChunk(BaseModel):
    """Document chunk with embedding metadata"""
    chunk_id: str
    content: str
    url: str
    title: str
    similarity_score: Optional[float] = None
    metadata: Optional[Dict[str, Any]] = None


# --- Request Models ---
class DeepSearchRequest(BaseModel):
    """Main DeepSearch API request"""
    query: str = Field(..., description="The search query")
    
    # Search configuration
    max_results: Optional[int] = Field(None, description="Maximum number of search results")
    providers: Optional[List[SearchProvider]] = Field(None, description="Search providers to use")
    sort_by: SortMethod = Field(SortMethod.RELEVANCE, description="Result sorting method")
    
    # Scraping configuration
    enable_scraping: bool = Field(True, description="Enable content scraping")
    max_scrape_urls: Optional[int] = Field(None, description="Maximum URLs to scrape")
    
    # RAG configuration
    enable_rag: bool = Field(True, description="Enable RAG pipeline")
    rag_top_k: Optional[int] = Field(None, description="Number of chunks to retrieve")
    
    # Synthesis configuration
    enable_synthesis: bool = Field(True, description="Enable LLM synthesis")
    llm_provider: Optional[LLMProvider] = Field(None, description="LLM provider to use")
    temperature: Optional[float] = Field(None, description="LLM temperature")
    stream: bool = Field(True, description="Stream the response")
    
    # Session management
    session_id: Optional[str] = Field(None, description="Session ID for conversation history")
    include_history: bool = Field(False, description="Include conversation history in context")
    
    # Advanced options
    enable_multi_hop: bool = Field(False, description="Enable multi-hop reasoning")
    enable_fact_checking: bool = Field(False, description="Enable fact verification")
    
    # Caching
    use_cache: bool = Field(True, description="Use cached results if available")
    cache_ttl: Optional[int] = Field(None, description="Override default cache TTL")


class QuickSearchRequest(BaseModel):
    """Simplified search request for quick queries"""
    query: str
    max_results: int = 10
    session_id: Optional[str] = None


# --- Response Models ---
class DeepSearchProgress(BaseModel):
    """Progress update during streaming"""
    stage: Literal["searching", "scraping", "embedding", "retrieving", "synthesizing", "complete", "error"]
    message: str
    progress: float = Field(0.0, ge=0.0, le=1.0, description="Progress from 0.0 to 1.0")
    details: Optional[Dict[str, Any]] = None


class DeepSearchResponse(BaseModel):
    """Complete DeepSearch response"""
    query: str
    answer: str
    sources: List[SearchResult]
    scraped_content: Optional[List[ScrapedContent]] = None
    rag_chunks: Optional[List[VectorChunk]] = None
    
    # Metadata
    session_id: Optional[str] = None
    execution_time: float
    provider_used: str
    cache_hit: bool = False
    
    # Statistics
    total_results: int
    results_scraped: int = 0
    chunks_retrieved: int = 0
    tokens_used: Optional[int] = None


class StreamChunk(BaseModel):
    """Streaming response chunk"""
    type: Literal["progress", "content", "sources", "complete", "error"]
    data: Dict[str, Any]
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# --- Session Models ---
class SessionMessage(BaseModel):
    """Single message in a conversation"""
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: Optional[Dict[str, Any]] = None


class Session(BaseModel):
    """Conversation session"""
    session_id: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    messages: List[SessionMessage] = []
    metadata: Optional[Dict[str, Any]] = None


class SessionCreate(BaseModel):
    """Create a new session"""
    metadata: Optional[Dict[str, Any]] = None


class SessionListResponse(BaseModel):
    """List of sessions"""
    sessions: List[Session]
    total: int


# --- Health & Status Models ---
class HealthCheck(BaseModel):
    """Service health status"""
    status: Literal["healthy", "degraded", "unhealthy"]
    version: str
    uptime: float
    dependencies: Dict[str, bool]
    cache_enabled: bool
    rag_enabled: bool


class ServiceMetrics(BaseModel):
    """Service performance metrics"""
    total_requests: int
    average_latency: float
    cache_hit_rate: float
    provider_latencies: Dict[str, float]
    error_rate: float
