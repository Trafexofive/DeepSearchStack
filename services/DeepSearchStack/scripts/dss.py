#!/usr/bin/env python3
"""DeepSearchStack CLI — test client for the full stack.

Usage:
    python3 scripts/dss.py health              # Health check all services
    python3 scripts/dss.py search "query"       # Aggregate search
    python3 scripts/dss.py search "query" --scrape --rag  # With scraping + RAG
    python3 scripts/dss.py ingest url1 url2...  # Bulk URL ingestion
    python3 scripts/dss.py crawl <url>          # Single URL crawl
    python3 scripts/dss.py warehouse [query]    # Warehouse stats or search
    python3 scripts/dss.py stream "query"       # Streaming search (SSE)
    python3 scripts/dss.py pending              # Pending warehouse forwards

Environment:
    DSS_WEB_API     Web API URL (default: http://localhost:8014)
    DSS_CRAWLER     Crawler URL (default: http://localhost:8000)
    DSS_WAREHOUSE   Warehouse URL (default: http://localhost:8009)
"""
import asyncio
import json
import os
import sys
from pathlib import Path

# Add sdk to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sdk import DSSClient


async def cmd_health(client: DSSClient):
    print(await client.health_report())


async def cmd_search(client: DSSClient, query: str, scrape: bool = False, rag: bool = False):
    print(f"Searching: {query}")
    result = await client.aggregate(
        query,
        max_results=10,
        reconcile=True,
        enable_scraping=scrape,
        max_scrape_urls=3,
        enable_rag=rag,
    )
    print(f"\n{result.total_sources} sources across {len(result.domains_queried)} domains")
    print(f"Execution: {result.execution_time_ms}ms | Scraped: {result.scraped_urls} | RAG: {result.rag_chunks}")

    if result.consensus:
        print(f"\n── Consensus Facts ({len(result.consensus)}) ──")
        for i, c in enumerate(result.consensus, 1):
            print(f"  [{c.confidence:.2f}] {c.claim}")

    if result.synthesis:
        print(f"\n── Synthesis ──")
        print(result.synthesis[:500])

    print(f"\n── Sources ──")
    for s in result.sources[:15]:
        print(f"  [{s.domain:15s}] {s.title[:80]}")


async def cmd_ingest(client: DSSClient, urls: list[str]):
    print(f"Ingesting {len(urls)} URLs...")
    result = await client.ingest_urls(urls)
    print(f"  Submitted: {result.urls_submitted}")
    print(f"  Success: {result.success_count} | Failed: {result.failure_count} | Cache hits: {result.cache_hits}")
    print(f"  Duration: {result.total_duration_ms:.0f}ms")
    print(f"  Warehouse entries: {result.warehouse_entries_after}")


async def cmd_crawl(client: DSSClient, url: str):
    print(f"Crawling: {url}")
    result = await client.crawl(url)
    status = "✓" if result.get("success") else "✗"
    print(f"  {status} {result.get('title', 'N/A')}")
    print(f"  Words: {result.get('word_count', 0)} | Cache: {result.get('cache_hit')}")
    if not result.get("success"):
        print(f"  Error: {result.get('error_type')} — {result.get('error_message', '')[:200]}")


async def cmd_warehouse(client: DSSClient, query: str | None = None):
    if query:
        print(f"Warehouse search: {query}")
        results = await client.warehouse_search(query, limit=10)
        print(f"  {len(results)} results")
        for r in results:
            print(f"  [{r.get('source_domain', '?')}] {r.get('title', 'N/A')[:80]}")
    else:
        stats = await client.warehouse_stats()
        print(f"Warehouse: {stats['total_entries']} entries, {stats['total_words']} words")
        print(f"  Size: {stats['db_size_mb']} MB")
        print(f"  Domains:")
        for d in stats["domains"][:20]:
            print(f"    {d['domain']:40s} {d['count']}")


async def cmd_stream(client: DSSClient, query: str):
    print(f"Streaming: {query}")
    async for chunk in client.aggregate_stream(query):
        content = chunk.get("content", "")
        if chunk.get("finished"):
            print(f"\n── Done ({len(chunk.get('sources', []))} sources) ──")
            break
        print(content, end="", flush=True)
    print()


async def cmd_pending(client: DSSClient):
    pending = await client.crawler_pending()
    print(f"Pending forwards: {pending['total']}")
    for p in pending["pending"]:
        print(f"  [{p['id']}] {p['url'][:100]} — {p['attempts']} attempts")


COMMANDS = {
    "health": (cmd_health, "Health check all services"),
    "search": (cmd_search, "Aggregate search with reconciliation"),
    "ingest": (cmd_ingest, "Bulk URL ingestion"),
    "crawl": (cmd_crawl, "Single URL crawl"),
    "warehouse": (cmd_warehouse, "Warehouse stats or search"),
    "stream": (cmd_stream, "Streaming search (SSE)"),
    "pending": (cmd_pending, "Pending warehouse forwards"),
}


def print_usage():
    print(__doc__)
    print("Commands:")
    for name, (_, desc) in COMMANDS.items():
        print(f"  {name:15s} {desc}")
    sys.exit(1)


async def main():
    if len(sys.argv) < 2:
        print_usage()

    cmd_name = sys.argv[1]
    if cmd_name not in COMMANDS:
        print(f"Unknown command: {cmd_name}")
        print_usage()

    cmd_fn, _ = COMMANDS[cmd_name]
    args = sys.argv[2:]

    scrape = "--scrape" in args
    rag = "--rag" in args
    args = [a for a in args if a not in ("--scrape", "--rag")]

    async with DSSClient() as client:
        if cmd_name == "health":
            await cmd_health(client)
        elif cmd_name == "search":
            if not args:
                print("Usage: dss.py search <query> [--scrape] [--rag]")
                sys.exit(1)
            await cmd_search(client, " ".join(args), scrape=scrape, rag=rag)
        elif cmd_name == "ingest":
            if not args:
                print("Usage: dss.py ingest <url1> [url2...]")
                sys.exit(1)
            await cmd_ingest(client, args)
        elif cmd_name == "crawl":
            if not args:
                print("Usage: dss.py crawl <url>")
                sys.exit(1)
            await cmd_crawl(client, args[0])
        elif cmd_name == "warehouse":
            await cmd_warehouse(client, " ".join(args) if args else None)
        elif cmd_name == "stream":
            if not args:
                print("Usage: dss.py stream <query>")
                sys.exit(1)
            await cmd_stream(client, " ".join(args))
        elif cmd_name == "pending":
            await cmd_pending(client)


if __name__ == "__main__":
    asyncio.run(main())
