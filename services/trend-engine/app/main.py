"""trend-engine — Viral trend analysis engine for Substrate.

Endpoints:
  POST /trends/analyze         — Analyze a single video for viral signals
  POST /trends/scan            — Scan warehouse for trending content
  GET  /trends/hot             — Current hot/trending content ranked by viral score
  GET  /trends/topics          — Trending topics with velocity
  POST /trends/compare         — Compare viral signals across multiple videos
  GET  /trends/signals/{id}    — Detailed viral signal breakdown for a video
  POST /trends/channel-pulse   — Channel-wide trend analysis
  GET  /health                 — Health check
"""

import asyncio
import hashlib
import json
import logging
import math
import os
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
import numpy as np
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [trend-engine] %(message)s",
)
log = logging.getLogger("trend-engine")

# ─── Config ───────────────────────────────────────────────────

WAREHOUSE_URL = os.environ.get("WAREHOUSE_URL", "http://knowledge-warehouse:8009")
YT_LAB_URL = os.environ.get("YT_LAB_URL", "http://localhost:8020")
INFERENCE_URL = os.environ.get("INFERENCE_URL", "http://inference_gateway:8005/v1/chat/completions")
DATA_DIR = Path(os.environ.get("TREND_DATA", "/app/data"))

app = FastAPI(title="trend-engine", version="1.0.0")

# ─── Models ───────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    video_url: str = Field(..., description="YouTube video URL")
    channel_url: Optional[str] = Field(None, description="Channel URL for baseline comparison")

class TrendSignal(BaseModel):
    """Viral signal decomposition for a single video."""
    video_id: str
    title: str
    channel: str
    views: int
    duration_seconds: int
    upload_date: str
    hours_since_upload: float

    # Raw signals
    view_velocity: float          # views per hour
    engagement_ratio: float       # (likes+comments)/views estimate
    like_count: int

    # Derived signals
    acceleration_score: float     # second derivative — is velocity increasing?
    outlier_score: float          # stddevs above channel baseline
    momentum: str                 # rising | stable | falling | cold

    # Composite
    viral_score: float            # 0.0–100.0 composite
    viral_tier: str               # cold | warm | hot | viral | megaviral

    # Trend metadata
    topics: list[str]
    signals_detail: dict = {}

class ScanRequest(BaseModel):
    max_videos: int = Field(default=50, ge=5, le=200)
    since_hours: int = Field(default=168, ge=1, le=720, description="Lookback window in hours")
    min_views: int = Field(default=1000, ge=0)

class ScanResponse(BaseModel):
    scanned: int
    trending: int
    hot_count: int
    viral_count: int
    results: list[TrendSignal]
    topics_trending: list[dict]
    scan_duration_seconds: float

class CompareRequest(BaseModel):
    video_urls: list[str] = Field(..., min_length=2, max_length=10)

class CompareResponse(BaseModel):
    videos: list[TrendSignal]
    winner: str
    insights: str

class ChannelPulseRequest(BaseModel):
    channel_url: str
    limit: int = Field(default=20, ge=5, le=100)

class ChannelPulseResponse(BaseModel):
    channel: str
    video_count: int
    average_viral_score: float
    trend_direction: str           # rising | stable | declining
    top_videos: list[TrendSignal]
    channel_summary: str


# ─── Viral Scoring Engine ─────────────────────────────────────

def _parse_iso_date(date_str: str) -> float:
    """Parse ISO-ish date to epoch. Handles YYYYMMDD and ISO formats."""
    if not date_str:
        return 0
    try:
        if len(date_str) == 8 and date_str.isdigit():
            dt = datetime.strptime(date_str, "%Y%m%d")
        else:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0


def _compute_viral_signals(
    video: dict,
    channel_baseline: Optional[dict] = None,
) -> TrendSignal:
    """Core scoring function — decompose a video into viral signals."""

    vid = str(video.get("id") or hashlib.md5((video.get("url") or "").encode()).hexdigest()[:11])
    title = video.get("title", "Unknown")
    channel = video.get("channel", "Unknown")
    views = int(video.get("view_count", 0) or 0)
    duration = int(video.get("duration", 0) or 60)
    like_count = int(video.get("like_count", 0) or 0)
    comment_count = int(video.get("comment_count", 0) or 0)
    upload_date = video.get("upload_date", "")

    # ── Time since upload ──
    upload_epoch = _parse_iso_date(upload_date)
    now = time.time()
    hours_since = max((now - upload_epoch) / 3600.0, 0.5)

    # ── View velocity (views/hour) ──
    view_velocity = views / hours_since if hours_since > 0 else 0

    # ── Engagement ratio ──
    # Weighted: likes 1.0, comments 2.0 (comments signal higher engagement)
    engagement = (like_count * 1.0 + comment_count * 2.0) / max(views, 1)
    engagement_ratio = min(engagement, 1.0)

    # ── Acceleration score ──
    # Estimate: if video is young + high velocity = accelerating
    # Young video (<24h) with high velocity gets boost
    youth_factor = max(0, 1.0 - (hours_since / 48.0))  # decays over 48h
    acceleration_score = min(view_velocity * youth_factor / 1000.0, 1.0)

    # ── Outlier score (vs channel baseline) ──
    outlier_score = 0.0
    if channel_baseline:
        baseline_vel = channel_baseline.get("avg_velocity", 0)
        baseline_std = channel_baseline.get("std_velocity", 1)
        if baseline_std > 0:
            outlier_score = min((view_velocity - baseline_vel) / baseline_std, 5.0)
    else:
        # Default baseline: typical video gets ~100 views/hour
        outlier_score = min(view_velocity / 200.0, 5.0)

    # ── Momentum ──
    if view_velocity > 10000:
        momentum = "rising"
    elif view_velocity > 1000:
        momentum = "stable"
    elif hours_since < 24 and view_velocity > 100:
        momentum = "rising"
    elif view_velocity > 10:
        momentum = "falling"
    else:
        momentum = "cold"

    # ── Composite viral score (0–100) ──
    # Weights: velocity 40%, engagement 15%, acceleration 25%, outlier 20%
    vel_norm = min(view_velocity / 10000.0, 1.0)
    viral_raw = (
        vel_norm * 0.40
        + engagement_ratio * 0.15
        + acceleration_score * 0.25
        + (outlier_score / 5.0) * 0.20
    )
    viral_score = round(viral_raw * 100, 1)

    # ── Viral tier ──
    if viral_score >= 80:
        tier = "megaviral"
    elif viral_score >= 60:
        tier = "viral"
    elif viral_score >= 35:
        tier = "hot"
    elif viral_score >= 15:
        tier = "warm"
    else:
        tier = "cold"

    # ── Topic extraction (keyword-based from title + tags) ──
    topics = _extract_topics(title, video.get("description", ""), video.get("tags", []))

    return TrendSignal(
        video_id=vid,
        title=title[:200],
        channel=channel,
        views=views,
        duration_seconds=duration,
        upload_date=upload_date,
        hours_since_upload=round(hours_since, 1),
        view_velocity=round(view_velocity, 1),
        engagement_ratio=round(engagement_ratio, 4),
        like_count=like_count,
        acceleration_score=round(acceleration_score, 4),
        outlier_score=round(outlier_score, 2),
        momentum=momentum,
        viral_score=viral_score,
        viral_tier=tier,
        topics=topics,
        signals_detail={
            "vel_norm": round(vel_norm, 4),
            "youth_factor": round(youth_factor, 4),
            "raw_score": round(viral_raw, 4),
        },
    )


# ─── Topic Extraction ─────────────────────────────────────────

TREND_KEYWORDS = {
    "ai": ["ai", "artificial intelligence", "machine learning", "llm", "gpt", "openai", "deepseek"],
    "coding": ["coding", "programming", "developer", "python", "rust", "javascript", "typescript"],
    "startup": ["startup", "saas", "indie hacker", "founder", "vc", "funding"],
    "tech_news": ["tech news", "launch", "released", "announced", "update"],
    "tutorial": ["tutorial", "how to", "guide", "walkthrough", "learn"],
    "crypto": ["crypto", "bitcoin", "ethereum", "blockchain", "defi", "nft", "web3"],
    "gaming": ["gaming", "gameplay", "walkthrough", "review", "esports"],
    "science": ["science", "physics", "biology", "chemistry", "research", "study"],
    "politics": ["politics", "election", "government", "policy", "president"],
    "drama": ["drama", "exposed", "controversy", "response", "apology", "beef"],
}

TOPIC_STOPWORDS = {"the", "a", "an", "is", "are", "was", "were", "and", "or", "of", "in", "to", "for", "with", "on", "at", "by", "this", "that", "it", "be", "has", "have", "from", "but", "not", "new", "video", "how", "why", "what"}


def _extract_topics(title: str, description: str, tags: list[str]) -> list[str]:
    """Extract trending topic categories from video metadata."""
    text = f"{title} {' '.join(tags)}".lower()
    matched = []

    for category, keywords in TREND_KEYWORDS.items():
        for kw in keywords:
            if kw in text:
                matched.append(category)
                break

    # Also extract significant N-grams from title as candidate topics
    words = [w.strip(".,!?()[]{}:;\"'") for w in title.lower().split()]
    words = [w for w in words if w and w not in TOPIC_STOPWORDS and len(w) > 2]
    bigrams = [" ".join(words[i:i+2]) for i in range(len(words)-1)]

    # Deduplicate
    seen = set(matched)
    result = matched.copy()
    for bg in bigrams:
        if bg not in seen:
            result.append(bg)
            seen.add(bg)

    return result[:8]


# ─── Warehouse / YT-Lab helpers ───────────────────────────────

async def _fetch_video_metadata(video_url: str) -> Optional[dict]:
    """Get full video metadata from yt-lab (view_count, like_count, upload_date, etc.)."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.get(
                f"{YT_LAB_URL}/videos/metadata",
                params={"video_url": video_url},
            )
            if resp.status_code == 200:
                return resp.json()
            log.warning(f"yt_lab_metadata_failed: {resp.status_code}")
    except Exception as e:
        log.warning(f"fetch_video_metadata_error: {e}")
    return None


async def _search_warehouse(query: str, limit: int = 20) -> list[dict]:
    """Search warehouse for content."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{WAREHOUSE_URL}/search", params={"q": query, "limit": limit})
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else data.get("results", [])
    except Exception as e:
        log.warning(f"warehouse_search_error: {e}")
        return []


async def _enrich_with_metadata(warehouse_results: list[dict], concurrency: int = 5) -> list[dict]:
    """Enrich warehouse results with live metadata from yt-lab.
    Fetches concurrently with bounded parallelism."""
    sem = asyncio.Semaphore(concurrency)

    async def fetch_one(r: dict) -> dict:
        url = r.get("url", "")
        if not url:
            return r
        async with sem:
            meta = await _fetch_video_metadata(url)
            if meta:
                # Merge: yt-lab metadata wins for numeric fields
                return {**r, **{k: v for k, v in meta.items() if v or k not in r}}
            return r

    tasks = [fetch_one(r) for r in warehouse_results]
    return list(await asyncio.gather(*tasks))


async def _compute_channel_baseline(channel_name: str) -> dict:
    """Compute baseline stats for a channel from warehouse data."""
    results = await _search_warehouse(channel_name, limit=50)
    velocities = []
    for r in results:
        view_count = int(r.get("view_count", 0) or 0)
        upload_date = r.get("published", "") or r.get("upload_date", "")
        hours = max((time.time() - _parse_iso_date(upload_date)) / 3600.0, 0.5) if upload_date else 168
        if view_count > 0:
            velocities.append(view_count / hours)

    if not velocities:
        return {"avg_velocity": 0, "std_velocity": 1, "count": 0}

    arr = np.array(velocities)
    return {
        "avg_velocity": float(np.mean(arr)),
        "std_velocity": float(np.std(arr)) if len(arr) > 1 else float(np.mean(arr)) * 0.5,
        "count": len(arr),
    }


# ─── LLM helpers ──────────────────────────────────────────────

async def _llm(prompt: str, system: str = "You are a trend analyst.", max_tokens: int = 1024) -> str:
    """Call inference_gateway."""
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(INFERENCE_URL, json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.7,
            })
            resp.raise_for_status()
            data = resp.json()
            return data.get("content", "") or data["choices"][0]["message"]["content"]
    except Exception as e:
        log.warning(f"llm_error: {e}")
        return ""


# ─── Persistence ──────────────────────────────────────────────

def _save_signals(signals: list[TrendSignal]):
    """Persist trend analysis to disk for historical tracking."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    path = DATA_DIR / f"trends-{ts}.json"
    path.write_text(json.dumps(
        [s.model_dump() for s in signals], indent=2, default=str
    ))
    log.info(f"saved {len(signals)} signals → {path}")


def _load_recent_signals(hours: int = 24) -> list[dict]:
    """Load recent trend data for trend-line analysis."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - hours * 3600
    signals = []
    for f in sorted(DATA_DIR.glob("trends-*.json"), reverse=True):
        try:
            data = json.loads(f.read_text())
            signals.extend(data)
        except Exception:
            continue
        if len(signals) > 500:
            break
    return signals


# ─── Endpoints ────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "trend-engine",
        "warehouse_url": WAREHOUSE_URL,
        "yt_lab_url": YT_LAB_URL,
    }


@app.post("/trends/analyze", response_model=TrendSignal)
async def analyze_video(req: AnalyzeRequest):
    """Analyze a single video for viral potential."""
    # Try yt-lab for metadata first
    metadata = await _fetch_video_metadata(req.video_url)

    if not metadata:
        # Fallback: search warehouse
        results = await _search_warehouse(req.video_url, limit=1)
        if results:
            metadata = results[0]
        else:
            raise HTTPException(
                status_code=404,
                detail="Video not found — ensure it's been ingested via yt-lab first",
            )

    # Compute channel baseline if provided
    channel_baseline = None
    channel_name = metadata.get("channel", "")
    if channel_name:
        channel_baseline = await _compute_channel_baseline(channel_name)

    signal = _compute_viral_signals(metadata, channel_baseline)

    # Use LLM to enrich with qualitative trend notes
    if signal.viral_score > 20:
        try:
            prompt = (
                f"Analyze this video's viral potential in 1-2 sentences. "
                f"Title: {signal.title}\n"
                f"Views: {signal.views}\n"
                f"Velocity: {signal.view_velocity} views/hr\n"
                f"Viral Score: {signal.viral_score}/100\n"
                f"Topics: {', '.join(signal.topics)}\n"
                f"Momentum: {signal.momentum}"
            )
            insight = await _llm(prompt, system="You analyze viral video trends. Be concise.", max_tokens=200)
            signal.signals_detail["ai_insight"] = insight.strip()
        except Exception:
            pass

    _save_signals([signal])
    return signal


@app.post("/trends/scan", response_model=ScanResponse)
async def scan_trends(req: ScanRequest):
    """Scan warehouse for trending content in the lookback window."""
    t0 = time.time()

    # Search warehouse for recent YouTube content
    results = await _search_warehouse("youtube", limit=req.max_videos)
    if not results:
        results = await _search_warehouse("video", limit=req.max_videos)

    signals = []
    channel_baselines = {}

    # Enrich warehouse results with live yt-lab metadata (view counts, etc.)
    enriched = await _enrich_with_metadata(results, concurrency=5)

    for r in enriched:
        channel = r.get("channel") or r.get("author", "")
        if channel and channel not in channel_baselines:
            channel_baselines[channel] = await _compute_channel_baseline(channel)

        signal = _compute_viral_signals(r, channel_baselines.get(channel))
        if signal.views >= req.min_views:
            signals.append(signal)

    # Sort by viral score descending
    signals.sort(key=lambda s: s.viral_score, reverse=True)

    # Classify
    hot = [s for s in signals if s.viral_tier in ("hot", "viral", "megaviral")]
    viral = [s for s in signals if s.viral_tier in ("viral", "megaviral")]

    # Extract trending topics
    topic_counter = defaultdict(float)
    for s in signals:
        for t in s.topics:
            topic_counter[t] += s.viral_score
    trending_topics = [
        {"topic": t, "score": round(s, 1), "count": sum(1 for sig in signals if t in sig.topics)}
        for t, s in sorted(topic_counter.items(), key=lambda x: x[1], reverse=True)[:15]
    ]

    _save_signals(signals[:req.max_videos])

    return ScanResponse(
        scanned=len(results),
        trending=len(hot),
        hot_count=len(hot),
        viral_count=len(viral),
        results=signals[:req.max_videos],
        topics_trending=trending_topics,
        scan_duration_seconds=round(time.time() - t0, 1),
    )


@app.get("/trends/hot")
async def hot_trends(limit: int = Query(default=20, ge=1, le=100)):
    """Get currently hot/trending content ranked by viral score."""
    recent = _load_recent_signals(hours=48)
    if not recent:
        # No cached data — do a live scan
        result = await scan_trends(ScanRequest(max_videos=limit))
        return {
            "source": "live_scan",
            "count": len(result.results),
            "hot": [s for s in result.results if s.viral_tier != "cold"],
        }

    # Re-score with current time
    signals = []
    for r in recent:
        try:
            sig = _compute_viral_signals(r)
            signals.append(sig)
        except Exception:
            continue

    signals.sort(key=lambda s: s.viral_score, reverse=True)
    hot = [s for s in signals if s.viral_tier != "cold"][:limit]

    return {
        "source": "cached",
        "age_hours": 48,
        "count": len(hot),
        "hot": [s.model_dump() for s in hot],
    }


@app.get("/trends/topics")
async def trending_topics(limit: int = Query(default=15, ge=1, le=50)):
    """Get trending topics with velocity scores."""
    recent = _load_recent_signals(hours=72)

    if not recent:
        result = await scan_trends(ScanRequest(max_videos=50))
        return {
            "source": "live_scan",
            "topics": result.topics_trending[:limit],
        }

    topic_scores = defaultdict(list)
    for r in recent:
        for t in r.get("topics", []):
            topic_scores[t].append(r.get("viral_score", 0))

    topics = []
    for topic, scores in topic_scores.items():
        arr = np.array(scores)
        topics.append({
            "topic": topic,
            "mean_score": round(float(np.mean(arr)), 1),
            "max_score": round(float(np.max(arr)), 1),
            "count": len(scores),
            "trend": "rising" if float(np.mean(arr[-3:])) > float(np.mean(arr[:-3])) else "stable"
            if len(arr) >= 6 else "new",
        })

    topics.sort(key=lambda t: t["mean_score"] * math.log(t["count"] + 1), reverse=True)
    return {"source": "cached", "topics": topics[:limit]}


@app.post("/trends/compare", response_model=CompareResponse)
async def compare_videos(req: CompareRequest):
    """Compare viral signals across multiple videos."""
    signals = []
    for url in req.video_urls:
        try:
            metadata = await _fetch_video_metadata(url)
            if metadata:
                channel_name = metadata.get("channel", "")
                baseline = await _compute_channel_baseline(channel_name) if channel_name else None
                signals.append(_compute_viral_signals(metadata, baseline))
        except Exception as e:
            log.warning(f"compare_skip: {url} — {e}")

    if len(signals) < 2:
        raise HTTPException(status_code=400, detail="Need at least 2 valid videos to compare")

    signals.sort(key=lambda s: s.viral_score, reverse=True)
    winner = signals[0]

    # LLM insight
    insights = ""
    if len(signals) >= 2:
        compare_text = "\n".join(
            f"- {s.title}: viral_score={s.viral_score}, views={s.views}, velocity={s.view_velocity}/hr, momentum={s.momentum}"
            for s in signals[:5]
        )
        prompt = (
            f"Compare these videos' viral potential in 2-3 sentences. Which is most likely to go viral and why?\n\n{compare_text}"
        )
        insights = await _llm(prompt, system="You are a viral trend analyst. Be concise.", max_tokens=300)

    return CompareResponse(
        videos=signals,
        winner=winner.title,
        insights=insights.strip(),
    )


@app.get("/trends/signals/{video_id}")
async def get_signals(video_id: str):
    """Get detailed viral signal breakdown for a specific video."""
    recent = _load_recent_signals(hours=168)  # last 7 days
    for r in recent:
        if r.get("video_id") == video_id or r.get("id") == video_id:
            return r
    raise HTTPException(status_code=404, detail="Signal data not found for this video")


@app.post("/trends/channel-pulse", response_model=ChannelPulseResponse)
async def channel_pulse(req: ChannelPulseRequest):
    """Channel-wide trend analysis — scan a channel for viral signals."""
    channel_name = req.channel_url.rstrip("/").split("/")[-1].replace("@", "")

    # Search warehouse for channel content
    results = await _search_warehouse(channel_name, limit=req.limit)
    if not results:
        raise HTTPException(status_code=404, detail=f"No content found for channel '{channel_name}'")

    # Enrich with live yt-lab metadata
    enriched = await _enrich_with_metadata(results, concurrency=5)

    baseline = await _compute_channel_baseline(channel_name)
    signals = [_compute_viral_signals(r, baseline) for r in enriched]
    signals.sort(key=lambda s: s.viral_score, reverse=True)

    avg_score = np.mean([s.viral_score for s in signals]) if signals else 0
    scores = [s.viral_score for s in signals]
    if len(scores) >= 3:
        recent_avg = np.mean(scores[:3])
        older_avg = np.mean(scores[-3:])
        if recent_avg > older_avg * 1.2:
            direction = "rising"
        elif recent_avg < older_avg * 0.8:
            direction = "declining"
        else:
            direction = "stable"
    else:
        direction = "stable"

    # LLM channel summary
    summary = ""
    top_titles = [s.title for s in signals[:5]]
    try:
        prompt = (
            f"Summarize this YouTube channel's trend trajectory in 2-3 sentences. "
            f"Channel: {channel_name}\n"
            f"Avg viral score: {round(avg_score, 1)}/100\n"
            f"Trend: {direction}\n"
            f"Top videos: {', '.join(top_titles)}\n"
            f"Topics: {', '.join(signals[0].topics) if signals else 'none'}"
        )
        summary = await _llm(prompt, system="You analyze YouTube channel trends. Be concise.", max_tokens=300)
    except Exception:
        pass

    _save_signals(signals[:20])

    return ChannelPulseResponse(
        channel=channel_name,
        video_count=len(signals),
        average_viral_score=round(avg_score, 1),
        trend_direction=direction,
        top_videos=signals[:10],
        channel_summary=summary.strip(),
    )


# ─── Startup ──────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log.info("trend_engine_started: warehouse=%s yt_lab=%s", WAREHOUSE_URL, YT_LAB_URL)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("TREND_ENGINE_PORT", "8021")))
