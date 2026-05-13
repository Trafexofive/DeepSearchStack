"""
IngestClient — RSS/Atom feed ingestion pipeline.

Endpoints:
  GET  /api/ingest/health  — Service health
  GET  /api/ingest/stats   — Pipeline statistics
  GET  /api/ingest/feeds   — Configured feeds
  GET  /api/ingest/drafts  — Generated drafts
  POST /api/ingest/scan    — Trigger manual scan
"""

from typing import Optional

from pydantic import BaseModel


class IngestClient:
    def __init__(self, base_url: str = "http://localhost:80", api_key: Optional[str] = None, timeout: float = 120.0):
        from substrate.client import SubstrateClient
        self._client = SubstrateClient(base_url, api_key, timeout)

    async def health(self) -> dict:
        resp = await self._client._request("GET", "/api/ingest/health")
        resp.raise_for_status()
        return resp.json()

    async def stats(self) -> dict:
        resp = await self._client._request("GET", "/api/ingest/stats")
        resp.raise_for_status()
        return resp.json()

    async def feeds(self) -> dict:
        resp = await self._client._request("GET", "/api/ingest/feeds")
        resp.raise_for_status()
        return resp.json()

    async def drafts(self) -> dict:
        resp = await self._client._request("GET", "/api/ingest/drafts")
        resp.raise_for_status()
        return resp.json()

    async def scan(self, feed_url: Optional[str] = None) -> dict:
        """Trigger a manual feed scan. Optionally limit to one feed URL."""
        payload = {"feed_url": feed_url} if feed_url else {}
        resp = await self._client._request("POST", "/api/ingest/scan", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self._client.close()
