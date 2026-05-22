"""yt-lab — YouTube automation orchestrator for Substrate.

Endpoints:
  POST /channels/ingest      — Ingest channel videos (extract → warehouse)
  POST /channels/watch       — Start background monitoring of a channel
  GET  /channels/watching    — List watched channels
  POST /videos/summarize     — TL;DR summary via inference-gateway
  POST /videos/crossref      — Cross-reference with warehouse content
  POST /videos/ingest        — Single video ingest
  GET  /health               — Health check

Depends on:
  - yt-extractor:8020 (yt-dlp extraction)
  - inference-gateway:8005 (LLM summarization)
  - knowledge-warehouse:8009 (transcript storage)
  - humanizer:8013 (optional — humanize summaries)
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [yt-lab] %(message)s")
log = logging.getLogger("yt-lab")

# ─── Config ───────────────────────────────────────────────────

EXTRACTOR_URL = os.environ.get("EXTRACTOR_URL", "http://localhost:8020")
WAREHOUSE_URL = os.environ.get("WAREHOUSE_URL", "http://knowledge-warehouse:8009")
INFERENCE_URL = os.environ.get("INFERENCE_URL", "http://inference-gateway:8005/v1/chat/completions")
HUMANIZER_URL = os.environ.get("HUMANIZER_URL", "http://humanizer:8013")
DATA_DIR = Path(os.environ.get("YT_LAB_DATA", "/app/data"))
INCLUDE_TRANSCRIPT_IN_WAREHOUSE = os.environ.get("INCLUDE_TRANSCRIPT", "true").lower() == "true"

app = FastAPI(title="yt-lab", version="0.2.0")

# ─── Models ───────────────────────────────────────────────────

class ChannelIngestRequest(BaseModel):
    channel_url: str = Field(..., description="YouTube channel URL (@handle or /channel/ID)")
    limit: int = Field(default=20, ge=1, le=100)
    summarize: bool = Field(default=False, description="Generate LLM summary after ingest")
    humanize: bool = Field(default=False, description="Humanize the summary via humanizer service")

class WatchRequest(BaseModel):
    channel_url: str
    interval_hours: int = Field(default=6, ge=1, le=48)

class VideoRequest(BaseModel):
    video_url: str = Field(..., description="YouTube video URL")

class SummarizeRequest(BaseModel):
    video_url: str
    style: str = Field(default="bullet", description="bullet, paragraph, or tl;dr")
    humanize: bool = Field(default=False)

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


# ─── Extractor client ─────────────────────────────────────────

async def _extract_video(url: str) -> dict | None:
    """Call yt-extractor for video metadata + transcript."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(f"{EXTRACTOR_URL}/video", params={"url": url})
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        log.warning("extractor_error: %s — %s", url[:60], e)
        return None


async def _list_channel(url: str, limit: int = 20) -> list[str]:
    """Call yt-extractor to list channel videos."""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{EXTRACTOR_URL}/channel/list",
                json={"channel_url": url, "limit": limit},
            )
            resp.raise_for_status()
            return resp.json().get("video_urls", [])
    except Exception as e:
        log.warning("extractor_channel_error: %s", e)
        return []


# ─── Warehouse helpers ────────────────────────────────────────

async def _store_in_warehouse(data: dict) -> bool:
    """Store video transcript in warehouse."""
    transcript = data.get("transcript", "")
    if not transcript or not INCLUDE_TRANSCRIPT_IN_WAREHOUSE:
        return False

    payload = {
        "url": data["url"],
        "markdown": (
            f"Channel: {data['channel']}\n"
            f"Duration: {data['duration']}s\n"
            f"Views: {data['view_count']}\n"
            f"Uploaded: {data['upload_date']}\n\n"
            f"{transcript}"
        ),
        "title": data["title"],
        "author": data["channel"],
        "published": data.get("upload_date", ""),
        "language": data.get("language", "en"),
        "word_count": len(transcript.split()),
        "source_domain": "youtube.com",
        "tags": ["youtube", data["channel"]],
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{WAREHOUSE_URL}/ingest", json=payload)
            return resp.status_code == 200
    except Exception as e:
        log.warning("warehouse_ingest_error: %s", e)
        return False


async def _search_warehouse(query: str, limit: int = 5) -> list[dict]:
    """Search warehouse for related content."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{WAREHOUSE_URL}/search", params={"q": query, "limit": limit})
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        log.warning("warehouse_search_error: %s", e)
        return []


# ─── LLM helpers ──────────────────────────────────────────────

async def _llm(prompt: str, system: str = "You are a helpful assistant.", max_tokens: int = 1024) -> str:
    """Call inference_gateway for LLM completion."""
    try:
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
            data = resp.json()
            return data.get("content", "") or data.get("choices", [{}])[0].get("message", {}).get("content", "")
    except Exception as e:
        log.warning("llm_error: %s", e)
        raise HTTPException(status_code=502, detail=f"LLM error: {str(e)}")


async def _humanize(text: str, style: str = "neutral") -> str | None:
    """Optionally humanize text via humanizer service."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{HUMANIZER_URL}/humanize",
                json={"text": text, "style": style, "intensity": 0.6},
            )
            if resp.status_code == 200:
                return resp.json().get("text", text)
            log.warning("humanizer_error: %s — %s", resp.status_code, resp.text[:200])
            return text
    except Exception as e:
        log.warning("humanizer_unavailable: %s", e)
        return text  # graceful degradation


# ─── Endpoints ────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "yt-lab",
        "version": "0.2.0",
        "watching": len(watching),
        "dependencies": {
            "extractor": EXTRACTOR_URL,
            "inference": INFERENCE_URL,
            "warehouse": WAREHOUSE_URL,
            "humanizer": HUMANIZER_URL,
        },
    }


@app.get("/videos/metadata")
async def video_metadata(video_url: str):
    """Return full metadata for a video without ingesting."""
    data = await _extract_video(video_url)
    if not data:
        raise HTTPException(status_code=502, detail="Failed to extract video")
    return data


@app.post("/videos/ingest", response_model=IngestResponse)
async def ingest_video(req: VideoRequest):
    """Ingest a single video — transcript → warehouse."""
    t0 = time.time()
    data = await _extract_video(req.video_url)
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
    data = await _extract_video(req.video_url)
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

    if req.humanize:
        summary = await _humanize(summary, style="professional") or summary

    return {
        "title": data["title"],
        "channel": data["channel"],
        "duration": data["duration"],
        "summary": summary,
        "style": req.style,
        "humanized": req.humanize,
    }


@app.post("/videos/crossref")
async def crossref(req: CrossrefRequest):
    """Cross-reference a video with warehouse content."""
    data = await _extract_video(req.video_url)
    if not data:
        raise HTTPException(status_code=502, detail="Failed to extract video")

    title = data["title"]
    results = await _search_warehouse(title, limit=req.max_results)

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

    channel_name = req.channel_url.rstrip("/").split("/")[-1].replace("@", "")
    urls = await _list_channel(req.channel_url, req.limit)
    if not urls:
        raise HTTPException(status_code=404, detail="No videos found for channel")

    log.info("channel_ingest: %s — %d videos", channel_name, len(urls))

    ingested = 0
    transcripts_all = []

    for i, url in enumerate(urls):
        data = await _extract_video(url)
        if data:
            if await _store_in_warehouse(data):
                ingested += 1
            if data.get("transcript"):
                transcripts_all.append(data)
        if (i + 1) % 10 == 0:
            log.info("channel_progress: %d/%d", i + 1, len(urls))

    summary = None
    if req.summarize and transcripts_all:
        top = sorted(transcripts_all, key=lambda d: d.get("view_count", 0), reverse=True)[:5]
        content = "\n\n---\n\n".join(
            f"Video: {d['title']}\n{d['transcript'][:3000]}"
            for d in top
        )
        prompt = f"Summarize what this YouTube channel is about, based on these videos:\n\n{content}"
        summary = await _llm(prompt, system="You analyze YouTube channels.", max_tokens=1024)

        if req.humanize and summary:
            summary = await _humanize(summary, style="professional") or summary

    return IngestResponse(
        channel=channel_name,
        videos_found=len(urls),
        videos_ingested=ingested,
        summary=summary,
        duration_seconds=round(time.time() - t0, 1),
    )


@app.post("/channels/watch")
async def watch_channel(req: WatchRequest):
    """Start watching a channel for new videos."""
    channel_name = req.channel_url.rstrip("/").split("/")[-1]
    watching[channel_name] = WatchingChannel(
        channel_url=req.channel_url,
        last_checked=datetime.now(timezone.utc).isoformat(),
        interval_hours=req.interval_hours,
    )
    _save_watching()
    log.info("watching: %s (every %dh)", channel_name, req.interval_hours)
    return {"status": "watching", "channel": channel_name, "interval_hours": req.interval_hours}


@app.get("/channels/watching")
async def list_watching():
    return {"channels": list(watching.values())}


# ─── Background watch loop ────────────────────────────────────

async def _watch_loop():
    """Check watched channels for new videos every hour."""
    while True:
        await asyncio.sleep(3600)
        for name, wc in list(watching.items()):
            try:
                urls = await _list_channel(wc.channel_url, 5)
                for url in urls:
                    data = await _extract_video(url)
                    if data:
                        await _store_in_warehouse(data)
            except Exception as e:
                log.warning("watch_error: %s — %s", name, e)


def _save_watching():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    watch_file = DATA_DIR / "watching.json"
    watch_file.write_text(
        json.dumps({k: v.model_dump() for k, v in watching.items()})
    )


@app.on_event("startup")
async def startup():
    global _watch_task
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    watch_file = DATA_DIR / "watching.json"
    if watch_file.exists():
        data = json.loads(watch_file.read_text())
        for k, v in data.items():
            watching[k] = WatchingChannel(**v)
    _watch_task = asyncio.create_task(_watch_loop())
    log.info("yt_lab_started: watching=%d channels", len(watching))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8021)
