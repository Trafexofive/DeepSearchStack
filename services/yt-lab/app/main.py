"""yt-lab — YouTube automation service for Substrate.

Endpoints:
  POST /channels/ingest      — Ingest channel videos (transcripts → warehouse)
  POST /channels/watch       — Start watching a channel for new videos
  GET  /channels/watching    — List watched channels
  POST /videos/summarize     — TL;DR summary of a video
  POST /videos/crossref      — Cross-reference video with warehouse content
  POST /videos/ingest        — Single video ingest
  GET  /health               — Health check
"""
import asyncio
import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [yt-lab] %(message)s")
log = logging.getLogger("yt-lab")

# ─── Config ───────────────────────────────────────────────────

WAREHOUSE_URL = os.environ.get("WAREHOUSE_URL", "http://dss-knowledge-warehouse:8009")
INFERENCE_URL = os.environ.get("INFERENCE_URL", "http://inference_gateway:8005/v1/chat/completions")
WEB_API_URL = os.environ.get("WEB_API_URL", "http://dss-web-api:8014")
YTDLP_PATH = os.environ.get("YTDLP_PATH", "yt-dlp")
DATA_DIR = Path(os.environ.get("YT_LAB_DATA", "/app/data"))

app = FastAPI(title="yt-lab", version="0.1.0")

# ─── Models ───────────────────────────────────────────────────

class ChannelIngestRequest(BaseModel):
    channel_url: str = Field(..., description="YouTube channel URL (@handle or /channel/ID)")
    limit: int = Field(default=20, ge=1, le=100)
    summarize: bool = Field(default=False, description="Generate LLM summary after ingest")

class WatchRequest(BaseModel):
    channel_url: str
    interval_hours: int = Field(default=6, ge=1, le=48)

class VideoRequest(BaseModel):
    video_url: str = Field(..., description="YouTube video URL")

class SummarizeRequest(BaseModel):
    video_url: str
    style: str = Field(default="bullet", description="bullet, paragraph, or tl;dr")

class CrossrefRequest(BaseModel):
    video_url: str
    max_results: int = Field(default=5)

class IngestResponse(BaseModel):
    channel: str
    videos_found: int
    videos_ingested: int
    summary: Optional[str] = None
    duration_seconds: float

class WatchingChannel(BaseModel):
    channel_url: str
    last_checked: str
    interval_hours: int


# ─── State ────────────────────────────────────────────────────

watching: dict[str, WatchingChannel] = {}
_watch_task: Optional[asyncio.Task] = None


# ─── yt-dlp wrapper ───────────────────────────────────────────

def _run_ytdlp(args: list[str], timeout: int = 120) -> tuple[str, str]:
    """Run yt-dlp, return (stdout, stderr)."""
    result = subprocess.run(
        [YTDLP_PATH] + args,
        capture_output=True, text=True, timeout=timeout,
    )
    return result.stdout, result.stderr


def _extract_video(url: str) -> dict | None:
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
            "transcript": transcript,
            "language": info.get("language") or "en",
            "tags": info.get("tags", []),
        }


def _list_channel(url: str, limit: int = 20) -> list[str]:
    """List video URLs from a channel."""
    stdout, stderr = _run_ytdlp([
        "--flat-playlist", "--print", "webpage_url",
        "--playlist-end", str(limit), url,
    ])
    return [l.strip() for l in stdout.split("\n") if l.strip().startswith("http")]


def _strip_srt(text: str) -> str:
    """Remove SRT/VTT timestamps, keep text."""
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


# ─── Transcription abstraction ────────────────────────────────

async def _transcribe(audio_path: str) -> str:
    """Abstract transcription interface. Currently: no-op (relies on yt-dlp subs).
    
    To add: swap in whisper.cpp, Whisper API, or any transcription backend.
    The rest of the service doesn't need to change.
    """
    return ""  # yt-dlp already extracts subtitles


# ─── Warehouse helpers ────────────────────────────────────────

async def _store_in_warehouse(data: dict) -> bool:
    """Store video transcript in warehouse."""
    if not data.get("transcript"):
        return False
    payload = {
        "url": data["url"],
        "markdown": f"Channel: {data['channel']}\nDuration: {data['duration']}s\n"
                    f"Views: {data['view_count']}\nUploaded: {data['upload_date']}\n\n{data['transcript']}",
        "title": data["title"],
        "author": data["channel"],
        "published": data.get("upload_date", ""),
        "language": data.get("language", "en"),
        "word_count": len(data["transcript"].split()),
        "source_domain": "youtube.com",
        "tags": ["youtube", data["channel"]],
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(f"{WAREHOUSE_URL}/ingest", json=payload)
        return resp.status_code == 200


async def _search_warehouse(query: str, limit: int = 5) -> list[dict]:
    """Search warehouse for related content."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(f"{WAREHOUSE_URL}/search", params={"q": query, "limit": limit})
        resp.raise_for_status()
        return resp.json()


# ─── LLM helpers ──────────────────────────────────────────────

async def _llm(prompt: str, system: str = "You are a helpful assistant.", max_tokens: int = 1024) -> str:
    """Call inference_gateway for LLM completion."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.post(
            INFERENCE_URL,
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.7,
            },
        )
        resp.raise_for_status()
        return resp.json().get("content", "") or resp.json()["choices"][0]["message"]["content"]


# ─── Endpoints ────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "watching": len(watching)}


@app.post("/videos/ingest", response_model=IngestResponse)
async def ingest_video(req: VideoRequest):
    """Ingest a single video — transcript → warehouse."""
    t0 = time.time()
    data = _extract_video(req.video_url)
    if not data:
        raise HTTPException(status_code=502, detail="Failed to extract video")
    ok = await _store_in_warehouse(data)
    return IngestResponse(
        channel=data["channel"],
        videos_found=1,
        videos_ingested=1 if ok else 0,
        duration_seconds=round(time.time() - t0, 1),
    )


@app.post("/videos/summarize")
async def summarize(req: SummarizeRequest):
    """TL;DR summary of a video."""
    data = _extract_video(req.video_url)
    if not data or not data.get("transcript"):
        raise HTTPException(status_code=404, detail="No transcript available")

    transcript = data["transcript"][:8000]
    style_prompts = {
        "bullet": f"Summarize this video in 5-7 bullet points:\n\n{transcript}",
        "paragraph": f"Write a 2-paragraph summary of this video:\n\n{transcript}",
        "tl;dr": f"Write a single-sentence TL;DR and then 3 key takeaways:\n\n{transcript}",
    }
    prompt = style_prompts.get(req.style, style_prompts["bullet"])
    summary = await _llm(prompt, system="You summarize YouTube videos concisely.", max_tokens=512)

    return {
        "title": data["title"],
        "channel": data["channel"],
        "duration": data["duration"],
        "summary": summary,
        "style": req.style,
    }


@app.post("/videos/crossref")
async def crossref(req: CrossrefRequest):
    """Cross-reference a video with warehouse content."""
    data = _extract_video(req.video_url)
    if not data:
        raise HTTPException(status_code=502, detail="Failed to extract video")

    # Search warehouse for related content
    title = data["title"]
    results = await _search_warehouse(title, limit=req.max_results)

    # Also search by first meaningful sentence of transcript
    if data.get("transcript"):
        first_sentence = data["transcript"].split(".")[0][:200]
        more = await _search_warehouse(first_sentence, limit=3)
        seen = {r.get("url") for r in results}
        results.extend(r for r in more if r.get("url") not in seen)

    return {
        "video_title": title,
        "channel": data["channel"],
        "related_content": [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "domain": r.get("source_domain", ""),
                "snippet": r.get("snippet", "")[:200],
            }
            for r in results[:req.max_results]
        ],
    }


@app.post("/channels/ingest", response_model=IngestResponse)
async def ingest_channel(req: ChannelIngestRequest):
    """Ingest a channel's videos — all transcripts → warehouse."""
    t0 = time.time()

    # Extract channel name from URL
    channel_name = req.channel_url.rstrip("/").split("/")[-1].replace("@", "")

    urls = _list_channel(req.channel_url, req.limit)
    if not urls:
        raise HTTPException(status_code=404, detail="No videos found for channel")

    log.info(f"channel_ingest: {channel_name} — {len(urls)} videos")

    ingested = 0
    transcripts_all = []

    for i, url in enumerate(urls):
        data = _extract_video(url)
        if data:
            if await _store_in_warehouse(data):
                ingested += 1
            if data.get("transcript"):
                transcripts_all.append(data)
        if (i + 1) % 10 == 0:
            log.info(f"channel_progress: {i+1}/{len(urls)}")

    # Optional: generate channel summary
    summary = None
    if req.summarize and transcripts_all:
        # Compile top 5 transcripts for summary
        top = sorted(transcripts_all, key=lambda d: d.get("view_count", 0), reverse=True)[:5]
        content = "\n\n---\n\n".join(
            f"Video: {d['title']}\n{d['transcript'][:3000]}"
            for d in top
        )
        prompt = f"Summarize what this YouTube channel is about, based on these videos:\n\n{content}"
        summary = await _llm(prompt, system="You analyze YouTube channels.", max_tokens=1024)

    return IngestResponse(
        channel=channel_name,
        videos_found=len(urls),
        videos_ingested=ingested,
        summary=summary,
        duration_seconds=round(time.time() - t0, 1),
    )


@app.post("/channels/watch")
async def watch_channel(req: WatchRequest, background: BackgroundTasks):
    """Start watching a channel for new videos."""
    channel_name = req.channel_url.rstrip("/").split("/")[-1]
    watching[channel_name] = WatchingChannel(
        channel_url=req.channel_url,
        last_checked=datetime.now(timezone.utc).isoformat(),
        interval_hours=req.interval_hours,
    )
    _save_watching()
    log.info(f"watching: {channel_name} (every {req.interval_hours}h)")
    return {"status": "watching", "channel": channel_name, "interval_hours": req.interval_hours}


@app.get("/channels/watching")
async def list_watching():
    return {"channels": list(watching.values())}


async def _watch_loop():
    """Background loop: check watched channels for new videos."""
    while True:
        await asyncio.sleep(3600)  # check every hour
        for name, wc in list(watching.items()):
            try:
                urls = _list_channel(wc.channel_url, 5)
                for url in urls:
                    data = _extract_video(url)
                    if data:
                        await _store_in_warehouse(data)
            except Exception as e:
                log.warning(f"watch_error: {name} — {e}")


def _save_watching():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    (DATA_DIR / "watching.json").write_text(
        json.dumps({k: v.dict() for k, v in watching.items()})
    )


@app.on_event("startup")
async def startup():
    global _watch_task
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    # Restore watching state
    watch_file = DATA_DIR / "watching.json"
    if watch_file.exists():
        data = json.loads(watch_file.read_text())
        for k, v in data.items():
            watching[k] = WatchingChannel(**v)
    _watch_task = asyncio.create_task(_watch_loop())
    log.info("yt_lab_started: watching=%d channels", len(watching))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8020)
