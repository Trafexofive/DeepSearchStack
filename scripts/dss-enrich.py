#!/usr/bin/env python3
"""Content pipeline — enrich warehouse entries with quality, entities, dedup.

Runs three passes:
  1. Quality scoring — word count, structure, source reputation
  2. Entity extraction — languages, tech, domains, people, orgs
  3. Near-duplicate detection — content hash clusters

Usage:
    python3 scripts/dss-enrich.py                dry-run (show stats)
    python3 scripts/dss-enrich.py --apply        apply enrichment to warehouse
    python3 scripts/dss-enrich.py --limit 100    process first N entries
"""
import asyncio
import hashlib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sdk import DSSClient

WAREHOUSE_URL = "http://localhost:8009"

# ── Entity patterns ────────────────────────────────────────────

PROGRAMMING_LANGUAGES = {
    'rust', 'python', 'javascript', 'typescript', 'go', 'golang',
    'java', 'c++', 'cpp', 'c', 'ruby', 'swift', 'kotlin', 'scala',
    'haskell', 'elixir', 'clojure', 'zig', 'nim', 'lua', 'r',
    'julia', 'dart', 'php', 'perl', 'bash', 'shell', 'sql',
}

TECH_TERMS = {
    'kubernetes', 'docker', 'linux', 'nginx', 'postgresql', 'redis',
    'mongodb', 'graphql', 'rest', 'grpc', 'websocket', 'mqtt',
    'tensorflow', 'pytorch', 'transformers', 'llm', 'gpt',
    'neural network', 'deep learning', 'reinforcement learning',
    'blockchain', 'ethereum', 'wasm', 'webassembly',
    'react', 'vue', 'angular', 'svelte', 'nextjs', 'nodejs',
    'aws', 'gcp', 'azure', 'terraform', 'ansible', 'ci/cd',
}

DOMAINS = {
    'arxiv.org': 9, 'github.com': 7, 'en.wikipedia.org': 9,
    'stackoverflow.com': 8, 'docs.python.org': 9, 'doc.rust-lang.org': 9,
    'medium.com': 4, 'dev.to': 5, 'youtube.com': 3,
    'richlyai.com': 3, 'fugumt.com': 3, 'www.catalyzex.com': 5,
    'huggingface.co': 7, 'lwn.net': 8, 'web.mit.edu': 8,
}


def extract_entities(text: str) -> list[str]:
    """Extract languages, tech, and patterns from text."""
    text_lower = text.lower()
    found = set()

    for lang in PROGRAMMING_LANGUAGES:
        if re.search(rf'\b{re.escape(lang)}\b', text_lower):
            found.add(f"lang:{lang}")

    for tech in TECH_TERMS:
        if tech in text_lower:
            found.add(f"tech:{tech}")

    # Extract arxiv IDs
    arxiv_ids = re.findall(r'arXiv:(\d{4}\.\d{4,5})', text) or re.findall(r'(\d{4}\.\d{4,5})', text)
    for aid in arxiv_ids[:3]:
        found.add(f"arxiv:{aid}")

    # Extract GitHub repos
    repos = re.findall(r'github\.com/([a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+)', text)
    for repo in repos[:3]:
        found.add(f"repo:{repo}")

    # Domain mentions
    domains = re.findall(r'https?://([a-zA-Z0-9.-]+\.[a-z]{2,})', text)
    for d in list(set(domains))[:3]:
        found.add(f"domain:{d}")

    return sorted(found)[:15]


def score_quality(entry: dict) -> tuple[int, str]:
    """Score entry quality 0-100. Returns (score, tier)."""
    score = 0
    words = entry.get("word_count", 0)
    title = entry.get("title", "")
    domain = entry.get("source_domain", "")
    md = entry.get("markdown", "") if entry.get("markdown") else ""

    # Word count (0-30)
    if words >= 5000: score += 30
    elif words >= 1000: score += 20
    elif words >= 200: score += 10
    elif words >= 50: score += 5

    # Title quality (0-15)
    if len(title) > 20: score += 10
    if not title.startswith("[") and "arxiv" not in title.lower(): score += 5

    # Source reputation (0-20)
    score += DOMAINS.get(domain, 3) * 2

    # Content structure (0-20)
    if md:
        headings = len(re.findall(r'^#{1,3}\s', md, re.MULTILINE))
        if headings > 10: score += 10
        elif headings > 3: score += 5
        code_blocks = len(re.findall(r'```', md))
        if code_blocks > 4: score += 5
        links = len(re.findall(r'\[.+\]\(.+\)', md))
        if links > 5: score += 5

    # Penalties (0 to -15)
    # Boilerplate detection
    boilerplate_signals = [
        'skip to content', 'navigation menu', 'toggle navigation',
        'sign in', 'you signed in', 'dismiss alert',
        '© 2025', 'all rights reserved', 'cookie consent',
    ]
    bp_count = sum(1 for bp in boilerplate_signals if bp in md.lower())
    score -= min(bp_count * 3, 15)

    # Tier
    if score >= 75: tier = "high"
    elif score >= 50: tier = "medium"
    elif score >= 25: tier = "low"
    else: tier = "garbage"

    return max(0, score), tier


def content_hash(text: str) -> str:
    """Normalized content hash for near-duplicate detection."""
    # Normalize: lowercase, strip whitespace, remove boilerplate patterns
    text = text.lower()
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'(skip to content|navigation menu|toggle navigation|sign in|cookie|© \d{4}).*?\n', '', text)
    return hashlib.md5(text[:5000].encode()).hexdigest()


async def main():
    dry_run = "--apply" not in sys.argv
    limit = None
    for i, a in enumerate(sys.argv[1:]):
        if a == '--limit' and i + 1 < len(sys.argv) - 1:
            limit = int(sys.argv[i + 2])

    mode = "DRY RUN" if dry_run else "APPLY"
    print(f"Content Pipeline — {mode}")
    print(f"  Passes: quality, entities, dedup")
    print()

    async with DSSClient() as dss:
        # Fetch entries via paginated list
        entries = []
        offset = 0
        while True:
            batch = await dss.warehouse_list(sort="ingested_at", order="desc", offset=offset, limit=100)
            if not batch:
                break
            entries.extend(batch)
            offset += 100
            if limit and len(entries) >= limit:
                entries = entries[:limit]
                break
            if len(entries) >= 5000:
                break
            print(f"  scanned {len(entries)} entries...")

        print(f"\n  Total: {len(entries)} entries")

        # ── Pass 1: Quality ──
        tiers = {"high": 0, "medium": 0, "low": 0, "garbage": 0}
        scored = []
        for e in entries:
            score, tier = score_quality(e)
            tiers[tier] += 1
            scored.append((e, score, tier))

        print(f"\n  Quality:")
        for tier, count in tiers.items():
            pct = count / len(entries) * 100 if entries else 0
            print(f"    {tier:8s} {count:>5d} ({pct:.0f}%)")

        # ── Pass 2: Entities ──
        entity_counts = {}
        all_tags = set()
        for e in entries:
            md = e.get("markdown", "")
            if not md and e.get("id"):
                # Fetch full content for entity extraction
                try:
                    content = await dss.warehouse_content(e["id"])
                    md = content.get("markdown", "")
                except Exception:
                    pass
            entities = extract_entities(md)
            for ent in entities:
                entity_counts[ent] = entity_counts.get(ent, 0) + 1
                all_tags.add(ent)

        print(f"\n  Top entities ({len(all_tags)} unique):")
        for ent, count in sorted(entity_counts.items(), key=lambda x: -x[1])[:15]:
            print(f"    {ent:30s} {count:>5d}")

        # ── Pass 3: Dedup ──
        hashes = {}
        dupes = 0
        for e in entries:
            md = e.get("markdown", "")
            if not md:
                continue
            h = content_hash(md)
            if h in hashes:
                dupes += 1
                hashes[h].append(e["id"])
            else:
                hashes[h] = [e["id"]]

        clusters = {h: ids for h, ids in hashes.items() if len(ids) > 1}
        print(f"\n  Dedup: {dupes} duplicates in {len(clusters)} clusters")
        if clusters:
            print(f"  Largest clusters:")
            for h, ids in sorted(clusters.items(), key=lambda x: -len(x[1]))[:5]:
                print(f"    {len(ids)} dupes: ids={ids[:3]}...")

        # ── Apply ──
        if not dry_run:
            print(f"\n  Applying enrichment...")
            enriched = 0
            for e, score, tier in scored:
                tags = e.get("tags", [])
                tags.append(f"quality:{tier}")
                tags.append(f"score:{score}")
                try:
                    async with dss.client as client:
                        await client.post(
                            f"{WAREHOUSE_URL}/ingest",
                            json={
                                "url": e["url"],
                                "markdown": e.get("markdown", ""),
                                "title": e["title"],
                                "source_domain": e.get("source_domain", ""),
                                "word_count": e.get("word_count", 0),
                                "tags": tags,
                            },
                            timeout=10.0,
                        )
                        enriched += 1
                except Exception:
                    pass
                if enriched % 100 == 0:
                    print(f"    {enriched}/{len(scored)} enriched")
            print(f"  ✓ {enriched} entries enriched")
        else:
            print(f"\n  Run with --apply to enrich {len(entries)} entries")


if __name__ == "__main__":
    asyncio.run(main())
