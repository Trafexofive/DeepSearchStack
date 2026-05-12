"""
event_bus — Substrate Internal Pub/Sub

Thin wrapper around Redis pub/sub for inter-service communication.
Agents emit events; services subscribe to channels.
Also exposes a WebSocket endpoint for real-time client updates.
"""

import os
import json
import logging
from typing import Optional

import redis.asyncio as redis_async
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("event_bus")


# ─── Models ──────────────────────────────────────────────────────────────────

class Event(BaseModel):
    channel: str
    data: dict
    source: Optional[str] = None


# ─── Event Bus Core ──────────────────────────────────────────────────────────

class EventBus:
    """Redis-backed pub/sub with WebSocket fan-out."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis_url = redis_url
        self._pub = None
        self._sub = None
        self._ws_clients: dict[str, list[WebSocket]] = {}

    async def connect(self):
        self._pub = await redis_async.from_url(self.redis_url)
        self._sub = self._pub.pubsub()
        logger.info(f"Event bus connected to {self.redis_url}")

    async def disconnect(self):
        if self._pub:
            await self._pub.aclose()
        if self._sub:
            await self._sub.close()

    async def publish(self, event: Event):
        """Publish an event to a channel."""
        if not self._pub:
            await self.connect()
        payload = json.dumps(event.model_dump())
        await self._pub.publish(event.channel, payload)
        logger.debug(f"Published to {event.channel}: {event.data}")

    async def subscribe(self, channel: str):
        """Subscribe to a channel (for service-side consumption)."""
        if not self._sub:
            await self.connect()
        await self._sub.subscribe(channel)

    async def listen(self, channel: str):
        """Generator yielding messages from a channel."""
        if not self._sub:
            await self.connect()
            await self._sub.subscribe(channel)
        async for message in self._sub.listen():
            if message["type"] == "message":
                yield json.loads(message["data"])

    async def register_ws(self, client_id: str, ws: WebSocket):
        if client_id not in self._ws_clients:
            self._ws_clients[client_id] = []
        self._ws_clients[client_id].append(ws)

    async def unregister_ws(self, client_id: str, ws: WebSocket):
        if client_id in self._ws_clients:
            self._ws_clients[client_id] = [w for w in self._ws_clients[client_id] if w != ws]
            if not self._ws_clients[client_id]:
                del self._ws_clients[client_id]

    async def fanout(self, event: Event):
        """Publish and also push to all WebSocket clients subscribed to this channel."""
        await self.publish(event)
        clients = self._ws_clients.get(event.channel, [])
        for ws in clients:
            try:
                await ws.send_json(event.model_dump())
            except Exception:
                pass


bus = EventBus()

app = FastAPI(title="Substrate Event Bus", version="0.1.0")


# ─── HTTP Routes ─────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "mode": "redis"}


@app.post("/api/publish")
async def publish_event(event: Event):
    """Publish an event to a channel."""
    await bus.publish(event)
    return {"published": True, "channel": event.channel}


# ─── WebSocket ───────────────────────────────────────────────────────────────

@app.websocket("/ws/{channel}")
async def websocket_endpoint(ws: WebSocket, channel: str, client_id: str = "anon"):
    await ws.accept()
    client_id = f"{client_id}-{channel}"
    await bus.register_ws(client_id, ws)
    logger.info(f"WebSocket connected: {client_id} -> {channel}")

    try:
        while True:
            data = await ws.receive_text()
            # Client can also publish via WebSocket
            try:
                msg = json.loads(data)
                event = Event(channel=channel, data=msg, source=client_id)
                await bus.fanout(event)
            except json.JSONDecodeError:
                await ws.send_json({"error": "invalid JSON"})
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {client_id}")
    finally:
        await bus.unregister_ws(client_id, ws)


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    import uvicorn

    port = int(os.getenv("EVENT_BUS_PORT", "8003"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
