#!/usr/bin/env python3
"""DeepSearchStack CLI — test client for the full stack.

Usage:
    python3 scripts/dss.py health              # Health check all services
    python3 scripts/dss.py search "query"       # Aggregate search
    python3 scripts/dss.py stream "query"       # Streaming search (SSE)
    python3 scripts/dss.py list [--domain x]    # Warehouse listing (newest first)
    python3 scripts/dss.py content <id>         # View warehouse entry
    python3 scripts/dss.py facts [query]        # Query consensus fact DB
    python3 scripts/dss.py ingest url1 url2...  # Bulk URL ingestion
    python3 scripts/dss.py crawl <url>          # Single URL crawl
    python3 scripts/dss.py warehouse [query]    # Warehouse stats or search
    python3 scripts/dss.py feed <rss_url>      # Ingest RSS/Atom feed
    python3 scripts/dss.py metrics             # Service metrics

Environment:
    DSS_WEB_API     Web API URL (default: http://localhost:8014)
    DSS_CRAWLER     Crawler URL (default: http://localhost:8000)
    DSS_WAREHOUSE   Warehouse URL (default: http://localhost:8009)
"""
import asyncio
import json
import os
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sdk import DSSClient


async def cmd_health(client: DSSClient):
    print(await client.health_report())


async def cmd_search(client: DSSClient, query: str, scrape: bool = False, rag: bool = False):
    print(f"Searching: {query}")
    result = await client.aggregate(
        query, max_results=10, reconcile=True,
        enable_scraping=scrape, max_scrape_urls=3, enable_rag=rag,
    )
    print(f"\n{result.total_sources} sources across {len(result.domains_queried)} domains")
    print(f"Execution: {result.execution_time_ms}ms | Scraped: {result.scraped_urls} | RAG: {result.rag_chunks}")
    if result.consensus:
        print(f"\n-- Consensus Facts ({len(result.consensus)}) --")
        for c in result.consensus:
            print(f"  [{c.confidence:.2f}] {c.claim}")
    if result.synthesis:
        print(f"\n-- Synthesis --\n{result.synthesis[:500]}")
    print(f"\n-- Sources --")
    for s in result.sources[:15]:
        print(f"  [{s.domain:15s}] {s.title[:80]}")


async def cmd_list(client: DSSClient, domain: str = None):
    entries = await client.warehouse_list(domain=domain, limit=20)
    print(f"Warehouse -- {len(entries)} entries (newest first):")
    for e in entries:
        print(f"  [{e['id']:>5d}] {e['title'][:60]:60s} {e['word_count']:>6d}w  {e['source_domain']}")


async def cmd_content(client: DSSClient, id: int):
    c = await client.warehouse_content(id)
    print(f"Title: {c.get('title','?')}")
    print(f"URL:   {c.get('url','?')}")
    print(f"Words: {c.get('word_count',0)}  Domain: {c.get('source_domain','?')}")
    print()
    md = c.get("markdown","")
    if len(md) > 5000:
        md = md[:5000] + "\n... [truncated]"
    print(textwrap.indent(md, "  "))


async def cmd_facts(client: DSSClient, query: str = None):
    data = await client.facts(query)
    facts = data.get("facts", [])
    print(f"Fact DB: {data.get('total',0)} total, {len(facts)} matching")
    for f in facts:
        print(f"  * {f['claim'][:100]}")
        if f.get("sources"):
            print(f"    sources: {', '.join(f['sources'][:3])}")


async def cmd_ingest(client: DSSClient, urls: list[str]):
    print(f"Ingesting {len(urls)} URLs...")
    result = await client.ingest_urls(urls)
    print(f"  Submitted: {result.urls_submitted}")
    print(f"  Success: {result.success_count} | Failed: {result.failure_count}")
    print(f"  Duration: {result.total_duration_ms:.0f}ms")
    print(f"  Warehouse entries: {result.warehouse_entries_after}")


async def cmd_crawl(client: DSSClient, url: str):
    print(f"Crawling: {url}")
    result = await client.crawl(url)
    status = "OK" if result.get("success") else "FAIL"
    print(f"  {status} {result.get('title', 'N/A')[:80]}")
    print(f"  Words: {result.get('word_count', 0)} | Cache: {result.get('cache_hit')}")


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
        print(f"  Top domains:")
        for d in stats["domains"][:10]:
            print(f"    {d['domain']:40s} {d['count']:>6,}")


async def cmd_stream(client: DSSClient, query: str):
    print(f"Streaming: {query}")
    async for chunk in client.aggregate_stream(query):
        content = chunk.get("content", "")
        if chunk.get("finished"):
            print(f"\n-- Done ({len(chunk.get('sources', []))} sources) --")
            break
        print(content, end="", flush=True)
    print()


async def cmd_feed(client: DSSClient, feed_url: str):
    print(f"Feed: {feed_url}")
    result = await client.ingest_feed(feed_url)
    print(f"  Title: {result['feed_title']}")
    print(f"  Items: {result['items_found']} found, {result['queued_for_crawl']} queued")


async def cmd_pending(client: DSSClient):
    pending = await client.crawler_pending()
    print(f"Pending forwards: {pending['total']}")
    for p in pending["pending"]:
        print(f"  [{p['id']}] {p['url'][:100]}")


async def cmd_metrics(client: DSSClient):
    m = await client.metrics()
    print(f"Uptime: {m['uptime_seconds']:.0f}s")
    print(f"\n-- Counters --")
    for k, v in sorted(m.get('counters', {}).items()):
        print(f"  {k:35s} {v}")
    print(f"\n-- Latency (ms) --")
    for k, v in sorted(m.get('timers_ms', {}).items()):
        print(f"  {k:35s} p50={v['p50']:.0f} p95={v['p95']:.0f} avg={v['avg']:.0f} n={v['count']}")
    if 'derived' in m:
        print(f"\n-- Derived --")
        for k, v in m['derived'].items():
            print(f"  {k:35s} {v}")


COMMANDS = {
    "health":    (cmd_health,   "Health check all services"),
    "search":    (cmd_search,   "Aggregate search with reconciliation"),
    "stream":    (cmd_stream,   "Streaming search (SSE)"),
    "list":      (cmd_list,     "Warehouse listing (newest first)"),
    "content":   (cmd_content,  "View warehouse entry by ID"),
    "facts":     (cmd_facts,    "Query consensus fact database"),
    "ingest":    (cmd_ingest,   "Bulk URL ingestion"),
    "crawl":     (cmd_crawl,    "Single URL crawl"),
    "warehouse": (cmd_warehouse,"Warehouse stats or search"),
    "feed":      (cmd_feed,     "Ingest RSS/Atom feed"),
    "metrics":   (cmd_metrics,  "Service metrics"),
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

    args = sys.argv[2:]
    scrape = "--scrape" in args
    rag = "--rag" in args
    domain = None
    for i, a in enumerate(args):
        if a == '--domain' and i + 1 < len(args):
            domain = args[i + 1]
    args = [a for a in args if a not in ("--scrape", "--rag", "--domain")]
    if domain:
        args = [a for a in args if a != domain]

    async with DSSClient() as client:
        if cmd_name == "list":
            await cmd_list(client, domain=domain)
        elif cmd_name == "content":
            if not args:
                print("Usage: dss.py content <id>")
                sys.exit(1)
            await cmd_content(client, int(args[0]))
        elif cmd_name == "facts":
            await cmd_facts(client, " ".join(args) if args else None)
        elif cmd_name == "search":
            if not args:
                print("Usage: dss.py search <query> [--scrape] [--rag]")
                sys.exit(1)
            await cmd_search(client, " ".join(args), scrape=scrape, rag=rag)
        elif cmd_name == "stream":
            if not args:
                print("Usage: dss.py stream <query>")
                sys.exit(1)
            await cmd_stream(client, " ".join(args))
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
        elif cmd_name == "feed":
            if not args:
                print("Usage: dss.py feed <rss_url>")
                sys.exit(1)
            await cmd_feed(client, args[0])
        elif cmd_name == "metrics":
            await cmd_metrics(client)
        elif cmd_name == "health":
            await cmd_health(client)
        elif cmd_name == "pending":
            await cmd_pending(client)


if __name__ == "__main__":
    asyncio.run(main())
