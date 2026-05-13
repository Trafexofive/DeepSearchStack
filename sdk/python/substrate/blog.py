"""
BlogGeneratorClient — AI-powered blog post generation.

Endpoints:
  POST /api/blog/generate           — Basic generation
  POST /api/blog/generate-researched — Research-backed generation
  GET  /api/blog/stats              — Usage statistics
  GET  /api/blog/history            — Generation history
"""

from typing import Optional

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    topic: str = Field(..., min_length=3, max_length=500)
    model: str = "deepseek-chat"
    style: str = "technical"
    max_tokens: int = 2048
    temperature: float = 0.7
    context: str = ""


class GenerateResponse(BaseModel):
    id: str
    topic: str
    model: str
    content: str
    sources: list[dict] = []
    usage: dict = {}
    cost_usd: float = 0.0
    duration_ms: int = 0


class StatsResponse(BaseModel):
    total_generations: int
    total_tokens: int
    total_cost_usd: float
    avg_duration_ms: float


class HistoryEntry(BaseModel):
    id: str
    topic: str
    model: str
    status: str
    total_tokens: int
    cost_usd: float
    duration_ms: int
    created_at: str


class BlogClient:
    """Client for the blog_generator service."""

    def __init__(self, base_url: str = "http://localhost:80", api_key: Optional[str] = None, timeout: float = 120.0):
        from substrate.client import SubstrateClient
        self._client = SubstrateClient(base_url, api_key, timeout)

    @property
    def base_url(self) -> str:
        return self._client.base_url

    async def generate(self, topic: str, model: str = "deepseek-chat", style: str = "technical",
                       max_tokens: int = 2048, temperature: float = 0.7,
                       context: str = "") -> GenerateResponse:
        """Generate a blog post on a topic."""
        req = GenerateRequest(topic=topic, model=model, style=style,
                              max_tokens=max_tokens, temperature=temperature, context=context)
        resp = await self._client._request("POST", "/api/blog/generate", json=req.model_dump())
        resp.raise_for_status()
        return GenerateResponse(**resp.json())

    async def generate_researched(self, topic: str, model: str = "deepseek-chat",
                                  style: str = "technical", max_tokens: int = 2048,
                                  temperature: float = 0.7) -> GenerateResponse:
        """Generate a blog post backed by DeepSearch research."""
        req = GenerateRequest(topic=topic, model=model, style=style,
                              max_tokens=max_tokens, temperature=temperature)
        resp = await self._client._request("POST", "/api/blog/generate-researched", json=req.model_dump())
        resp.raise_for_status()
        return GenerateResponse(**resp.json())

    async def stats(self) -> StatsResponse:
        """Get aggregate usage statistics."""
        resp = await self._client._request("GET", "/api/blog/stats")
        resp.raise_for_status()
        return StatsResponse(**resp.json())

    async def history(self, limit: int = 20, offset: int = 0) -> list[HistoryEntry]:
        """List past generations."""
        resp = await self._client._request("GET", "/api/blog/history", params={"limit": limit, "offset": offset})
        resp.raise_for_status()
        return [HistoryEntry(**e) for e in resp.json()]

    async def health(self) -> dict:
        resp = await self._client._request("GET", "/api/blog/health")
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self._client.close()
