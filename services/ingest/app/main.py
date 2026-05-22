"""
Ingest service — RSS feed watcher, content extraction, auto-generation.

Pipeline:
  1. Poll RSS feeds on interval
  2. Detect new entries (by GUID)
  3. Extract full content via crawler:8004
  4. Generate researched blog post via blog_generator:8006
  5. Store in output directory (ready for human review)
"""

import asyncio
import hashlib
import os
import signal
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.logger import get_logger
from app.feed_watcher import FeedWatcher
from app.extractor import extract_content
from app.publisher import generate_post, store_draft

# ─── Config ────────────────────────────────────────────────
CONFIG_PATH = os.environ.get("INGEST_CONFIG", "/app/config/feeds.yml")
OUTPUT_DIR = Path(os.environ.get("INGEST_OUTPUT_DIR", "/app/volumes/data/output"))
STATE_DIR = Path(os.environ.get("INGEST_STATE_DIR", "/app/volumes/data"))

CRAWLER_URL = os.environ.get("CRAWLER_URL", "http://dss-crawler:8000")
BLOG_GENERATOR_URL = os.environ.get("BLOG_GENERATOR_URL", "http://blog_generator:8006")

log = get_logger(__name__)

# ─── State ─────────────────────────────────────────────────
watcher: Optional[FeedWatcher] = None
http_client: Optional[httpx.AsyncClient] = None
pipeline_stats = {
    "feeds_watched": 0,
    "entries_detected": 0,
    "posts_generated": 0,
    "posts_published": 0,
    "last_scan": None,
    "errors": 0,
}
# In-memory simple state for seen GUIDs
_seen_guids: set = set()

# ─── Init ──────────────────────────────────────────────────
def load_config():
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    feeds = [f for f in cfg.get("feeds", []) if f.get("enabled", True)]
    gen = cfg.get("generation", {})
    return feeds, gen

async def run_pipeline(feed: dict, gen: dict):
    """Full pipeline for a single feed: poll → extract → generate."""
    global pipeline_stats

    feed_url = feed["url"]
    category = feed.get("category", "news")
    tags = feed.get("tags", [])
    log.info(f"scanning feed", feed_url=feed_url, category=category)

    try:
        entries = await watcher.poll(feed_url)
    except Exception as e:
        log.error("feed_poll_failed", feed_url=feed_url, error=str(e))
        pipeline_stats["errors"] += 1
        return

    pipeline_stats["last_scan"] = datetime.now(timezone.utc).isoformat()

    for entry in entries:
        guid = entry.get("guid") or entry.get("link") or hashlib.sha256(
            (entry.get("title") + entry.get("link", "")).encode()
        ).hexdigest()

        if guid in _seen_guids:
            continue
        _seen_guids.add(guid)

        pipeline_stats["entries_detected"] += 1
        entry_url = entry.get("link", "")
        title = entry.get("title", "Untitled")
        log.info("new_entry", title=title, url=entry_url)

        # Extract full content
        content = await extract_content(http_client, CRAWLER_URL, entry_url)
        if not content or len(content) < gen.get("min_content_length", 500):
            log.info("skipping_short_content", title=title, length=len(content or ""))
            continue

        # Generate researched post
        topic = f"{title} — analysis and technical breakdown"
        try:
            result = await generate_post(
                http_client,
                BLOG_GENERATOR_URL,
                topic=topic,
                style=gen.get("style", "technical"),
                model=gen.get("model", "deepseek-v4-flash"),
                max_tokens=gen.get("max_tokens", 2048),
                temperature=gen.get("temperature", 0.7),
            )

            # Store draft
            draft_path = store_draft(
                OUTPUT_DIR,
                title=title,
                category=category,
                tags=tags,
                content=result.get("content", ""),
                sources=result.get("sources", []),
                source_url=entry_url,
                model=result.get("model", "unknown"),
                cost_usd=result.get("cost_usd", 0),
                tokens=result.get("usage", {}).get("total_tokens", 0),
            )

            pipeline_stats["posts_generated"] += 1
            log.info("post_generated", title=title, path=str(draft_path),
                     cost=result.get("cost_usd"), tokens=result.get("usage", {}).get("total_tokens"))

        except Exception as e:
            log.error("generation_failed", title=title, error=str(e))
            pipeline_stats["errors"] += 1
            continue

        # Rate limit between generations
        await asyncio.sleep(5)

async def scan_all_feeds():
    """Scan all enabled feeds."""
    feeds, gen = load_config()
    pipeline_stats["feeds_watched"] = len(feeds)
    log.info("scanning_all_feeds", count=len(feeds))

    for feed in feeds:
        await run_pipeline(feed, gen)

async def scheduler_loop(interval_seconds: int = 300):
    """Background scheduler — scans all feeds on interval."""
    log.info("scheduler_started", interval_seconds=interval_seconds)
    while True:
        try:
            await scan_all_feeds()
        except Exception as e:
            log.error("scheduler_error", error=str(e))
        await asyncio.sleep(interval_seconds)

# ─── FastAPI App ──────────────────────────────────────────
app = FastAPI(title="Substrate Ingest Service", version="1.0.0")

@app.on_event("startup")
async def startup():
    global watcher, http_client
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
    watcher = FeedWatcher(http_client)

    # Load seen GUIDs from output dir
    if OUTPUT_DIR.exists():
        for f in OUTPUT_DIR.glob("*.md*"):
            _seen_guids.add(f.stem)

    # Start background scheduler
    feeds, _ = load_config()
    interval = min((f.get("interval_minutes", 60) for f in feeds), default=60) * 60
    asyncio.create_task(scheduler_loop(interval))
    log.info("ingest_service_started", feeds=len(feeds), interval_seconds=interval)

@app.on_event("shutdown")
async def shutdown():
    if http_client:
        await http_client.aclose()
    log.info("ingest_service_shutdown")

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "feeds_watched": pipeline_stats["feeds_watched"],
        "entries_detected": pipeline_stats["entries_detected"],
        "posts_generated": pipeline_stats["posts_generated"],
        "last_scan": pipeline_stats["last_scan"],
        "dependencies": {
            "crawler": CRAWLER_URL,
            "blog_generator": BLOG_GENERATOR_URL,
        },
    }

@app.get("/stats")
async def stats():
    feeds, gen = load_config()
    return {
        **pipeline_stats,
        "feeds_configured": len(feeds),
        "generation_config": gen,
        "output_dir": str(OUTPUT_DIR),
        "drafts_count": len(list(OUTPUT_DIR.glob("*.md"))) if OUTPUT_DIR.exists() else 0,
    }

@app.get("/drafts")
async def list_drafts():
    if not OUTPUT_DIR.exists():
        return {"drafts": []}
    drafts = []
    for f in sorted(OUTPUT_DIR.glob("*.md*"), key=lambda x: x.stat().st_mtime, reverse=True):
        drafts.append({
            "filename": f.name,
            "size": f.stat().st_size,
            "modified": datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc).isoformat(),
        })
    return {"drafts": drafts[:50], "total": len(drafts)}

class ScanRequest(BaseModel):
    feed_url: Optional[str] = None

@app.post("/scan")
async def trigger_scan(req: ScanRequest = ScanRequest()):
    """Manually trigger a scan. Optionally limit to one feed URL."""
    if req.feed_url:
        feeds, gen = load_config()
        target = next((f for f in feeds if f["url"] == req.feed_url), None)
        if not target:
            raise HTTPException(status_code=404, detail="Feed not found in config")
        await run_pipeline(target, gen)
        return {"scanned": 1, "feed": req.feed_url}
    else:
        await scan_all_feeds()
        return {"scanned": pipeline_stats["feeds_watched"]}

@app.get("/feeds")
async def list_feeds():
    feeds, gen = load_config()
    return {
        "feeds": [{"url": f["url"], "category": f.get("category"), "enabled": f.get("enabled", True)} for f in feeds],
        "generation": gen,
    }

# ─── Main ─────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("INGEST_PORT", "8008")))
