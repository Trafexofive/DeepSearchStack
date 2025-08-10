#
# services/search-agent/common/models.py
#
from pydantic import BaseModel
from typing import List, Optional

# --- LLM Client Models (Internal to search-agent) ---
class Message(BaseModel):
    role: str
    content: str

# --- Search Result Model (Input from web-api) ---
class SearchResult(BaseModel):
    title: str
    url: str
    description: str
    source: str
    confidence: float = 1.0

# --- Agent API Models ---
class SynthesizeRequest(BaseModel):
    query: str
    sources: List[SearchResult]
    llm_provider: Optional[str] = None

class StreamingChunk(BaseModel):
    content: str
    finished: bool = False
    sources: Optional[List[SearchResult]] = None
