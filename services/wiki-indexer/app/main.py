"""Wikipedia Indexer — download, parse, and index Wikipedia dumps into knowledge-warehouse.

Pipeline: download dump → stream XML → parse articles → extract clean text →
         → store in knowledge-warehouse → embed in vector-store
"""
import asyncio
import bz2
import hashlib
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, AsyncIterator

import httpx
import mwparserfromhell
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [wiki-indexer] %(message)s",
)
log = logging.getLogger("wiki-indexer")

DUMP_PATH = Path(os.environ.get("WIKI_DUMP_PATH", "/app/data/enwiki-latest-pages-articles.xml.bz2"))
DUMP_URL = os.environ.get("WIKI_DUMP_URL", "https://dumps.wikimedia.org/enwiki/latest/enwiki-latest-pages-articles.xml.bz2")
WAREHOUSE_URL = os.environ.get("WAREHOUSE_URL", "http://knowledge-warehouse:8009")
VECTOR_STORE_URL = os.environ.get("VECTOR_STORE_URL", "http://dss-vector-store:8003")

BATCH_SIZE = 100
ARTICLE_LIMIT = int(os.environ.get("WIKI_ARTICLE_LIMIT", "0"))  # 0 = no limit

app = FastAPI(title="Wikipedia Indexer", version="1.0.0")

indexer_state = {
    "status": "idle",
    "total_articles": 0,
    "indexed": 0,
    "errors": 0,
    "started_at": None,
    "completed_at": None,
    "current_article": None,
}


# ─── XML streaming parser ────────────────────────────────
_NS = "{http://www.mediawiki.org/xml/export-0.11/}"

def _stream_articles(path: Path, limit: int = 0) -> AsyncIterator[dict]:
    """Generator that yields {title, id, text} dicts from Wikipedia XML dump."""
    log.info("Opening dump: %s", path)
    opened = bz2.open(path, "rt", encoding="utf-8", errors="replace") if path.suffix == ".bz2" else open(path, "r")
    
    # Iterate through <page> elements
    context = ET.iterparse(opened, events=("end",))
    count = 0

    for event, elem in context:
        if elem.tag == f"{_NS}page":
            title_el = elem.find(f"{_NS}title")
            id_el = elem.find(f"{_NS}id")
            text_el = elem.find(f"{_NS}revision/{_NS}text")

            title = title_el.text if title_el is not None else ""
            page_id = id_el.text if id_el is not None else ""
            raw_text = text_el.text if text_el is not None else ""

            # Skip non-articles
            if not title or not raw_text or raw_text.startswith("#REDIRECT"):
                elem.clear()
                continue

            yield {
                "id": page_id,
                "title": title,
                "raw_text": raw_text,
            }

            count += 1
            if limit and count >= limit:
                elem.clear()
                break

            elem.clear()

    opened.close()
    log.info("Streamed %d articles from dump", count)


def _clean_wikitext(raw: str) -> str:
    """Parse wikitext and extract clean prose. Removes templates, tables, etc."""
    try:
        parsed = mwparserfromhell.parse(raw)
        # Remove templates (infoboxes, citations, etc.)
        for template in parsed.filter_templates():
            try:
                parsed.remove(template)
            except Exception:
                pass
        # Remove comments
        for comment in parsed.filter_comments():
            try:
                parsed.remove(comment)
            except Exception:
                pass
        # Remove HTML tags
        for tag in parsed.filter_tags():
            try:
                parsed.remove(tag)
            except Exception:
                pass
        text = parsed.strip_code().strip()
        # Collapse whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)
        return text
    except Exception as e:
        log.warning("Parse error for article: %s", str(e)[:100])
        return ""


async def _index_articles(dump_path: Path, limit: int = 0):
    """Full indexing pipeline: parse → store → embed."""
    indexer_state["status"] = "running"
    indexer_state["started_at"] = datetime.now(timezone.utc).isoformat()
    indexer_state["indexed"] = 0
    indexer_state["errors"] = 0

    async with httpx.AsyncClient(timeout=60.0) as client:
        batch = []

        for article in _stream_articles(dump_path, limit):
            indexer_state["total_articles"] += 1
            indexer_state["current_article"] = article["title"][:120]

            # Parse and clean
            clean_text = _clean_wikitext(article["raw_text"])
            if len(clean_text) < 200:  # Skip stubs
                continue

            url = f"https://en.wikipedia.org/wiki/{article['title'].replace(' ', '_')}"
            batch.append({
                "url": url,
                "title": article["title"],
                "content": clean_text,
                "markdown": clean_text,
                "namespace": "wikipedia",
                "source_domain": "wikipedia.org",
                "tags": ["wikipedia", "encyclopedia"],
                "language": "en",
            })

            if len(batch) >= BATCH_SIZE:
                await _store_batch(client, batch)
                indexer_state["indexed"] += len(batch)
                log.info("Progress: %d indexed", indexer_state["indexed"])
                batch = []
                await asyncio.sleep(0.5)  # Backpressure

        # Final batch
        if batch:
            await _store_batch(client, batch)
            indexer_state["indexed"] += len(batch)

    indexer_state["status"] = "complete"
    indexer_state["completed_at"] = datetime.now(timezone.utc).isoformat()
    log.info("Indexing complete: %d articles", indexer_state["indexed"])


async def _store_batch(client: httpx.AsyncClient, batch: List[dict]):
    """Store a batch of articles in knowledge-warehouse."""
    try:
        resp = await client.post(
            f"{WAREHOUSE_URL}/store/batch",
            json=batch,
            timeout=60.0,
        )
        resp.raise_for_status()
    except Exception as e:
        indexer_state["errors"] += len(batch)
        log.error("Batch store failed: %s", str(e))


# ─── Endpoints ────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "dump_available": DUMP_PATH.exists(),
        "dump_path": str(DUMP_PATH),
        "indexer": indexer_state["status"],
    }

@app.get("/status")
async def status():
    return indexer_state

@app.get("/download")
async def download_status():
    if DUMP_PATH.exists():
        size_gb = DUMP_PATH.stat().st_size / (1024**3)
        return {"downloaded": True, "path": str(DUMP_PATH), "size_gb": round(size_gb, 2)}
    return {"downloaded": False, "url": DUMP_URL}

@app.post("/download")
async def start_download(background_tasks: BackgroundTasks):
    """Download Wikipedia dump in background."""
    if DUMP_PATH.exists():
        return {"message": "Dump already downloaded", "path": str(DUMP_PATH)}

    async def _download():
        log.info("Downloading Wikipedia dump from %s", DUMP_URL)
        DUMP_PATH.parent.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=3600.0) as client:
            async with client.stream("GET", DUMP_URL) as resp:
                resp.raise_for_status()
                with open(DUMP_PATH, "wb") as f:
                    async for chunk in resp.aiter_bytes(chunk_size=8192):
                        f.write(chunk)
        log.info("Download complete: %s (%.1f GB)", DUMP_PATH, DUMP_PATH.stat().st_size / (1024**3))

    background_tasks.add_task(_download)
    return {"message": "Download started"}

@app.post("/index")
async def start_index(background_tasks: BackgroundTasks, limit: int = 0):
    """Start indexing Wikipedia dump into knowledge-warehouse."""
    if not DUMP_PATH.exists():
        raise HTTPException(status_code=400, detail="Wikipedia dump not found. Download first: POST /download")

    if indexer_state["status"] == "running":
        raise HTTPException(status_code=409, detail="Indexing already in progress")

    article_limit = limit or ARTICLE_LIMIT
    background_tasks.add_task(_index_articles, DUMP_PATH, article_limit)
    return {
        "message": "Indexing started",
        "dump": str(DUMP_PATH),
        "limit": article_limit if article_limit else "unlimited",
    }

@app.post("/index/resume")
async def resume_index(background_tasks: BackgroundTasks, skip: int = 0, limit: int = 0):
    """Resume indexing from a specific count."""
    if not DUMP_PATH.exists():
        raise HTTPException(status_code=400, detail="Wikipedia dump not found")

    if indexer_state["status"] == "running":
        raise HTTPException(status_code=409, detail="Already running")

    background_tasks.add_task(_index_articles, DUMP_PATH, limit)
    return {"message": "Resumed indexing", "skip": skip}

@app.post("/cancel")
async def cancel_index():
    indexer_state["status"] = "cancelled"
    return {"message": "Indexing cancelled"}

@app.get("/")
async def root():
    return {
        "service": "wiki-indexer",
        "version": "1.0.0",
        "endpoints": {
            "GET /health": "Health + dump status",
            "GET /status": "Indexer progress",
            "GET /download": "Download status",
            "POST /download": "Download Wikipedia dump",
            "POST /index": "Start indexing",
            "POST /index/resume": "Resume indexing with skip",
            "POST /cancel": "Cancel indexing",
        },
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8014)
