"""
geo-audit — AI-SEO/GEO content audit service.

Endpoints:
  POST /audit/content     — score content for LLM-citability
  POST /audit/compare     — compare against competitor URLs
  POST /audit/llm-citation — LLM-based citation potential check
  GET  /audit/status      — health + stats
"""

import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from scorer import score_all
from llm_auditor import score_citation_potential, compare_content

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [geo-audit] %(message)s",
)
log = logging.getLogger("geo-audit")

CRAWLER_URL = os.environ.get("CRAWLER_URL", "http://dss-crawler:8000")

app = FastAPI(title="geo-audit", version="1.0.0")

http_client: Optional[httpx.AsyncClient] = None

audit_stats = {
    "content_audits": 0,
    "comparisons": 0,
    "llm_audits": 0,
    "errors": 0,
    "last_audit": None,
}

# ─── Models ───────────────────────────────────────────────

class ContentAuditRequest(BaseModel):
    content: str = Field(..., min_length=10)
    keyword: str = Field(default="", max_length=200)

class ContentAuditResponse(BaseModel):
    composite_score: int
    dimensions: dict
    total_issues: int
    issues: list[str]

class CompareRequest(BaseModel):
    content: str
    keyword: str
    competitor_urls: list[str] = Field(default=[], max_length=5)

class CompareResponse(BaseModel):
    target_score: int
    competitor_scores: list[int]
    gaps: list[str]
    advantages: list[str]

class CitationCheckRequest(BaseModel):
    content: str
    keyword: str

class CitationCheckResponse(BaseModel):
    citation_score: int
    reasoning: str
    strengths: list[str]
    gaps: list[str]

class StatusResponse(BaseModel):
    status: str
    audits: dict

# ─── Lifecycle ────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    global http_client
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0))
    log.info("geo-audit started")

@app.on_event("shutdown")
async def shutdown():
    if http_client:
        await http_client.aclose()

# ─── Endpoints ────────────────────────────────────────────

@app.post("/audit/content", response_model=ContentAuditResponse)
async def audit_content(req: ContentAuditRequest):
    """Run full rule-based audit on content."""
    audit_stats["content_audits"] += 1
    audit_stats["last_audit"] = datetime.now(timezone.utc).isoformat()
    log.info("audit content len=%d kw=%s", len(req.content), req.keyword or "(none)")

    result = score_all(req.content, req.keyword)
    return ContentAuditResponse(**result)


@app.post("/audit/compare", response_model=CompareResponse)
async def audit_compare(req: CompareRequest):
    """Compare content against competitor URLs using LLM."""
    audit_stats["comparisons"] += 1
    audit_stats["last_audit"] = datetime.now(timezone.utc).isoformat()
    log.info("compare kw=%s competitors=%d", req.keyword, len(req.competitor_urls))

    try:
        competitor_contents = []
        for url in req.competitor_urls:
            try:
                resp = await http_client.post(
                    f"{CRAWLER_URL}/crawl",
                    json={"url": url},
                    timeout=30.0,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    text = data.get("content", "") or data.get("markdown", "")
                    competitor_contents.append(text[:3000])
            except Exception as e:
                log.warning("crawl_failed url=%s err=%s", url, str(e))

        result = await compare_content(
            http_client, req.content, competitor_contents, req.keyword
        )
        return CompareResponse(**result)

    except Exception as e:
        audit_stats["errors"] += 1
        log.error("compare_failed: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/audit/llm-citation", response_model=CitationCheckResponse)
async def check_citation_potential(req: CitationCheckRequest):
    """LLM-based citation potential scoring."""
    audit_stats["llm_audits"] += 1
    audit_stats["last_audit"] = datetime.now(timezone.utc).isoformat()
    log.info("llm_audit kw=%s len=%d", req.keyword, len(req.content))

    try:
        result = await score_citation_potential(
            http_client, req.content, req.keyword
        )
        return CitationCheckResponse(**result)
    except Exception as e:
        audit_stats["errors"] += 1
        log.error("llm_audit_failed: %s", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/audit/status")
async def status():
    return StatusResponse(
        status="ok",
        audits={**audit_stats, "uptime": datetime.now(timezone.utc).isoformat()},
    )


@app.get("/health")
async def health():
    deps = {}
    try:
        r = await http_client.get(f"{CRAWLER_URL}/health", timeout=5.0)
        deps["crawler"] = "ok" if r.status_code == 200 else "degraded"
    except Exception:
        deps["crawler"] = "unreachable"
    return {"status": "ok", "dependencies": deps}


# ─── Main ─────────────────────────────────────────────────

def main():
    import uvicorn
    port = int(os.environ.get("GEO_AUDIT_PORT", "8011"))
    uvicorn.run(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
