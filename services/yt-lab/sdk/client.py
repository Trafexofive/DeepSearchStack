"""yt-lab SDK — typed async Python client.

Usage:
    from ytlab_client import YtLabClient

    async with YtLabClient() as yt:
        health = await yt.health()

        # Channel ingest
        result = await yt.ingest_channel("https://youtube.com/@Fireship", limit=10)

        # Video summarize
        summary = await yt.summarize("https://youtube.com/watch?v=...", style="tl;dr")

        # Cross-reference
        refs = await yt.crossref("https://youtube.com/watch?v=...")
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from typing import Optional

import httpx


@dataclass
class IngestResult:
    channel: str
    videos_found: int
    videos_ingested: int
    summary: str | None = None
    duration_seconds: float = 0.0


@dataclass
class SummarizeResult:
    title: str
    channel: str
    duration: int
    summary: str
    style: str
    humanized: bool = False


@dataclass
class VideoMetadata:
    id: str
    url: str
    title: str
    channel: str
    channel_url: str = ""
    duration: int = 0
    upload_date: str = ""
    view_count: int = 0
    transcript: str = ""
    has_transcript: bool = False


class YtLabClient:
    """Async client for Substrate's yt-lab service."""

    def __init__(self, base_url: str = "http://localhost:8021", timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Use as context manager: async with YtLabClient() as yt:")
        return self._client

    async def health(self) -> dict:
        r = await self.client.get(f"{self.base_url}/health")
        r.raise_for_status()
        return r.json()

    async def video_metadata(self, video_url: str) -> VideoMetadata:
        r = await self.client.get(f"{self.base_url}/videos/metadata", params={"video_url": video_url})
        r.raise_for_status()
        data = r.json()
        return VideoMetadata(**data)

    async def ingest_video(self, video_url: str) -> IngestResult:
        r = await self.client.post(f"{self.base_url}/videos/ingest", json={"video_url": video_url})
        r.raise_for_status()
        return IngestResult(**r.json())

    async def summarize(
        self, video_url: str, style: str = "bullet", humanize: bool = False
    ) -> SummarizeResult:
        r = await self.client.post(
            f"{self.base_url}/videos/summarize",
            json={"video_url": video_url, "style": style, "humanize": humanize},
        )
        r.raise_for_status()
        return SummarizeResult(**r.json())

    async def crossref(self, video_url: str, max_results: int = 5) -> list[dict]:
        r = await self.client.post(
            f"{self.base_url}/videos/crossref",
            json={"video_url": video_url, "max_results": max_results},
        )
        r.raise_for_status()
        return r.json()["related_content"]

    async def ingest_channel(
        self, channel_url: str, limit: int = 20, summarize: bool = False, humanize: bool = False
    ) -> IngestResult:
        r = await self.client.post(
            f"{self.base_url}/channels/ingest",
            json={
                "channel_url": channel_url,
                "limit": limit,
                "summarize": summarize,
                "humanize": humanize,
            },
        )
        r.raise_for_status()
        return IngestResult(**r.json())

    async def watch_channel(self, channel_url: str, interval_hours: int = 6) -> dict:
        r = await self.client.post(
            f"{self.base_url}/channels/watch",
            json={"channel_url": channel_url, "interval_hours": interval_hours},
        )
        r.raise_for_status()
        return r.json()

    async def list_watching(self) -> list[dict]:
        r = await self.client.get(f"{self.base_url}/channels/watching")
        r.raise_for_status()
        return r.json()["channels"]


# ─── CLI ──────────────────────────────────────────────────────

USAGE = """ytlab_client.py — CLI for Substrate yt-lab

Usage:
  python ytlab_client.py health
  python ytlab_client.py metadata <video_url>
  python ytlab_client.py summarize <video_url> [--style tl;dr]
  python ytlab_client.py ingest <channel_url> [--limit 10]
"""


async def _main():
    if len(sys.argv) < 2:
        print(USAGE)
        sys.exit(1)

    cmd = sys.argv[1]

    async with YtLabClient() as yt:
        if cmd == "health":
            print(json.dumps(await yt.health(), indent=2))

        elif cmd == "metadata":
            url = sys.argv[2] if len(sys.argv) > 2 else ""
            m = await yt.video_metadata(url)
            print(f"  {m.title}\n  {m.channel} | {m.duration}s | {m.view_count} views")
            print(f"  transcript: {len(m.transcript)} chars" if m.has_transcript else "  no transcript")

        elif cmd == "summarize":
            url = sys.argv[2] if len(sys.argv) > 2 else ""
            style = "bullet"
            for i, arg in enumerate(sys.argv):
                if arg == "--style" and i + 1 < len(sys.argv):
                    style = sys.argv[i + 1]
            s = await yt.summarize(url, style=style)
            print(s.summary)
            print(f"\n── {s.title} | {s.style}")

        elif cmd == "ingest":
            url = sys.argv[2] if len(sys.argv) > 2 else ""
            limit = 10
            for i, arg in enumerate(sys.argv):
                if arg == "--limit" and i + 1 < len(sys.argv):
                    limit = int(sys.argv[i + 1])
            r = await yt.ingest_channel(url, limit=limit)
            print(f"  {r.channel}: {r.videos_ingested}/{r.videos_found} ingested ({r.duration_seconds:.1f}s)")
            if r.summary:
                print(f"\n{r.summary}")

        else:
            print(f"Unknown: {cmd}\n{USAGE}")


if __name__ == "__main__":
    asyncio.run(_main())
