#!/usr/bin/env python3
"""DSS SDK smoke test — exercises all client methods.

Usage: python3 scripts/dss-smoke.py
"""
import asyncio, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sdk import DSSClient

async def test(name: str, fn):
    try:
        result = await fn()
        if isinstance(result, list):
            print(f"  {name}: OK ({len(result)} items)")
        elif isinstance(result, dict):
            keys = list(result.keys())[:3]
            print(f"  {name}: OK (keys: {keys})")
        else:
            print(f"  {name}: OK ({type(result).__name__})")
        return True
    except Exception as e:
        print(f"  {name}: FAIL ({e})")
        return False

async def main():
    print("DSS SDK Smoke Test\n")
    ok = 0
    total = 0

    async with DSSClient() as dss:
        # Warehouse
        total += 1; ok += await test("warehouse_stats", dss.warehouse_stats)
        total += 1; ok += await test("warehouse_search(rust,3)", lambda: dss.warehouse_search("rust", 3))
        total += 1; ok += await test("warehouse_list(newest,5)", lambda: dss.warehouse_list(sort="ingested_at", order="desc", limit=5))
        total += 1; ok += await test("warehouse_list(arxiv)", lambda: dss.warehouse_list(domain="arxiv.org", limit=3))
        total += 1; ok += await test("warehouse_content(168)", lambda: dss.warehouse_content(168))
        total += 1; ok += await test("facts(Rust)", lambda: dss.facts("Rust"))
        total += 1; ok += await test("facts(all)", dss.facts)

        # Crawler
        total += 1; ok += await test("crawler_stats", dss.crawler_stats)
        total += 1; ok += await test("crawler_pending", dss.crawler_pending)

        # Metrics
        total += 1; ok += await test("metrics", dss.metrics)

    print(f"\n{ok}/{total} tests passed")
    return 0 if ok == total else 1

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
