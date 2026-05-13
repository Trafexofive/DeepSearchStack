"""
AuditClient — AI-SEO / GEO content scoring.

Endpoints:
  POST /api/audit/content      — Score a piece of content
  POST /api/audit/compare      — Compare against competitor
  POST /api/audit/llm-citation — LLM-based citation check
"""

from typing import Optional

from pydantic import BaseModel


class AuditClient:
    def __init__(self, base_url: str = "http://localhost:80", api_key: Optional[str] = None, timeout: float = 120.0):
        from substrate.client import SubstrateClient
        self._client = SubstrateClient(base_url, api_key, timeout)

    async def audit_content(self, content: str, keyword: str) -> dict:
        resp = await self._client._request("POST", "/api/audit/content", json={
            "content": content, "keyword": keyword,
        })
        resp.raise_for_status()
        return resp.json()

    async def compare(self, content: str, competitor_url: str, keyword: str) -> dict:
        resp = await self._client._request("POST", "/api/audit/compare", json={
            "content": content, "competitor_url": competitor_url, "keyword": keyword,
        })
        resp.raise_for_status()
        return resp.json()

    async def llm_citation(self, query: str, content: str) -> dict:
        resp = await self._client._request("POST", "/api/audit/llm-citation", json={
            "query": query, "content": content,
        })
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self._client.close()
