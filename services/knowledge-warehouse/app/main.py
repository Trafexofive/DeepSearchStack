"""Knowledge Warehouse — persistent cross-domain content store with full-text search.

Stores: crawled web content, document dumps, extracted knowledge.
Search: PostgreSQL tsvector full-text + optional pgvector semantic search.
"""
import asyncio
import hashlib
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import (
    Column, String, Text, Float, Integer, DateTime, Index,
    create_engine, text as sa_text, select, func, desc, and_, or_,
)
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase, sessionmaker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [warehouse] %(message)s",
)
log = logging.getLogger("warehouse")

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://searchuser:searchpass@dss-postgres:5432/searchdb",
)
SYNC_URL = DATABASE_URL.replace("+asyncpg", "").replace("postgresql+asyncpg://", "postgresql://")

class Base(DeclarativeBase):
    pass

class KnowledgeEntry(Base):
    __tablename__ = "knowledge_entries"
    __table_args__ = (
        Index("idx_kw_namespace", "namespace"),
        Index("idx_kw_domain", "source_domain"),
        Index("idx_kw_crawled", "crawled_at"),
        Index("idx_kw_search", "search_vector", postgresql_using="gin"),
        Index("idx_kw_url_hash", "url_hash", unique=True),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    url_hash = Column(String(64), unique=True, nullable=False)
    url = Column(Text, nullable=False)
    title = Column(Text)
    content = Column(Text)
    markdown = Column(Text)
    author = Column(Text)
    published = Column(DateTime(timezone=True))
    language = Column(String(10))
    word_count = Column(Integer, default=0)
    source_domain = Column(Text)
    namespace = Column(String(50), default="web")
    tags = Column(Text)  # JSON array string
    entities = Column(Text)  # JSON extracted entities
    search_vector = Column(Text)  # tsvector stored as text for simplicity
    crawled_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

engine = create_async_engine(DATABASE_URL, echo=False, pool_size=10)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# ─── Full-text search helpers ─────────────────────────────
_clean_re = re.compile(r'[^\w\s]')

def _tsvector(text: str) -> str:
    """Build a simple tsvector string for full-text search."""
    cleaned = _clean_re.sub(' ', text).lower()
    words = cleaned.split()
    # Weight title words higher, content words lower
    return ' '.join(f"{w}:A" for w in words[:50]) + ' ' + ' '.join(f"{w}:D" for w in words[50:500])

async def _ensure_tsvector():
    """Ensure pg_trgm extension and tsvector index exist."""
    async with engine.begin() as conn:
        await conn.execute(sa_text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        await conn.execute(sa_text("""
            CREATE INDEX IF NOT EXISTS idx_kw_trgm_title
            ON knowledge_entries USING gin (title gin_trgm_ops)
        """))
    log.info("pg_trgm extension + indexes ensured")


# ─── Models ───────────────────────────────────────────────
class StoreRequest(BaseModel):
    url: str = Field(..., min_length=1)
    title: Optional[str] = None
    content: Optional[str] = None
    markdown: Optional[str] = None
    author: Optional[str] = None
    published: Optional[str] = None
    language: Optional[str] = None
    namespace: str = "web"
    tags: List[str] = []
    source_domain: Optional[str] = None

class StoreResponse(BaseModel):
    id: int
    url_hash: str
    stored: bool
    existing: bool

class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    namespace: Optional[str] = None
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = 0

class SearchResult(BaseModel):
    id: int
    url: str
    title: Optional[str]
    excerpt: Optional[str]
    source_domain: Optional[str]
    namespace: str
    published: Optional[str]
    crawled_at: Optional[str]
    word_count: int

class SearchResponse(BaseModel):
    results: List[SearchResult]
    total: int
    query: str

class WarehouseStats(BaseModel):
    total_entries: int
    namespaces: dict
    domains: List[dict]
    total_words: int
    oldest_entry: Optional[str]
    newest_entry: Optional[str]


# ─── App ──────────────────────────────────────────────────
app = FastAPI(title="Knowledge Warehouse", version="1.0.0")

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await _ensure_tsvector()
    log.info("Knowledge Warehouse ready")
    yield
    await engine.dispose()

app.router.lifespan_context = lifespan


# ─── Endpoints ────────────────────────────────────────────

@app.post("/store", response_model=StoreResponse)
async def store(req: StoreRequest):
    """Store a knowledge entry. Deduplicates by URL hash."""
    url_hash = hashlib.sha256(req.url.encode()).hexdigest()

    async with async_session() as session:
        existing = await session.execute(
            select(KnowledgeEntry).where(KnowledgeEntry.url_hash == url_hash)
        )
        if existing.scalar_one_or_none():
            return StoreResponse(id=0, url_hash=url_hash, stored=False, existing=True)

        domain = req.source_domain
        if not domain:
            from urllib.parse import urlparse
            domain = urlparse(req.url).netloc

        published_dt = None
        if req.published:
            try:
                from dateutil import parser as dtparser
                published_dt = dtparser.parse(req.published)
            except Exception:
                pass

        search_text = f"{req.title or ''} {req.content or ''}"

        entry = KnowledgeEntry(
            url_hash=url_hash,
            url=req.url,
            title=req.title,
            content=req.content,
            markdown=req.markdown,
            author=req.author,
            published=published_dt,
            language=req.language,
            word_count=len((req.content or "").split()),
            source_domain=domain,
            namespace=req.namespace,
            tags=",".join(req.tags) if req.tags else None,
            search_vector=_tsvector(search_text),
        )
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
        log.info("stored url=%s ns=%s hash=%s", req.url[:120], req.namespace, url_hash[:12])
        return StoreResponse(id=entry.id, url_hash=url_hash, stored=True, existing=False)

@app.post("/store/batch")
async def store_batch(reqs: List[StoreRequest]):
    """Store multiple entries in batch."""
    stored = 0
    skipped = 0
    for r in reqs:
        resp = await store(r)
        if resp.stored:
            stored += 1
        else:
            skipped += 1
    return {"stored": stored, "skipped": skipped, "total": len(reqs)}

@app.post("/search", response_model=SearchResponse)
async def search(req: SearchRequest):
    """Full-text search across knowledge entries."""
    query_clean = _clean_re.sub(' ', req.query).lower().strip()
    terms = query_clean.split()

    async with async_session() as session:
        q = select(KnowledgeEntry)

        if req.namespace:
            q = q.where(KnowledgeEntry.namespace == req.namespace)

        # Simple full-text: match any term in title or content
        conditions = []
        for term in terms:
            conditions.append(KnowledgeEntry.title.ilike(f"%{term}%"))
            conditions.append(KnowledgeEntry.content.ilike(f"%{term}%"))
        if conditions:
            q = q.where(or_(*conditions))

        # Count
        count_q = select(func.count()).select_from(q.subquery())
        total = (await session.execute(count_q)).scalar() or 0

        # Fetch
        q = q.order_by(desc(KnowledgeEntry.crawled_at)).offset(req.offset).limit(req.limit)
        rows = (await session.execute(q)).scalars().all()

        results = []
        for row in rows:
            excerpt = (row.content or row.markdown or "")[:300]
            # Find snippet around first matching term
            for term in terms:
                idx = excerpt.lower().find(term.lower())
                if idx >= 0:
                    start = max(0, idx - 60)
                    excerpt = ("…" if start > 0 else "") + excerpt[start:start + 200] + "…"
                    break

            results.append(SearchResult(
                id=row.id,
                url=row.url,
                title=row.title,
                excerpt=excerpt,
                source_domain=row.source_domain,
                namespace=row.namespace,
                published=row.published.isoformat() if row.published else None,
                crawled_at=row.crawled_at.isoformat() if row.crawled_at else None,
                word_count=row.word_count or 0,
            ))

        return SearchResponse(results=results, total=total, query=req.query)

@app.get("/entry/{entry_id}")
async def get_entry(entry_id: int):
    """Get full content of a single entry."""
    async with async_session() as session:
        row = await session.get(KnowledgeEntry, entry_id)
        if not row:
            raise HTTPException(status_code=404, detail="Entry not found")
        return {
            "id": row.id,
            "url": row.url,
            "title": row.title,
            "content": row.content,
            "markdown": row.markdown,
            "author": row.author,
            "published": row.published.isoformat() if row.published else None,
            "language": row.language,
            "word_count": row.word_count,
            "source_domain": row.source_domain,
            "namespace": row.namespace,
            "tags": row.tags.split(",") if row.tags else [],
            "crawled_at": row.crawled_at.isoformat() if row.crawled_at else None,
        }

@app.get("/entry/by-url")
async def get_entry_by_url(url: str = Query(..., min_length=1)):
    """Look up entry by URL."""
    url_hash = hashlib.sha256(url.encode()).hexdigest()
    async with async_session() as session:
        row = (await session.execute(
            select(KnowledgeEntry).where(KnowledgeEntry.url_hash == url_hash)
        )).scalar_one_or_none()
        if not row:
            raise HTTPException(status_code=404, detail="Entry not found")
        return await get_entry(row.id)

@app.delete("/entry/{entry_id}")
async def delete_entry(entry_id: int):
    async with async_session() as session:
        row = await session.get(KnowledgeEntry, entry_id)
        if not row:
            raise HTTPException(status_code=404)
        await session.delete(row)
        await session.commit()
    return {"deleted": True}

@app.get("/stats", response_model=WarehouseStats)
async def stats():
    async with async_session() as session:
        total = (await session.execute(select(func.count()).select_from(KnowledgeEntry))).scalar() or 0
        total_words = (await session.execute(select(func.sum(KnowledgeEntry.word_count)))).scalar() or 0

        # Namespace counts
        ns_rows = (await session.execute(
            select(KnowledgeEntry.namespace, func.count())
            .group_by(KnowledgeEntry.namespace)
        )).all()
        namespaces = {ns: cnt for ns, cnt in ns_rows}

        # Top domains
        domain_rows = (await session.execute(
            select(KnowledgeEntry.source_domain, func.count())
            .group_by(KnowledgeEntry.source_domain)
            .order_by(desc(func.count()))
            .limit(20)
        )).all()
        domains = [{"domain": d, "count": c} for d, c in domain_rows]

        oldest = (await session.execute(
            select(KnowledgeEntry.crawled_at).order_by(KnowledgeEntry.crawled_at).limit(1)
        )).scalar()
        newest = (await session.execute(
            select(KnowledgeEntry.crawled_at).order_by(desc(KnowledgeEntry.crawled_at)).limit(1)
        )).scalar()

        return WarehouseStats(
            total_entries=total,
            namespaces=namespaces,
            domains=domains,
            total_words=total_words,
            oldest_entry=oldest.isoformat() if oldest else None,
            newest_entry=newest.isoformat() if newest else None,
        )

@app.get("/health")
async def health():
    try:
        async with async_session() as session:
            await session.execute(sa_text("SELECT 1"))
        return {"status": "ok", "service": "knowledge-warehouse"}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}

@app.get("/")
async def root():
    return {
        "service": "knowledge-warehouse",
        "version": "1.0.0",
        "endpoints": {
            "POST /store": "Store a knowledge entry (deduplicated by URL)",
            "POST /store/batch": "Batch store entries",
            "POST /search": "Full-text search",
            "GET /entry/{id}": "Get full entry content",
            "GET /entry/by-url": "Look up by URL",
            "DELETE /entry/{id}": "Delete entry",
            "GET /stats": "Warehouse statistics",
            "GET /health": "Health check",
        },
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8009)
