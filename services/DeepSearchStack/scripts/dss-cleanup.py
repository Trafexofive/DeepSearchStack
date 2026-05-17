#!/usr/bin/env python3
"""Warehouse content cleanup — removes low-quality seed entries.

Usage:
    python3 scripts/dss-cleanup.py               dry-run
    python3 scripts/dss-cleanup.py --delete      actual cleanup
    python3 scripts/dss-cleanup.py --min-words 100
"""
import asyncio, sys, httpx

WAREHOUSE_URL = "http://localhost:8009"

async def main():
    dry_run = "--delete" not in sys.argv
    min_words = 50
    for i, arg in enumerate(sys.argv[1:]):
        if arg == '--min-words' and i + 1 < len(sys.argv) - 1:
            min_words = int(sys.argv[i + 2])

    print(f"Warehouse cleanup — {'DRY RUN' if dry_run else 'DELETE MODE'}")
    print(f"  Threshold: word_count < {min_words}")
    print()

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        # Scan entries via common-word FTS5 searches
        entries = []
        seen = set()
        terms = ["the", "that", "this", "with", "from", "have", "they", "what", "when", "were", "are", "not", "but", "all", "can"]
        for term in terms:
            try:
                resp = await client.get(
                    f"{WAREHOUSE_URL}/search",
                    params={"q": term, "limit": 100},
                )
                if resp.status_code != 200:
                    continue
                data = resp.json()
                for e in data:
                    eid = e.get('id')
                    if eid and eid not in seen:
                        seen.add(eid)
                        entries.append(e)
            except Exception:
                continue
            if len(entries) >= 5000:
                break

        print(f"  Scanned {len(entries)} entries")

        garbage = [e for e in entries if e.get('word_count', 0) < min_words]
        print(f"  Garbage: {len(garbage)} entries (< {min_words} words)")

        if not garbage:
            print("  Nothing to clean up.")
            return

        # Show sample
        print("\n  Sample garbage:")
        for e in garbage[:10]:
            print(f"    [{e['id']}] {e['word_count']}w  {e.get('title','')[:60]}  {e.get('source_domain','')}")

        if dry_run:
            print(f"\n  DRY RUN — {len(garbage)} entries would be removed. Run with --delete.")
            return

        # Delete
        deleted = 0
        for e in garbage:
            try:
                resp = await client.delete(
                    f"{WAREHOUSE_URL}/content/{e['id']}",
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    deleted += 1
                elif resp.status_code != 404:
                    print(f"    ⚠ delete {e['id']}: {resp.status_code}")
            except Exception as ex:
                print(f"    ✗ {e['id']}: {ex}")
            if deleted % 50 == 0 and deleted > 0:
                print(f"    deleted {deleted}/{len(garbage)}...")

        print(f"\n  ✓ {deleted}/{len(garbage)} entries deleted")
        resp = await client.get(f"{WAREHOUSE_URL}/stats", timeout=10.0)
        stats = resp.json()
        print(f"  Warehouse: {stats['total_entries']} entries, {stats['db_size_mb']}MB")


if __name__ == "__main__":
    asyncio.run(main())
