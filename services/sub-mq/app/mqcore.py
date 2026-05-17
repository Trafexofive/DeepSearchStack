"""
Redis-backed message queue for sub-agent research pipelines.

Channels are Redis lists. Messages are JSON blobs with id, channel, payload, ts.
Consumers use blocking BLPOP. Publishers LPUSH.
"""

import json
import os
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import redis.asyncio as aioredis

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")


class MessageQueue:
    """Async Redis-backed message queue."""

    def __init__(self):
        self._redis: Optional[aioredis.Redis] = None

    async def connect(self):
        self._redis = aioredis.from_url(REDIS_URL, decode_responses=True)

    async def disconnect(self):
        if self._redis:
            await self._redis.close()

    async def publish(self, channel: str, payload: dict) -> dict:
        """Publish a message to a channel. Returns message with id."""
        msg = {
            "id": str(uuid.uuid4()),
            "channel": channel,
            "payload": payload,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        await self._redis.lpush(f"mq:{channel}", json.dumps(msg))
        await self._redis.publish(f"mq:notify:{channel}", msg["id"])
        # Update channel stats
        await self._redis.hincrby("mq:stats", f"published:{channel}", 1)
        await self._redis.hincrby("mq:stats", "total_published", 1)
        return msg

    async def consume(self, channel: str, timeout: int = 30) -> Optional[dict]:
        """Blocking consume from a channel. Returns message or None on timeout."""
        result = await self._redis.blpop(f"mq:{channel}", timeout=timeout)
        if result is None:
            return None
        _, raw = result
        msg = json.loads(raw)
        # Track ack
        await self._redis.hincrby("mq:stats", f"consumed:{channel}", 1)
        await self._redis.hincrby("mq:stats", "total_consumed", 1)
        return msg

    async def ack(self, channel: str, msg_id: str) -> bool:
        """Acknowledge a message (removes from processing set if exists)."""
        removed = await self._redis.srem(f"mq:processing:{channel}", msg_id)
        return removed > 0

    async def queue_depth(self, channel: str) -> int:
        """Get the current depth of a channel queue."""
        return await self._redis.llen(f"mq:{channel}")

    async def stats(self) -> dict:
        """Get global queue stats."""
        raw = await self._redis.hgetall("mq:stats")
        stats = {k: int(v) if v.isdigit() else v for k, v in raw.items()}

        # Get per-channel depths
        keys = await self._redis.keys("mq:*")
        channels = set()
        for k in keys:
            parts = k.split(":", 2)
            if len(parts) >= 2 and parts[0] == "mq" and parts[1] != "stats" and parts[1] != "notify" and parts[1] != "processing":
                channels.add(parts[1])

        channel_depths = {}
        for ch in channels:
            depth = await self.queue_depth(ch)
            if depth > 0:
                channel_depths[ch] = depth

        return {
            "total_published": stats.get("total_published", 0),
            "total_consumed": stats.get("total_consumed", 0),
            "channels": sorted(list(channels)),
            "channel_depths": channel_depths,
            "uptime": datetime.now(timezone.utc).isoformat(),
        }

    async def health(self) -> bool:
        """Check Redis connectivity."""
        try:
            await self._redis.ping()
            return True
        except Exception:
            return False
