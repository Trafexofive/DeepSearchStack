"""yt-extractor — yt-dlp wrapper for YouTube metadata + transcript extraction.

Exposes:
  GET  /health
  GET  /video/{url:path}       — extract metadata + transcript for a single video
  POST /channel/list            — list video URLs from a channel

All heavy lifting (yt-dlp, ffmpeg) lives here. The orchestrator (yt-lab) calls this service.
Host networking required — YouTube blocks datacenter IPs.
"""
import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [yt-extractor] %(message)s")
log = logging.getLogger("yt-extractor")

YTDLP_PATH = os.environ.get("YTDLP_PATH", "yt-dlp")
PORT = int(os.environ.get("YT_EXTRACTOR_PORT", "8020"))

app = FastAPI(title="yt-extractor", version="0.1.0")


# ─── Models ───────────────────────────────────────────────────

class VideoMetadata(BaseModel):
    id: str
    url: str
    title: str
    channel: str
    channel_url: str = ""
    description: str = ""
    duration: int = 0
    upload_date: str = ""
    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    language: str = "en"
    tags: list[str] = Field(default_factory=list)
    transcript: str = ""
    has_transcript: bool = False


class ChannelListRequest(BaseModel):
    channel_url: str = Field(..., description="YouTube channel URL (@handle or /channel/ID)")
    limit: int = Field(default=20, ge=1, le=100)


class ChannelListResponse(BaseModel):
    channel: str
    video_urls: list[str]
    count: int


# ─── yt-dlp wrappers ──────────────────────────────────────────

def _run_ytdlp(args: list[str], timeout: int = 120) -> tuple[str, str]:
    result = subprocess.run(
        [YTDLP_PATH] + args,
        capture_output=True, text=True, timeout=timeout,
    )
    return result.stdout, result.stderr


def _strip_srt(text: str) -> str:
    """Remove SRT/VTT timestamps and HTML tags, keep text."""
    lines = []
    for line in text.split("\n"):
        line = line.strip()
        if not line or line.isdigit():
            continue
        if re.match(r'\d{2}:\d{2}:\d{2}[,.]\d{3}', line):
            continue
        line = re.sub(r'<[^>]+>', '', line)
        lines.append(line)
    return "\n".join(lines)


def _get_best_format_url(url: str, fmt: str) -> str:
    """Get direct media URL for best video/audio format."""
    try:
        result = subprocess.run(
            [YTDLP_PATH, "-f", fmt, "--get-url", "--no-playlist", url],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip().split("\n")[0]
    except Exception as e:
        log.warning("format_url_error: %s", e)
    return ""


def extract_video(url: str) -> Optional[dict]:
    """Extract metadata + transcript for a single video."""
    with tempfile.TemporaryDirectory() as tmpdir:
        result = subprocess.run(
            [
                YTDLP_PATH,
                "--write-subs", "--write-auto-subs",
                "--sub-lang", "en",
                "--convert-subs", "srt",
                "--skip-download",
                "--write-info-json",
                "-o", f"{tmpdir}/%(id)s.%(ext)s",
                url,
            ],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            log.warning("ytdlp_failed: %s", result.stderr[:200])
            return None

        info_files = list(Path(tmpdir).glob("*.info.json"))
        if not info_files:
            return None

        with open(info_files[0]) as f:
            info = json.load(f)

        # Find transcript
        subtitle_files = (
            list(Path(tmpdir).glob("*.en.srt")) +
            list(Path(tmpdir).glob("*.en.vtt")) +
            list(Path(tmpdir).glob("*.srt")) +
            list(Path(tmpdir).glob("*.vtt"))
        )
        transcript = ""
        if subtitle_files:
            transcript = _strip_srt(subtitle_files[0].read_text(errors="replace"))

        return {
            "id": info.get("id", ""),
            "url": info.get("webpage_url", url),
            "title": info.get("title", ""),
            "channel": info.get("channel") or info.get("uploader", ""),
            "channel_url": info.get("channel_url", ""),
            "description": (info.get("description") or "")[:3000],
            "duration": info.get("duration", 0),
            "upload_date": info.get("upload_date", ""),
            "view_count": info.get("view_count", 0),
            "like_count": info.get("like_count", 0),
            "comment_count": info.get("comment_count", 0),
            "transcript": transcript,
            "language": info.get("language") or "en",
            "tags": info.get("tags", []),
            "audio_url": _get_best_format_url(url, "bestaudio"),
            "video_url": _get_best_format_url(url, "best"),
        }


def list_channel_videos(url: str, limit: int = 20) -> list[str]:
    """List video URLs from a channel."""
    stdout, stderr = _run_ytdlp([
        "--flat-playlist", "--print", "webpage_url",
        "--playlist-end", str(limit), url,
    ])
    return [l.strip() for l in stdout.split("\n") if l.strip().startswith("http")]


# ─── Endpoints ────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "yt-extractor",
        "ytdlp_path": YTDLP_PATH,
    }


@app.get("/video")
async def get_video(url: str = Query(..., description="YouTube video URL")):
    """Extract full metadata + transcript for a single video."""
    data = extract_video(url)
    if not data:
        raise HTTPException(status_code=502, detail="Failed to extract video")
    data["has_transcript"] = bool(data.get("transcript"))
    return data


@app.post("/channel/list", response_model=ChannelListResponse)
async def list_channel(req: ChannelListRequest):
    """List video URLs from a channel."""
    channel_name = req.channel_url.rstrip("/").split("/")[-1].replace("@", "")
    urls = list_channel_videos(req.channel_url, req.limit)
    if not urls:
        raise HTTPException(status_code=404, detail="No videos found for channel")
    return ChannelListResponse(
        channel=channel_name,
        video_urls=urls,
        count=len(urls),
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
