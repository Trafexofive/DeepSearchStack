"""
EventBusClient — Internal pub/sub event bus.

Endpoints:
  POST /api/events/publish  — Publish an event
"""

from typing import Optional


class EventBusClient:
    def __init__(self, base_url: str = "http://localhost:80", api_key: Optional[str] = None, timeout: float = 120.0):
        from substrate.client import SubstrateClient
        self._client = SubstrateClient(base_url, api_key, timeout)

    async def publish(self, channel: str, data: dict, source: str = "sdk") -> dict:
        resp = await self._client._request("POST", "/api/events/publish", json={
            "channel": channel, "data": data, "source": source,
        })
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        await self._client.close()
