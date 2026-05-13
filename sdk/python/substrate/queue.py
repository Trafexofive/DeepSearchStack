"""
QueueClient — Sub-agent message queue.

Endpoints:
  POST /api/queue/publish          — Publish a message
  GET  /api/queue/consume/{channel} — Consume a message
  GET  /api/queue/status            — Queue status
"""

from typing import Optional


class QueueClient:
    def __init__(self, base_url: str = "http://localhost:80", api_key: Optional[str] = None, timeout: float = 120.0):
        from substrate.client import SubstrateClient
        self._client = SubstrateClient(base_url, api_key, timeout)

    async def publish(self, channel: str, payload: dict) -> dict:
        resp = await self._client._request("POST", "/api/queue/publish", json={
            "channel": channel, "payload": payload,
        })
        resp.raise_for_status()
        return resp.json()

    async def consume(self, channel: str) -> dict:
        resp = await self._client._request("GET", f"/api/queue/consume/{channel}")
        resp.raise_for_status()
        return resp.json()

    async def status(self) -> dict:
        resp = await self._client._request("GET", "/api/queue/status")
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self._client.close()
