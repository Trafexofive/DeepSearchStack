#!/usr/bin/env python3
"""Live quality audit: hybrid vs FTS5 vs vector for the same query.

Picks diverse queries that probe DIFFERENT failure modes:
  - exact-match query (FTS5 wins on its own)
  - paraphrased query (vector wins on its own)
  - mixed (hybrid should beat both)
"""
import httpx, json, time

BASE = "http://localhost:8083"

QUERIES = [
    "raft consensus log replication",        # exact terms — FTS5 territory
    "how do distributed databases reach agreement on writes",  # paraphrase — vector territory
    "BEAM scheduler reduction counting",     # mixed
    "garbage collection in concurrent runtimes",  # semantic
]

def fts(q, k=8):
    r = httpx.get(f"{BASE}/dss/warehouse/search", params={"q": q, "limit": k}, timeout=20)
    return r.json() if r.status_code == 200 else []

def vec(q, k=8):
    r = httpx.post(f"{BASE}/dss/vectors/query",
                   json={"query_text": q, "n_results": k, "namespace": "warehouse"},
                   timeout=20)
    d = r.json() if r.status_code == 200 else {}
    ids = (d.get("ids") or [[]])[0]
    metas = (d.get("metadatas") or [[]])[0]
    dists = (d.get("distances") or [[]])[0]
    out = []
    for i, vid in enumerate(ids):
        bare = vid.rsplit(":", 1)[-1] if ":" in vid else vid
        wid = int(bare[3:]) if bare.startswith("wh-") else 0
        m = metas[i] if i < len(metas) else {}
        out.append({"id": wid, "url": m.get("url", ""), "title": m.get("title", ""), "dist": dists[i] if i < len(dists) else 1.0})
    return out

def hybrid(q, k=8):
    r = httpx.get(f"{BASE}/dss/api/search/hybrid", params={"q": q, "limit": k}, timeout=30)
    return r.json() if r.status_code == 200 else {}

def dump_row(idx, title, url, extra=""):
    title = (title or "?")[:70]
    url = (url or "")[:80]
    print(f"  {idx:>2}. {title}")
    print(f"      {url}  {extra}")

def main():
    for q in QUERIES:
        print()
        print("=" * 100)
        print(f"QUERY: {q!r}")
        print("=" * 100)

        # FTS5 only
        t0 = time.time(); fts_hits = fts(q); fts_ms = int((time.time()-t0)*1000)
        print(f"\n  FTS5 only ({len(fts_hits)} hits, {fts_ms}ms):")
        if not fts_hits:
            print("    (no hits — FTS5 strict AND failed)")
        for i, h in enumerate(fts_hits[:5], 1):
            dump_row(i, h.get("title"), h.get("url"))

        # Vector only
        t0 = time.time(); vec_hits = vec(q); vec_ms = int((time.time()-t0)*1000)
        print(f"\n  Vector only ({len(vec_hits)} hits, {vec_ms}ms):")
        for i, h in enumerate(vec_hits[:5], 1):
            dump_row(i, h.get("title"), h.get("url"), f"dist={h['dist']:.3f}")

        # Hybrid (fused)
        t0 = time.time(); h_resp = hybrid(q); h_ms = int((time.time()-t0)*1000)
        h_hits = h_resp.get("hits", [])
        print(f"\n  HYBRID ({len(h_hits)} hits, {h_ms}ms; reported {h_resp.get('elapsed_ms')}ms internal):")
        for i, h in enumerate(h_hits[:6], 1):
            badges = []
            if h.get("fts_rank") is not None:
                badges.append(f"fts#{h['fts_rank']}")
            if h.get("vec_rank") is not None:
                badges.append(f"vec#{h['vec_rank']}")
            extra = f"rrf={h.get('rrf_score',0):.4f}  [{', '.join(badges) or '?'}]"
            dump_row(i, h.get("title"), h.get("url"), extra)

        # Quality readout: rows present in BOTH rankings (★) = high-confidence
        both = sum(1 for h in h_hits if h.get("fts_rank") and h.get("vec_rank"))
        only_fts = sum(1 for h in h_hits if h.get("fts_rank") and not h.get("vec_rank"))
        only_vec = sum(1 for h in h_hits if h.get("vec_rank") and not h.get("fts_rank"))
        print(f"\n  Composition: ★both={both}  fts-only={only_fts}  vec-only={only_vec}")

if __name__ == "__main__":
    main()
