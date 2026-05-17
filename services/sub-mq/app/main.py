"""
SubMQ — Sub-agent Message Queue

Lightweight Redis-backed message queue for sub-agent research pipelines.

Endpoints:
  POST /queue/publish              — publish message to channel
  GET  /queue/consume/{channel}    — blocking read (BLPOP with timeout)
  POST /queue/subscribe            — WebSocket subscribe to channel
  GET  /queue/status               — queue depths, consumer counts, throughput
  DELETE /queue/{channel}/{id}     — acknowledge/delete message
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel, Field

from mqcore import MessageQueue

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [sub-mq] %(message)s",
)
log = logging.getLogger("sub-mq")

app = FastAPI(title="SubMQ — Sub-agent Message Queue", version="1.0.0")
mq: Optional[MessageQueue] = None

# ─── Models ───────────────────────────────────────────────

class PublishRequest(BaseModel):
    channel: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_.-]+$")
    payload: dict = Field(default_factory=dict)

class PublishResponse(BaseModel):
    message_id: str
    channel: str
    ts: str

class ConsumeRequest(BaseModel):
    timeout: int = Field(default=30, ge=1, le=120)

class MessageResponse(BaseModel):
    id: str
    channel: str
    payload: dict
    ts: str

class QueueStatus(BaseModel):
    total_published: int
    total_consumed: int
    channels: list[str]
    channel_depths: dict
    redis_connected: bool

class AckResponse(BaseModel):
    acknowledged: bool

# ─── Lifecycle ────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    global mq
    mq = MessageQueue()
    await mq.connect()
    log.info("sub-mq started redis=%s", os.environ.get("REDIS_URL", "redis://redis:6379/0"))

@app.on_event("shutdown")
async def shutdown():
    if mq:
        await mq.disconnect()

# ─── Endpoints ────────────────────────────────────────────

@app.post("/queue/publish", response_model=PublishResponse)
async def publish(req: PublishRequest):
    """Publish a message to a channel."""
    msg = await mq.publish(req.channel, req.payload)
    log.info("published channel=%s id=%s", req.channel, msg["id"])
    return PublishResponse(
        message_id=msg["id"],
        channel=msg["channel"],
        ts=msg["ts"],
    )


@app.get("/queue/consume/{channel}")
async def consume(channel: str, timeout: int = Query(default=30, ge=1, le=120)):
    """Blocking consume from a channel. Returns message or 204 on timeout."""
    msg = await mq.consume(channel, timeout=timeout)
    if msg is None:
        raise HTTPException(status_code=204, detail="No message available")
    log.info("consumed channel=%s id=%s", channel, msg["id"])
    return MessageResponse(
        id=msg["id"],
        channel=msg["channel"],
        payload=msg.get("payload", {}),
        ts=msg["ts"],
    )


@app.websocket("/queue/subscribe")
async def websocket_subscribe(websocket: WebSocket):
    """WebSocket subscribe — receive messages as they're published.

    Client sends: {"subscribe": "channel_name"}
    Server sends: {"type": "message", "channel": "...", "data": {...}}
    """
    await websocket.accept()
    subscribed_channels = set()
    log.info("websocket connected")

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "detail": "invalid JSON"})
                continue

            if "subscribe" in data:
                ch = data["subscribe"]
                subscribed_channels.add(ch)
                await websocket.send_json({"type": "subscribed", "channel": ch})
                log.info("websocket subscribed channel=%s", ch)
            elif "unsubscribe" in data:
                ch = data["unsubscribe"]
                subscribed_channels.discard(ch)
                await websocket.send_json({"type": "unsubscribed", "channel": ch})

    except WebSocketDisconnect:
        log.info("websocket disconnected channels=%s", subscribed_channels)


@app.get("/queue/status", response_model=QueueStatus)
async def status():
    """Get queue status — depths, throughput, Redis connectivity."""
    stats = await mq.stats()
    redis_ok = await mq.health()
    return QueueStatus(
        total_published=stats["total_published"],
        total_consumed=stats["total_consumed"],
        channels=stats["channels"],
        channel_depths=stats["channel_depths"],
        redis_connected=redis_ok,
    )


@app.delete("/queue/{channel}/{message_id}", response_model=AckResponse)
async def ack_message(channel: str, message_id: str):
    """Acknowledge/delete a message from the processing set."""
    ok = await mq.ack(channel, message_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Message not found in processing set")
    return AckResponse(acknowledged=True)


@app.get("/health")
async def health():
    redis_ok = await mq.health()
    return {
        "status": "ok" if redis_ok else "degraded",
        "redis": "connected" if redis_ok else "disconnected",
    }


# ─── Main ─────────────────────────────────────────────────

def main():
    import uvicorn
    port = int(os.environ.get("SUB_MQ_PORT", "8012"))
    uvicorn.run(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
