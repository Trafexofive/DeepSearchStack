#!/usr/bin/env python3
"""
DeepSearchStack Research Agent — end-to-end research pipeline.

Usage:
  python3 scripts/dss-research-agent.py "topic to research" [options]

Workflow:
  1. Multi-source search across search gateways
  2. Crawl top URLs for full text content
  3. Ingest into knowledge warehouse
  4. Vector-embed for RAG retrieval
  5. LLM-based cross-domain reconciliation
  6. Output structured research report

Environment:
  DSS_WEB_API, DSS_CRAWLER, DSS_WAREHOUSE — override service URLs
"""

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sdk.client import DSSClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
)
log = logging.getLogger("dss.research")


class ResearchAgent:
    """End-to-end research agent using the full DSS pipeline."""

    def __init__(self, topic: str, max_sources: int = 5, max_scrape: int = 3):
        self.topic = topic
        self.max_sources = max_sources
        self.max_scrape = max_scrape
        self.start_time = time.monotonic()
        self.dss = DSSClient(
            web_api_url=os.environ.get("DSS_WEB_API", "http://localhost:8083/dss/api"),
            crawler_url=os.environ.get("DSS_CRAWLER", "http://localhost:8083/dss/crawl"),
            warehouse_url=os.environ.get("DSS_WAREHOUSE", "http://localhost:8083/dss/warehouse"),
            vector_store_url=os.environ.get("DSS_VECTOR_STORE", "http://localhost:8083/dss/vectors"),
            search_agent_url=os.environ.get("DSS_SEARCH_AGENT", "http://localhost:8083/dss/agent"),
            search_gateway_url=os.environ.get("DSS_SEARCH_GATEWAY", "http://localhost:8083/dss/gateway"),
            deepsearch_url=os.environ.get("DSS_DEEPSEARCH", "http://localhost:8083/dss/search"),
            timeout=180.0,
        )
        self.results = {
            "topic": topic,
            "timestamp": datetime.now().isoformat(),
            "sources": [],
            "warehouse_entries": 0,
            "crawled_urls": [],
            "consensus_facts": [],
            "synthesis": "",
            "execution_ms": 0,
            "phases": {},
        }

    def _phase(self, name: str):
        self._phase_start = time.monotonic()
        self._phase_name = name
        log.info("═══ PHASE: %s ═══", name)

    def _phase_end(self):
        elapsed = int((time.monotonic() - self._phase_start) * 1000)
        self.results["phases"][self._phase_name] = elapsed
        log.info("  ✓ %s — %dms", self._phase_name, elapsed)

    async def run(self) -> dict:
        """Execute the full research pipeline."""
        await self.dss.connect()
        try:
            # Phase 1: Aggregate search with LLM reconciliation
            self._phase("Search + Reconcile")
            agg = await self.dss.aggregate(
                query=self.topic,
                max_results=self.max_sources,
                reconcile=True,
                include_warehouse=True,
                enable_scraping=False,
                enable_rag=False,
            )
            self._phase_end()

            self.results["sources"] = [
                {"title": s.title, "url": s.url, "domain": s.domain, "source": s.source}
                for s in agg.sources
            ]

            if agg.consensus:
                self.results["consensus_facts"] = [
                    {"claim": f.claim, "confidence": f.confidence,
                     "sources": f.supporting_sources}
                    for f in agg.consensus
                ]

            self.results["synthesis"] = agg.synthesis or ""

            log.info("Found %d sources, %d consensus facts",
                     agg.total_sources, len(agg.consensus or []))

            # Phase 2: Crawl top URLs for full content
            self._phase("Crawl top sources")
            urls_to_crawl = [s.url for s in agg.sources[:self.max_scrape] if s.url]
            for url in urls_to_crawl:
                try:
                    log.info("Crawling: %s", url)
                    crawl_result = await self.dss.crawl(url, timeout=30)
                    self.results["crawled_urls"].append({
                        "url": url,
                        "status": "ok",
                        "content_length": len(crawl_result.get("content", "")),
                    })
                except Exception as e:
                    log.warning("Crawl failed for %s: %s", url, e)
                    self.results["crawled_urls"].append({
                        "url": url, "status": f"failed: {e}"
                    })
            self._phase_end()

            # Phase 3: Ingest into warehouse
            self._phase("Ingest to warehouse")
            if urls_to_crawl:
                ingest = await self.dss.ingest_urls(
                    urls=urls_to_crawl,
                    timeout=30,
                    bypass_cache=False,
                )
                self.results["warehouse_entries"] = ingest.warehouse_entries_after
                log.info("Ingested %d/%d URLs, warehouse has %d entries",
                         ingest.success_count, ingest.urls_submitted,
                         ingest.warehouse_entries_after)
            self._phase_end()

            # Phase 4: RAG-enhanced search
            self._phase("RAG-enhanced aggregate")
            rag_result = await self.dss.aggregate(
                query=self.topic,
                max_results=self.max_sources,
                reconcile=True,
                include_warehouse=True,
                enable_scraping=False,
                enable_rag=True,
                rag_top_k=5,
            )
            self._phase_end()

            if rag_result.consensus and len(rag_result.consensus) > len(agg.consensus or []):
                self.results["consensus_facts"] = [
                    {"claim": f.claim, "confidence": f.confidence,
                     "sources": f.supporting_sources}
                    for f in rag_result.consensus
                ]
                self.results["synthesis"] = rag_result.synthesis or ""

            # Final: warehouse stats
            try:
                stats = await self.dss.warehouse_stats()
                self.results["warehouse_stats"] = stats
            except Exception:
                pass

        finally:
            await self.dss.close()

        self.results["execution_ms"] = int((time.monotonic() - self.start_time) * 1000)
        return self.results

    def print_report(self):
        """Pretty-print research results."""
        r = self.results
        total = r["execution_ms"]

        print()
        print("╔══════════════════════════════════════════════════════════════╗")
        print(f"║  DeepSearchStack Research Report                            ║")
        print(f"║  Topic: {r['topic'][:56]:56s} ║")
        print(f"║  {r['timestamp']}                    ║")
        print("╚══════════════════════════════════════════════════════════════╝")
        print()

        print(f"  Total execution: {total}ms ({total/1000:.1f}s)")
        print(f"  Sources found:   {len(r['sources'])}")
        print(f"  URLs crawled:    {len(r['crawled_urls'])}")
        print(f"  Consensus facts: {len(r['consensus_facts'])}")
        print()

        if r["phases"]:
            print("  Phase breakdown:")
            for phase, ms in r["phases"].items():
                pct = ms / total * 100 if total else 0
                print(f"    {phase:30s} {ms:>6d}ms ({pct:.0f}%)")
            print()

        if r["consensus_facts"]:
            print("  ── Consensus Facts ──")
            for i, f in enumerate(r["consensus_facts"]):
                print(f"  [{i+1}] {f['claim'][:200]}")
                print(f"       confidence={f['confidence']}  sources={f.get('sources', [])}")

        if r.get("synthesis"):
            print()
            print("  ── Synthesis ──")
            print(f"  {r['synthesis'][:600]}")

        if r["crawled_urls"]:
            print()
            print("  ── Crawled URLs ──")
            for c in r["crawled_urls"]:
                status_icon = "✓" if c["status"] == "ok" else "✗"
                content_len = c.get("content_length", 0)
                print(f"  {status_icon} {c['url'][:70]}")
                if content_len:
                    print(f"     {content_len:,} chars")

        if r.get("warehouse_stats"):
            ws = r["warehouse_stats"]
            print()
            print("  ── Knowledge Warehouse ──")
            print(f"     Entries: {ws.get('total_entries', 0)}")
            print(f"     Words:   {ws.get('total_words', 0):,}")
            print(f"     DB size: {ws.get('db_size_mb', 0)} MB")

        print()
        phase_sizes = {k: v for k, v in r["phases"].items()}
        bar_width = 40
        if phase_sizes:
            max_v = max(phase_sizes.values()) if phase_sizes else 1
            print("  Timeline:")
            for phase, ms in phase_sizes.items():
                blocks = int(ms / max_v * bar_width) if max_v else 1
                bar = "█" * max(1, blocks)
                print(f"  {bar} {ms}ms  {phase}")

        print()


async def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="DSS Research Agent — end-to-end research pipeline"
    )
    parser.add_argument("topic", help="Research topic")
    parser.add_argument("--sources", type=int, default=5, help="Max sources to collect")
    parser.add_argument("--scrape", type=int, default=3, help="Max URLs to crawl")
    parser.add_argument("--json", action="store_true", help="Output JSON report")
    args = parser.parse_args()

    agent = ResearchAgent(args.topic, max_sources=args.sources, max_scrape=args.scrape)
    results = await agent.run()

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        agent.print_report()


if __name__ == "__main__":
    asyncio.run(main())
