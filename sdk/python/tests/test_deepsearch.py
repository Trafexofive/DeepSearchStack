"""SDK v2 tests — unit + integration.

Unit tests run offline (no stack required).
Integration tests run against a live `make up` stack.
Run with: `python sdk/python/tests/test_deepsearch.py`

To skip integration tests: `python sdk/python/tests/test_deepsearch.py --unit`
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from typing import List

# Make the SDK importable from this file's directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import deepsearch as ds
from deepsearch import (
    AsyncDeepSearchClient,
    CrawlResult,
    DeepSearchClient,
    EmbedResult,
    ModelInfo,
    SearchHit,
    SearchResult,
    SynthesizedChunk,
    WarehouseHit,
    validate_citations,
)


# ─── Unit tests (no network) ───────────────────────────────────────────


def test_validate_citations_no_citations() -> None:
    r = validate_citations("Just text.", 5)
    assert r == {"total": 0, "valid": [], "invalid": [], "invalid_strs": []}, r


def test_validate_citations_all_valid() -> None:
    r = validate_citations("A [1] B [2] C [3] D [1].", 5)
    assert r["total"] == 4
    assert r["valid"] == [1, 2, 3, 1]
    assert r["invalid"] == []


def test_validate_citations_hallucinated() -> None:
    r = validate_citations("[1] [7] [10] [3].", 3)
    assert r["valid"] == [1, 3]
    assert r["invalid"] == [7, 10]
    assert r["invalid_strs"] == ["[7]", "[10]"]


def test_validate_citations_dedup() -> None:
    r = validate_citations("[1] [1] [99] [99] [1].", 3)
    assert r["valid"] == [1, 1, 1]
    assert r["invalid"] == [99]  # deduped
    assert r["invalid_strs"] == ["[99]"]


def test_validate_citations_edge_cases() -> None:
    # 0 is invalid (must be >= 1), -1 doesn't match \\d+, 1.5 doesn't match \\d+
    r = validate_citations("Bad: [0] [-1] [1.5] [1].", 3)
    assert r["valid"] == [1]
    assert r["invalid"] == [0]


def test_validate_citations_multidigit() -> None:
    r = validate_citations("[10] [11] [12].", 12)
    assert r["valid"] == [10, 11, 12]
    assert r["invalid"] == []


def test_validate_citations_realistic() -> None:
    text = (
        "Rust is a systems language [1] with memory safety [1] without GC [2]. "
        "Some claim [99] but the docs [3] disagree."
    )
    r = validate_citations(text, 3)
    assert r["valid"] == [1, 1, 2, 3]
    assert r["invalid"] == [99]


def test_llm_base_url_inference() -> None:
    c = AsyncDeepSearchClient(base_url="http://localhost:8083")
    assert c.llm_base_url == "http://localhost:8005"
    c2 = AsyncDeepSearchClient(base_url="http://example.com:9000", llm_base_url="http://custom:1234")
    assert c2.llm_base_url == "http://custom:1234"


# ─── Integration tests (need live stack) ──────────────────────────────


def _stack_up() -> bool:
    """Quick health check before integration tests."""
    import httpx
    try:
        r = httpx.get("http://localhost:8083/health", timeout=2.0)
        return r.status_code == 200
    except Exception:
        return False


def integration_catalog() -> None:
    if not _stack_up():
        print("  SKIP (stack down)")
        return
    with DeepSearchClient() as c:
        models, err = c.list_models()
        assert err is None, f"list_models failed: {err}"
        assert len(models) > 0
        assert all(isinstance(m, ModelInfo) for m in models)
        print(f"  list_models: {len(models)} models ✓")


def integration_search() -> None:
    if not _stack_up():
        print("  SKIP")
        return
    with DeepSearchClient() as c:
        res, err = c.search("python", providers=["searxng"], max_results=3)
        assert err is None, f"search failed: {err}"
        assert isinstance(res, SearchResult)
        assert all(isinstance(h, SearchHit) for h in res.hits)
        print(f"  search: {len(res.hits)} hits ✓")


def integration_aggregate() -> None:
    if not _stack_up():
        print("  SKIP")
        return
    with DeepSearchClient() as c:
        res, err = c.aggregate("python", providers=["searxng", "github"], max_results=2, timeout=15.0)
        assert err is None, f"aggregate failed: {err}"
        assert isinstance(res, SearchResult)
        print(f"  aggregate: {len(res.hits)} hits ✓")


def integration_llm_complete() -> None:
    if not _stack_up():
        print("  SKIP")
        return
    with DeepSearchClient() as c:
        text, err = c.llm_complete(
            [{"role": "user", "content": "Reply with the single word: OK"}],
            model="virtual/free-coder",
        )
        assert err is None, f"llm_complete failed: {err}"
        assert text and "OK" in text
        print(f"  llm_complete: {text.strip()[:40]!r} ✓")


def integration_llm_stream() -> None:
    if not _stack_up():
        print("  SKIP")
        return
    with DeepSearchClient() as c:
        chunks = list(c.llm_stream(
            [{"role": "user", "content": "Reply: OK"}],
            model="virtual/free-coder",
        ))
        full = "".join(c for c, _ in chunks)
        assert "OK" in full
        print(f"  llm_stream: {len(chunks)} chunks, total: {full.strip()!r} ✓")


def integration_synthesize() -> None:
    if not _stack_up():
        print("  SKIP")
        return
    with DeepSearchClient() as c:
        text, err = c.synthesize(
            "What is Python in one sentence?",
            [
                {"title": "Python.org", "url": "https://python.org/", "description": "Python is a programming language.", "source": "web", "confidence": 1.0},
                {"title": "Wikipedia", "url": "https://en.wikipedia.org/wiki/Python_(programming_language)", "description": "Python is a high-level, general-purpose language.", "source": "web", "confidence": 1.0},
            ],
        )
        assert err is None, f"synthesize failed: {err}"
        assert len(text) > 0
        print(f"  synthesize: {len(text)} chars ✓")


def integration_crawl() -> None:
    if not _stack_up():
        print("  SKIP")
        return
    with DeepSearchClient() as c:
        res, err = c.crawl("https://example.com", timeout=15)
        assert err is None, f"crawl failed: {err}"
        assert res.success
        assert "Example Domain" in res.content
        print(f"  crawl: {len(res.content)} chars, title={res.title!r} ✓")


def integration_embed_and_query() -> None:
    if not _stack_up():
        print("  SKIP")
        return
    with DeepSearchClient() as c:
        res, err = c.embed(
            [{"text": "the quick brown fox jumps over the lazy dog", "id": "test-int-1"}],
            namespace="sdk_int_test",
        )
        assert err is None, f"embed failed: {err}"
        assert res.count == 1
        # query back
        res2, err2 = c.vector_query("fox jumps", namespace="sdk_int_test", top_k=1)
        assert err2 is None, f"vector_query failed: {err2}"
        ids = (res2.get("ids") or [[]])[0]
        assert len(ids) > 0
        print(f"  embed+query: count=1, queried back {len(ids)} hits ✓")


def integration_warehouse() -> None:
    if not _stack_up():
        print("  SKIP")
        return
    with DeepSearchClient() as c:
        hits, err = c.warehouse_search("python", limit=2)
        assert err is None, f"warehouse_search failed: {err}"
        assert all(isinstance(h, WarehouseHit) for h in hits)
        stats, err = c.warehouse_stats()
        assert err is None
        assert "total_entries" in stats
        print(f"  warehouse: {len(hits)} hits, {stats['total_entries']} total entries ✓")


# ─── Runner ────────────────────────────────────────────────────────────


UNIT_TESTS = [
    test_validate_citations_no_citations,
    test_validate_citations_all_valid,
    test_validate_citations_hallucinated,
    test_validate_citations_dedup,
    test_validate_citations_edge_cases,
    test_validate_citations_multidigit,
    test_validate_citations_realistic,
    test_llm_base_url_inference,
]

INTEGRATION_TESTS = [
    integration_catalog,
    integration_search,
    integration_aggregate,
    integration_llm_complete,
    integration_llm_stream,
    integration_synthesize,
    integration_crawl,
    integration_embed_and_query,
    integration_warehouse,
]


def main():
    unit_only = "--unit" in sys.argv

    print(f"=== SDK unit tests ({len(UNIT_TESTS)}) ===")
    n_pass = n_fail = 0
    for t in UNIT_TESTS:
        try:
            t()
            print(f"  ✓ {t.__name__}")
            n_pass += 1
        except Exception as e:
            print(f"  ✗ {t.__name__}: {e}")
            n_fail += 1
    print(f"  {n_pass} passed, {n_fail} failed\n")

    if unit_only:
        return 0 if n_fail == 0 else 1

    print(f"=== SDK integration tests ({len(INTEGRATION_TESTS)}) — needs live stack ===")
    n_pass = n_fail = 0
    for t in INTEGRATION_TESTS:
        print(f"  {t.__name__}:", end=" ")
        try:
            t()
            n_pass += 1
        except Exception as e:
            print(f"FAIL: {e}")
            n_fail += 1
    print(f"\n  {n_pass} passed, {n_fail} failed")
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
