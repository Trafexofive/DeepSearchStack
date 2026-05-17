"""Knowledge Warehouse — persistent content repository for crawled pages.

Receives content from the crawler service, stores in SQLite with full-text search.
Provides query API for agents to retrieve stored knowledge.
"""
import hashlib
import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

# ─── Config ───────────────────────────────────────────────
DATA_DIR = Path(os.environ.get("WAREHOUSE_DATA_DIR", "/app/data"))
DB_PATH = DATA_DIR / "warehouse.db"
MAX_CONTENT_LENGTH = int(os.environ.get("WAREHOUSE_MAX_CONTENT", "100000"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [warehouse] %(message)s",
)
log = logging.getLogger("warehouse")

app = FastAPI(title="Knowledge Warehouse", version="1.0.0")


# ─── Database ─────────────────────────────────────────────
def _init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS content (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url_hash TEXT UNIQUE NOT NULL,
                url TEXT NOT NULL,
                title TEXT,
                markdown TEXT NOT NULL,
                content TEXT,
                author TEXT,
                published TEXT,
                language TEXT,
                word_count INTEGER DEFAULT 0,
                source_domain TEXT,
                ingested_at REAL NOT NULL,
                tags TEXT DEFAULT '[]'
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_warehouse_domain ON content(source_domain)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_warehouse_ingested ON content(ingested_at)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_warehouse_url_hash ON content(url_hash)")
        # FTS5 for full-text search
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS content_fts USING fts5(
                title, markdown, content, url, author,
                content='content', content_rowid='id'
            )
        """)
        # Triggers to keep FTS in sync
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS content_ai AFTER INSERT ON content BEGIN
                INSERT INTO content_fts(rowid, title, markdown, content, url, author)
                VALUES (new.id, new.title, new.markdown, new.content, new.url, new.author);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS content_ad AFTER DELETE ON content BEGIN
                INSERT INTO content_fts(content_fts, rowid, title, markdown, content, url, author)
                VALUES ('delete', old.id, old.title, old.markdown, old.content, old.url, old.author);
            END
        """)
        conn.commit()

_init_db()


# ─── Models ───────────────────────────────────────────────
class IngestRequest(BaseModel):
    url: str = Field(..., min_length=1, max_length=2048)
    markdown: str = Field(..., min_length=1)
    content: Optional[str] = None
    title: Optional[str] = None
    author: Optional[str] = None
    published: Optional[str] = None
    language: Optional[str] = None
    word_count: int = 0
    source_domain: Optional[str] = None
    tags: list[str] = []


class IngestResponse(BaseModel):
    id: int
    url: str
    ingested: bool
    cached: bool = False


class ContentItem(BaseModel):
    id: int
    url: str
    title: Optional[str]
    markdown: str
    author: Optional[str]
    published: Optional[str]
    language: Optional[str]
    word_count: int
    source_domain: Optional[str]
    ingested_at: str
    tags: list


class SearchResult(BaseModel):
    id: int
    url: str
    title: Optional[str]
    snippet: str
    source_domain: Optional[str]
    ingested_at: str
    word_count: int = 0


class ListResult(BaseModel):
    id: int
    url: str
    title: Optional[str]
    snippet: str
    source_domain: Optional[str]
    ingested_at: str
    word_count: int = 0
    author: Optional[str] = None
    tags: list[str] = []


class StatsResponse(BaseModel):
    total_entries: int
    total_words: int
    domains: list[dict]
    db_size_mb: float


# ─── Endpoints ────────────────────────────────────────────

@app.post("/ingest", response_model=IngestResponse)
async def ingest(req: IngestRequest):
    """Ingest crawled content into the warehouse."""
    url_hash = hashlib.sha256(req.url.encode()).hexdigest()
    domain = req.source_domain or _extract_domain(req.url)
    md = req.markdown[:MAX_CONTENT_LENGTH]
    content = (req.content or "")[:MAX_CONTENT_LENGTH]

    with sqlite3.connect(str(DB_PATH)) as conn:
        existing = conn.execute(
            "SELECT id FROM content WHERE url_hash = ?", (url_hash,)
        ).fetchone()

        if existing:
            conn.execute("""
                UPDATE content SET markdown=?, content=?, title=?, author=?,
                published=?, language=?, word_count=?, ingested_at=?, tags=?
                WHERE url_hash=?
            """, (
                md, content, req.title, req.author, req.published,
                req.language, req.word_count, time.time(),
                json.dumps(req.tags), url_hash,
            ))
            conn.commit()
            log.info("ingest_update url=%s id=%s", req.url[:100], existing[0])
            return IngestResponse(id=existing[0], url=req.url, ingested=True, cached=True)

        cursor = conn.execute("""
            INSERT INTO content (url_hash, url, title, markdown, content, author,
            published, language, word_count, source_domain, ingested_at, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            url_hash, req.url, req.title, md, content, req.author,
            req.published, req.language, req.word_count, domain,
            time.time(), json.dumps(req.tags),
        ))
        conn.commit()
        row_id = cursor.lastrowid
        log.info("ingest_new url=%s id=%s words=%d", req.url[:100], row_id, req.word_count)
        return IngestResponse(id=row_id, url=req.url, ingested=True)


@app.get("/content/{item_id}", response_model=ContentItem)
async def get_content(item_id: int):
    """Retrieve a single content item by ID."""
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM content WHERE id = ?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Content not found")
        return ContentItem(
            id=row["id"], url=row["url"], title=row["title"],
            markdown=row["markdown"], author=row["author"],
            published=row["published"], language=row["language"],
            word_count=row["word_count"], source_domain=row["source_domain"],
            ingested_at=datetime.fromtimestamp(row["ingested_at"], tz=timezone.utc).isoformat(),
            tags=json.loads(row["tags"]),
        )


@app.get("/search", response_model=list[SearchResult])
async def search(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(20, ge=1, le=100),
    domain: Optional[str] = Query(None, description="Filter by domain"),
):
    """Full-text search across stored content."""
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        query = q.replace("'", "''")
        where = ""
        if domain:
            where = f"AND c.source_domain = '{domain.replace(chr(39), chr(39)+chr(39))}'"

        rows = conn.execute(f"""
            SELECT c.id, c.url, c.title, c.source_domain, c.ingested_at, c.word_count,
                   snippet(content_fts, 1, '<b>', '</b>', '...', 40) as snippet
            FROM content_fts
            JOIN content c ON content_fts.rowid = c.id
            WHERE content_fts MATCH ? {where}
            ORDER BY rank
            LIMIT ?
        """, (query, limit)).fetchall()

        return [
            SearchResult(
                id=row["id"], url=row["url"], title=row["title"],
                snippet=row["snippet"], source_domain=row["source_domain"],
                word_count=row["word_count"],
                ingested_at=datetime.fromtimestamp(row["ingested_at"], tz=timezone.utc).isoformat(),
            )
            for row in rows
        ]


@app.get("/list", response_model=list[ListResult])
async def list_entries(
    sort: str = Query("ingested_at", description="Sort field: ingested_at, word_count, title, domain"),
    order: str = Query("desc", description="Sort order: asc or desc"),
    domain: Optional[str] = Query(None, description="Filter by domain"),
    min_words: Optional[int] = Query(None, description="Minimum word count"),
    max_words: Optional[int] = Query(None, description="Maximum word count"),
    offset: int = Query(0, ge=0),
    limit: int = Query(30, ge=1, le=100),
):
    """Paginated list with sort and filter — newest first by default."""
    allowed_sorts = {"ingested_at", "word_count", "title", "source_domain"}
    if sort not in allowed_sorts:
        sort = "ingested_at"
    if sort == "source_domain":
        sort = "source_domain"  # column name matches
    direction = "DESC" if order == "desc" else "ASC"

    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.row_factory = sqlite3.Row
        where = []
        params = []
        if domain:
            where.append("source_domain = ?")
            params.append(domain)
        if min_words is not None:
            where.append("word_count >= ?")
            params.append(min_words)
        if max_words is not None:
            where.append("word_count <= ?")
            params.append(max_words)

        where_clause = f"WHERE {' AND '.join(where)}" if where else ""
        query = f"""
            SELECT id, url, title, source_domain, word_count, author, tags, ingested_at
            FROM content
            {where_clause}
            ORDER BY {sort} {direction}
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])
        rows = conn.execute(query, params).fetchall()

        return [
            {
                "id": row["id"],
                "url": row["url"],
                "title": row["title"],
                "snippet": (row["title"] or "")[:100],
                "source_domain": row["source_domain"],
                "ingested_at": datetime.fromtimestamp(row["ingested_at"], tz=timezone.utc).isoformat(),
                "word_count": row["word_count"],
                "author": row["author"],
                "tags": json.loads(row["tags"]) if row["tags"] else [],
            }
            for row in rows
        ]


@app.get("/stats", response_model=StatsResponse)
async def stats():
    """Warehouse statistics."""
    with sqlite3.connect(str(DB_PATH)) as conn:
        total = conn.execute("SELECT COUNT(*), COALESCE(SUM(word_count), 0) FROM content").fetchone()
        domains = conn.execute(
            "SELECT source_domain, COUNT(*) as cnt FROM content GROUP BY source_domain ORDER BY cnt DESC LIMIT 20"
        ).fetchall()
        db_size = DB_PATH.stat().st_size / (1024 * 1024) if DB_PATH.exists() else 0

    return StatsResponse(
        total_entries=total[0], total_words=total[1],
        domains=[{"domain": d, "count": c} for d, c in domains],
        db_size_mb=round(db_size, 2),
    )


@app.delete("/content/{item_id}")
async def delete_content(item_id: int):
    """Delete a content item."""
    with sqlite3.connect(str(DB_PATH)) as conn:
        conn.execute("DELETE FROM content WHERE id = ?", (item_id,))
        conn.commit()
    return {"deleted": item_id}


@app.get("/health")
async def health():
    with sqlite3.connect(str(DB_PATH)) as conn:
        total = conn.execute("SELECT COUNT(*) FROM content").fetchone()[0]
    return {"status": "healthy", "total_entries": total, "version": "1.0.0"}


@app.get("/")
async def root():
    return {
        "service": "knowledge-warehouse",
        "version": "1.0.0",
        "endpoints": {
            "POST /ingest": "Ingest crawled content",
            "GET /search?q=...": "Full-text search",
            "GET /content/{id}": "Get by ID",
            "DELETE /content/{id}": "Delete by ID",
            "GET /stats": "Warehouse statistics",
            "GET /health": "Health check",
        },
    }


def _extract_domain(url: str) -> str:
    from urllib.parse import urlparse
    return urlparse(url).netloc or "unknown"


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8009)
