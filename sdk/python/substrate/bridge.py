"""
BridgeClient — DSS research → blog generation cross-wire.

Endpoints:
  POST /api/bridge/research       — Research a topic via DSS
  POST /api/bridge/generate       — Generate blog with research context
  POST /api/bridge/crawl-and-bridge — URL → crawl → generate one-shot
"""

from typing import Optional


class BridgeClient:
    def __init__(self, base_url: str = "http://localhost:80", api_key: Optional[str] = None, timeout: float = 120.0):
        from substrate.client import SubstrateClient
        self._client = SubstrateClient(base_url, api_key, timeout)

    async def research(self, topic: str, max_sources: int = 3) -> dict:
        resp = await self._client._request("POST", "/api/bridge/research", json={
            "topic": topic, "max_sources": max_sources,
        })
        resp.raise_for_status()
        return resp.json()

    async def generate(self, topic: str, context: str = "",
                       style: str = "technical", max_tokens: int = 2048) -> dict:
        resp = await self._client._request("POST", "/api/bridge/generate", json={
            "topic": topic, "context": context, "style": style, "max_tokens": max_tokens,
        })
        resp.raise_for_status()
        return resp.json()

    async def crawl_and_bridge(self, url: str, style: str = "technical") -> dict:
        resp = await self._client._request("POST", "/api/bridge/crawl-and-bridge", json={
            "url": url, "style": style,
        })
        resp.raise_for_status()
        return resp.json()

    async def status(self) -> dict:
        resp = await self._client._request("GET", "/api/bridge/status")
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self._client.close()
