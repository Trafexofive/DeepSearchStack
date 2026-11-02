#!/usr/bin/env python3
"""Real provider audit. One query, every provider, count hits, flag dead ones."""
import asyncio, time, httpx, json

BASE = "http://localhost:8083"
QUERY = "distributed systems consensus"

SEARCH_PROVIDERS = [
    "arxiv", "crossref", "duckduckgo", "github", "hackernews",
    "internetarchive", "pubmed", "reddit", "searxng", "stackexchange",
    "wikipedia", "yacy",
]

LLM_TESTS = [
    ("deepseek-chat", None),
    ("deepseek-v4-flash-free", None),
    ("llama-3.1-8b-instant", None),
    ("meta/llama-3.2-11b-vision-instruct", "nvidia_nim"),
]


async def test_search_provider(client, name):
    t0 = time.time()
    try:
        r = await client.post(
            f"{BASE}/dss/gateway/search",
            json={"query": QUERY, "providers": [name], "max_results": 10},
            timeout=20,
        )
        if r.status_code != 200:
            return name, "HTTP_ERR", r.status_code, time.time() - t0, ""
        d = r.json()
        results = d if isinstance(d, list) else d.get("results", [])
        sample = results[0]["title"][:60] if results else ""
        return name, "OK" if results else "EMPTY", len(results), time.time() - t0, sample
    except Exception as e:
        return name, "EXC", str(e)[:60], time.time() - t0, ""


async def test_llm(client, model, provider):
    t0 = time.time()
    try:
        headers = {"Content-Type": "application/json"}
        if provider:
            headers["x-provider"] = provider
        r = await client.post(
            f"http://localhost:8005/v1/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": "reply with exactly: ok"}],
                "max_tokens": 8,
            },
            headers=headers,
            timeout=30,
        )
        if r.status_code != 200:
            return model, "HTTP_ERR", r.status_code, time.time() - t0, r.text[:80]
        d = r.json()
        content = d.get("content", "") or d.get("raw_response", {}).get("choices", [{}])[0].get("message", {}).get("content", "")
        return model, "OK", len(content), time.time() - t0, repr(content[:30])
    except Exception as e:
        return model, "EXC", str(e)[:60], time.time() - t0, ""


async def main():
    print(f"DSS provider audit — query={QUERY!r}\n")
    async with httpx.AsyncClient() as c:
        print("=" * 78)
        print(f"SEARCH PROVIDERS ({len(SEARCH_PROVIDERS)})")
        print("=" * 78)
        print(f"{'provider':<18s} {'status':<10s} {'count':>6s} {'time':>7s}  sample")
        results = await asyncio.gather(*[test_search_provider(c, p) for p in SEARCH_PROVIDERS])
        ok = empty = err = 0
        for name, status, count, elapsed, sample in results:
            mark = {"OK": "✓", "EMPTY": "○", "HTTP_ERR": "✗", "EXC": "✗"}.get(status, "?")
            if status == "OK":
                ok += 1
            elif status == "EMPTY":
                empty += 1
            else:
                err += 1
            print(f"  {mark} {name:<16s} {status:<10s} {str(count):>6s} {elapsed:>6.2f}s  {sample}")
        print(f"\nSEARCH summary: {ok} OK, {empty} empty, {err} errored")

        print()
        print("=" * 78)
        print(f"LLM PROVIDERS ({len(LLM_TESTS)} sample models)")
        print("=" * 78)
        print(f"{'model':<42s} {'status':<10s} {'chars':>6s} {'time':>7s}  reply")
        ok = err = 0
        for model, prov in LLM_TESTS:
            name, status, count, elapsed, sample = await test_llm(c, model, prov)
            mark = "✓" if status == "OK" else "✗"
            if status == "OK":
                ok += 1
            else:
                err += 1
            print(f"  {mark} {name:<40s} {status:<10s} {str(count):>6s} {elapsed:>6.2f}s  {sample}")
        print(f"\nLLM summary: {ok}/{len(LLM_TESTS)} ok")


if __name__ == "__main__":
    asyncio.run(main())
