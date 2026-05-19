"""trends-aggregator — Multi-engine trend aggregator for indie hacker market research.

Data sources:
  SearXNG (:8080, via DSS) → Google Trends, web search volume
  Crawler (:8000, via DSS)  → GitHub Trending, ProductHunt, HackerNews, Exploding Topics
  yt-lab (:8020)            → YouTube viral analysis
  trend-engine (:8021)      → YouTube viral scoring
  warehouse (:8009)         → Historical trend data storage
  inference_gateway (:8005) → LLM market analysis + opportunity scoring

Endpoints:
  POST /trends/search        — Multi-source trend search for a topic
  POST /trends/compare       — Compare topics across all sources
  GET  /trends/rising        — Rising topics detected across sources
  GET  /trends/opportunities — LLM-scored indie-hacker opportunities
  POST /trends/report        — Full market research report for a topic/subniche
  GET  /sources              — Source health + status
  GET  /health               — Health check
"""

import asyncio
import hashlib
import json
import logging
import math
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [trends-agg] %(message)s",
)
log = logging.getLogger("trends-agg")

# ─── Config ───────────────────────────────────────────────────

SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://searxng:8080")
CRAWLER_URL = os.environ.get("CRAWLER_URL", "http://crawler:8000")
YT_LAB_URL = os.environ.get("YT_LAB_URL", "http://localhost:8020")
TREND_ENGINE_URL = os.environ.get("TREND_ENGINE_URL", "http://localhost:8021")
WAREHOUSE_URL = os.environ.get("WAREHOUSE_URL", "http://knowledge-warehouse:8009")
INFERENCE_URL = os.environ.get("INFERENCE_URL", "http://inference_gateway:8005/v1/chat/completions")
DATA_DIR = Path(os.environ.get("TRENDS_AGG_DATA", "/app/data"))

app = FastAPI(title="trends-aggregator", version="1.0.0")

# ─── Models ───────────────────────────────────────────────────

class TrendSearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Topic to research")
    sources: list[str] = Field(
        default=["web", "github", "youtube"],
        description="Sources to query: web, github, youtube, producthunt, hackernews"
    )
    max_results_per_source: int = Field(default=8, ge=1, le=30)
    generate_report: bool = Field(default=False, description="Generate LLM market report")

class SourceResult(BaseModel):
    source: str
    title: str
    url: str
    snippet: str
    score: float = 0.0          # Relevance/trend score 0–100
    metadata: dict = {}

class TrendSearchResponse(BaseModel):
    query: str
    sources_queried: list[str]
    total_results: int
    results: list[SourceResult]
    trend_signal: dict             # Aggregated trend metrics
    market_report: Optional[str] = None
    duration_ms: int

class CompareRequest(BaseModel):
    topics: list[str] = Field(..., min_length=2, max_length=5)
    sources: list[str] = Field(default=["web", "github", "youtube"])

class CompareResponse(BaseModel):
    topics: list[dict]             # Each with per-source breakdown
    winner: str                    # Highest trending topic
    comparative_analysis: str      # LLM comparison

class OpportunityScore(BaseModel):
    topic: str
    demand_score: float            # Search volume / interest 0–100
    competition_score: float       # How crowded? (lower = better) 0–100
    growth_score: float            # Trajectory 0–100
    monetization_score: float      # Can you build a business? 0–100
    composite_score: float         # Weighted composite
    sources: list[str]
    summary: str

class ReportRequest(BaseModel):
    topic: str
    depth: str = Field(default="standard", description="quick, standard, or deep")

class ReportResponse(BaseModel):
    topic: str
    generated_at: str
    sections: list[dict]           # Section title + content
    sources_cited: list[str]
    execution_time_ms: int


# ─── Source Queries ──────────────────────────────────────────

async def _query_searxng(query: str, limit: int = 10) -> list[dict]:
    """Search via SearXNG (multi-engine: Google, DDG, Bing, etc.)."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{SEARXNG_URL}/search",
                params={"q": query, "format": "json", "language": "en", "limit": limit},
                headers={"X-Real-IP": "127.0.0.1"},
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("results", [])
    except Exception as e:
        log.warning(f"searxng_error: {e}")
        return []


async def _query_github_trending(language: str = "") -> list[dict]:
    """Scrape GitHub Trending page via crawler."""
    url = f"https://github.com/trending/{language}?since=daily" if language else "https://github.com/trending?since=weekly"
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{CRAWLER_URL}/crawl",
                json={"url": url, "formats": ["markdown"]},
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            if not data.get("success"):
                return []
            md = data.get("markdown", "")
            # Parse trending repos from markdown
            repos = []
            # Pattern: repository names in GitHub trending page
            entries = re.findall(
                r'(?:(\S+)\s*/\s*(\S+))\s*\n.*?\n.*?(\d+,?\d*)\s+stars.*?(?:today|this week)',
                md, re.MULTILINE
            )
            # Fallback: look for repo URL patterns
            repo_urls = re.findall(r'github\.com/([\w.-]+/[\w.-]+)', md)
            seen = set()
            for full_name in repo_urls:
                if full_name in seen or "/" not in full_name:
                    continue
                seen.add(full_name)
                owner, name = full_name.split("/", 1)
                # Skip GitHub feature pages
                if owner in ("features", "security", "enterprise", "solutions", "pricing", "marketplace"):
                    continue
                repos.append({
                    "title": full_name,
                    "url": f"https://github.com/{full_name}",
                    "snippet": f"Trending on GitHub",
                    "source": "github",
                    "stars_today": 0,
                })
            return repos[:15]
    except Exception as e:
        log.warning(f"github_trending_error: {e}")
        return []


async def _query_youtube_trends(query: str, limit: int = 5) -> list[dict]:
    """Get YouTube trend data via yt-lab + trend-engine."""
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            # Search warehouse for YouTube content matching query
            resp = await client.get(
                f"{WAREHOUSE_URL}/search",
                params={"q": f"{query} youtube", "limit": limit},
            )
            if resp.status_code != 200:
                return []
            results = resp.json()
            if isinstance(results, dict):
                results = results.get("results", [])

            enriched = []
            for r in results[:limit]:
                url = r.get("url", "")
                if "youtube.com" not in url and "youtu.be" not in url:
                    continue
                # Get viral score from trend-engine
                try:
                    tr = await client.post(
                        f"{TREND_ENGINE_URL}/trends/analyze",
                        json={"video_url": url},
                    )
                    if tr.status_code == 200:
                        td = tr.json()
                        enriched.append({
                            "title": td.get("title", r.get("title", "")),
                            "url": url,
                            "snippet": f"Views: {td.get('views',0):,} | Score: {td.get('viral_score',0)}/100",
                            "source": "youtube",
                            "viral_score": td.get("viral_score", 0),
                            "views": td.get("views", 0),
                        })
                        continue
                except Exception:
                    pass
                enriched.append({
                    "title": r.get("title", ""),
                    "url": url,
                    "snippet": r.get("snippet", "")[:200],
                    "source": "youtube",
                    "viral_score": 0,
                    "views": 0,
                })
            return enriched
    except Exception as e:
        log.warning(f"youtube_trends_error: {e}")
        return []


async def _query_hackernews() -> list[dict]:
    """Get trending HackerNews posts (Show HN, top stories)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                "https://hacker-news.firebaseio.com/v0/topstories.json"
            )
            resp.raise_for_status()
            ids = resp.json()[:10]  # top 10

            results = []
            for item_id in ids[:8]:
                try:
                    item_resp = await client.get(
                        f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
                    )
                    item = item_resp.json()
                    if item and item.get("title"):
                        results.append({
                            "title": item["title"],
                            "url": item.get("url", f"https://news.ycombinator.com/item?id={item_id}"),
                            "snippet": f"Score: {item.get('score',0)} | Comments: {item.get('descendants',0)}",
                            "source": "hackernews",
                            "score": item.get("score", 0),
                        })
                except Exception:
                    continue
            return results
    except Exception as e:
        log.warning(f"hackernews_error: {e}")
        return []


# ─── Trend Scoring ───────────────────────────────────────────

def _compute_trend_signal(results: list[SourceResult]) -> dict:
    """Aggregate results into a trend signal."""
    if not results:
        return {"strength": "none", "volume": 0, "velocity": 0, "source_diversity": 0}

    sources_represented = len(set(r.source for r in results))
    total_volume = len(results)

    # Score based on result count + source diversity
    volume_score = min(total_volume * 5, 100)
    diversity_score = sources_represented * 25

    # Average relevance score
    avg_score = sum(r.score for r in results) / len(results) if results else 0

    composite = (volume_score * 0.3 + diversity_score * 0.3 + avg_score * 0.4)

    if composite >= 70:
        strength = "strong"
    elif composite >= 40:
        strength = "moderate"
    elif composite >= 15:
        strength = "weak"
    else:
        strength = "none"

    return {
        "strength": strength,
        "volume": total_volume,
        "velocity": round(composite, 1),
        "source_diversity": sources_represented,
        "avg_relevance": round(avg_score, 1),
    }


# ─── LLM Helpers ─────────────────────────────────────────────

async def _llm(prompt: str, system: str, max_tokens: int = 1024) -> str:
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
                "temperature": 0.3,
            })
            resp.raise_for_status()
            data = resp.json()
            return data.get("content", "") or data["choices"][0]["message"]["content"]
    except Exception as e:
        log.warning(f"llm_error: {e}")
        return ""


# ─── Endpoints ───────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "trends-aggregator",
        "sources": {
            "searxng": SEARXNG_URL,
            "crawler": CRAWLER_URL,
            "warehouse": WAREHOUSE_URL,
        },
    }


@app.get("/sources")
async def source_status():
    """Check health of all data sources."""
    results = {}
    # SearXNG
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{SEARXNG_URL}/health", headers={"X-Real-IP": "127.0.0.1"})
            results["searxng"] = "ok" if r.status_code < 500 else "degraded"
    except Exception:
        results["searxng"] = "unreachable"

    # Crawler
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{CRAWLER_URL}/health")
            results["crawler"] = "ok" if r.status_code < 500 else "degraded"
    except Exception:
        results["crawler"] = "unreachable"

    # YT-Lab
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{YT_LAB_URL}/health")
            results["yt_lab"] = "ok" if r.status_code < 500 else "degraded"
    except Exception:
        results["yt_lab"] = "unreachable"

    # Trend Engine
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{TREND_ENGINE_URL}/health")
            results["trend_engine"] = "ok" if r.status_code < 500 else "degraded"
    except Exception:
        results["trend_engine"] = "unreachable"

    # HackerNews
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get("https://hacker-news.firebaseio.com/v0/maxitem.json")
            results["hackernews"] = "ok" if r.status_code < 500 else "degraded"
    except Exception:
        results["hackernews"] = "unreachable"

    return results


@app.post("/trends/search", response_model=TrendSearchResponse)
async def search_trends(req: TrendSearchRequest):
    """Multi-source trend search for a topic."""
    t0 = time.time()
    sources_used = []
    all_results: list[SourceResult] = []

    async def score_and_add(source_name: str, items: list[dict], base_score: float = 50):
        for item in items:
            all_results.append(SourceResult(
                source=source_name,
                title=item.get("title", ""),
                url=item.get("url", ""),
                snippet=item.get("snippet", "")[:300],
                score=base_score + item.get("score", item.get("viral_score", 0)) * 0.5,
                metadata={k: v for k, v in item.items() if k not in ("title", "url", "snippet", "score")},
            ))

    # Query each requested source concurrently
    tasks = []

    if "web" in req.sources:
        sources_used.append("web")
        tasks.append(("web", _query_searxng(req.query, req.max_results_per_source)))

    if "github" in req.sources:
        sources_used.append("github")
        tasks.append(("github", _query_github_trending()))

    if "youtube" in req.sources:
        sources_used.append("youtube")
        tasks.append(("youtube", _query_youtube_trends(req.query, req.max_results_per_source)))

    if "hackernews" in req.sources:
        sources_used.append("hackernews")
        tasks.append(("hackernews", _query_hackernews()))

    # Run all source queries concurrently
    gathered = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)

    for (source_name, _), result in zip(tasks, gathered):
        if isinstance(result, Exception):
            log.warning(f"source_{source_name}_error: {result}")
            continue
        if result:
            score_and_add(source_name, result)

    # Compute trend signal
    signal = _compute_trend_signal(all_results)

    # Generate market report if requested
    report = None
    if req.generate_report and all_results:
        context = "\n".join(
            f"[{r.source}] {r.title}: {r.snippet[:150]}"
            for r in all_results[:15]
        )
        prompt = (
            f"Analyze the market trend for '{req.query}' based on this data. "
            f"Is this a growing trend? Would it make a good indie hacker business opportunity? "
            f"Give a 2-3 paragraph assessment with specific insights.\n\nData:\n{context}"
        )
        report = await _llm(
            prompt,
            system="You are a market research analyst specializing in indie hacker opportunities. Be specific and data-driven.",
            max_tokens=600,
        )

    duration = int((time.time() - t0) * 1000)

    # Persist for historical tracking
    _save_search(req.query, signal, duration)

    return TrendSearchResponse(
        query=req.query,
        sources_queried=sources_used,
        total_results=len(all_results),
        results=all_results[:25],
        trend_signal=signal,
        market_report=report.strip() if report else None,
        duration_ms=duration,
    )


@app.post("/trends/compare", response_model=CompareResponse)
async def compare_topics(req: CompareRequest):
    """Compare multiple topics across all sources."""
    topic_data = []

    for topic in req.topics:
        search = await search_trends(TrendSearchRequest(
            query=topic,
            sources=req.sources,
            max_results_per_source=6,
            generate_report=False,
        ))
        topic_data.append({
            "topic": topic,
            "total_results": search.total_results,
            "trend_signal": search.trend_signal,
            "top_sources": [r.source for r in search.results[:5]],
        })

    # Sort by trend velocity descending
    topic_data.sort(key=lambda t: t["trend_signal"]["velocity"], reverse=True)
    winner = topic_data[0]["topic"]

    # LLM comparative analysis
    comparison_context = "\n".join(
        f"- {t['topic']}: {t['total_results']} results, velocity={t['trend_signal']['velocity']}, "
        f"sources={t['trend_signal']['source_diversity']}"
        for t in topic_data
    )
    prompt = (
        f"Compare these topics for indie hacker market opportunity. "
        f"Which is the best to build a business around and why? "
        f"Give a 2-3 paragraph analysis.\n\n{comparison_context}"
    )
    analysis = await _llm(
        prompt,
        system="You analyze market opportunities for indie hackers. Be specific about which business models would work.",
        max_tokens=500,
    )

    return CompareResponse(
        topics=topic_data,
        winner=winner,
        comparative_analysis=analysis.strip(),
    )


@app.get("/trends/rising")
async def rising_trends(limit: int = Query(default=15, ge=5, le=50)):
    """Discover rising topics by scanning multiple sources for breakout signals."""
    t0 = time.time()

    # Query multiple discovery sources concurrently
    web_future = _query_searxng("trending topics 2026 new rising trends", limit=15)
    github_future = _query_github_trending()
    hn_future = _query_hackernews()

    web_results, github_results, hn_results = await asyncio.gather(
        web_future, github_future, hn_future, return_exceptions=True
    )

    all_topics = []

    # Web results
    if not isinstance(web_results, Exception):
        for r in web_results:
            all_topics.append({
                "topic": r.get("title", ""),
                "source": "web",
                "url": r.get("url", ""),
                "snippet": r.get("content", r.get("snippet", ""))[:200],
            })

    # GitHub trending repos → extract topics
    if not isinstance(github_results, Exception):
        for r in github_results:
            all_topics.append({
                "topic": r.get("title", ""),
                "source": "github",
                "url": r.get("url", ""),
                "snippet": r.get("snippet", ""),
            })

    # HackerNews
    if not isinstance(hn_results, Exception):
        for r in hn_results:
            all_topics.append({
                "topic": r.get("title", ""),
                "source": "hackernews",
                "url": r.get("url", ""),
                "snippet": r.get("snippet", ""),
            })

    # Deduplicate by title similarity (simple)
    seen = set()
    unique = []
    for t in all_topics:
        key = t["topic"].lower()[:50]
        if key not in seen:
            seen.add(key)
            unique.append(t)

    return {
        "rising_topics": unique[:limit],
        "total_found": len(all_topics),
        "unique": len(unique),
        "sources": ["web", "github", "hackernews"],
        "duration_ms": int((time.time() - t0) * 1000),
    }


@app.get("/trends/opportunities")
async def indie_opportunities(limit: int = Query(default=10, ge=3, le=30)):
    """LLM-scored indie hacker opportunities from current trending data."""
    # Gather raw data from all sources
    web = await _query_searxng("rising startup trends indie hacker saas 2026", limit=10)
    github = await _query_github_trending()
    hn = await _query_hackernews()

    # Build context for LLM
    source_context = []
    for r in web[:8]:
        source_context.append(f"[web] {r.get('title','')}")
    for r in github[:8]:
        source_context.append(f"[github] {r.get('title','')}")
    for r in hn[:5]:
        source_context.append(f"[hackernews] {r.get('title','')} (score: {r.get('score',0)})")

    context = "\n".join(source_context[:20])

    prompt = (
        f"Based on these current trending topics, identify the top {limit} indie hacker business opportunities. "
        f"For each opportunity, provide: topic name, a demand score (0-100), competition score (0-100 where lower means less competitive), "
        f"growth score (0-100), monetization score (0-100), a composite score, and a one-sentence summary. "
        f"Return as JSON array.\n\nTrending now:\n{context}"
    )

    try:
        raw = await _llm(
            prompt,
            system="You identify indie hacker market opportunities. Return ONLY valid JSON array. No markdown, no preamble.",
            max_tokens=2000,
        )
        # Parse JSON from response
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
        opportunities = json.loads(cleaned)
    except Exception as e:
        log.warning(f"opportunity_llm_parse_error: {e}")
        opportunities = []

    # Score and sort
    scored = []
    for opp in (opportunities if isinstance(opportunities, list) else []):
        try:
            composite = (
                opp.get("demand_score", 50) * 0.35
                + (100 - opp.get("competition_score", 50)) * 0.25
                + opp.get("growth_score", 50) * 0.25
                + opp.get("monetization_score", 50) * 0.15
            )
            scored.append(OpportunityScore(
                topic=opp.get("topic", "Unknown"),
                demand_score=float(opp.get("demand_score", 50)),
                competition_score=float(opp.get("competition_score", 50)),
                growth_score=float(opp.get("growth_score", 50)),
                monetization_score=float(opp.get("monetization_score", 50)),
                composite_score=round(composite, 1),
                sources=["web", "github", "hackernews"],
                summary=opp.get("summary", opp.get("description", "")),
            ))
        except Exception:
            continue

    scored.sort(key=lambda s: s.composite_score, reverse=True)

    return {
        "opportunities": scored[:limit],
        "total_scored": len(scored),
        "source_data_points": len(source_context),
        "methodology": "LLM-scored multi-source aggregation (web + GitHub + HN)",
    }


@app.post("/trends/report", response_model=ReportResponse)
async def generate_report(req: ReportRequest):
    """Generate a comprehensive market research report for a topic."""
    t0 = time.time()

    # Gather data from all sources
    web = await _query_searxng(f"{req.topic} market size trends growth 2026", limit=10)
    github = await _query_github_trending()
    yt = await _query_youtube_trends(req.topic, limit=5)

    # Build source context
    sources_cited = []
    context_parts = []

    for r in web[:8]:
        sources_cited.append(r.get("url", ""))
        context_parts.append(f"- {r.get('title','')}: {r.get('content', r.get('snippet',''))[:200]}")

    for r in github[:5]:
        if req.topic.lower() in r.get("title", "").lower():
            sources_cited.append(r.get("url", ""))
            context_parts.append(f"- GitHub: {r.get('title','')}")

    for r in yt[:3]:
        sources_cited.append(r.get("url", ""))
        context_parts.append(f"- YouTube: {r.get('title','')} ({r.get('snippet','')})")

    context = "\n".join(context_parts[:20])

    # Generate report sections
    sections = []

    # Section 1: Market Overview
    overview = await _llm(
        f"Write a 2-paragraph market overview for '{req.topic}'. Cover: what is it, current state, key players.\n\nContext:\n{context}",
        system="You write market research reports. Be factual and specific.",
        max_tokens=500,
    )
    sections.append({"title": "Market Overview", "content": overview.strip()})

    # Section 2: Trend Analysis
    trends = await _llm(
        f"Analyze trends for '{req.topic}'. Is demand growing or shrinking? What are the key drivers? What's the 12-month outlook?\n\nContext:\n{context}",
        system="You analyze market trends. Be data-driven.",
        max_tokens=500,
    )
    sections.append({"title": "Trend Analysis", "content": trends.strip()})

    # Section 3: Indie Hacker Opportunity
    opportunity = await _llm(
        f"Assess '{req.topic}' as an indie hacker business opportunity. Can a solo founder build a profitable business here? What business models would work? What's the revenue potential? What are the risks?\n\nContext:\n{context}",
        system="You evaluate business opportunities for indie hackers. Be brutally honest about viability.",
        max_tokens=500,
    )
    sections.append({"title": "Indie Hacker Opportunity Assessment", "content": opportunity.strip()})

    return ReportResponse(
        topic=req.topic,
        generated_at=datetime.now(timezone.utc).isoformat(),
        sections=sections,
        sources_cited=list(set(sources_cited))[:15],
        execution_time_ms=int((time.time() - t0) * 1000),
    )


# ─── Persistence ─────────────────────────────────────────────

def _save_search(query: str, signal: dict, duration_ms: int):
    """Persist search for historical tracking."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    entry = {
        "timestamp": ts,
        "query": query,
        "signal": signal,
        "duration_ms": duration_ms,
    }
    path = DATA_DIR / f"search-{ts}-{hashlib.md5(query.encode()).hexdigest()[:8]}.json"
    path.write_text(json.dumps(entry, indent=2))


@app.on_event("startup")
async def startup():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    log.info("trends_aggregator_started")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8022)
