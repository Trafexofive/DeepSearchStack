"""proxy-rotator — fetch, test, and rotate free HTTP proxies into tinyproxy upstream."""
import asyncio
import json
import logging
import os
import random
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI

logging.basicConfig(level=logging.INFO, format="%(asctime)s [rotator] %(message)s")
log = logging.getLogger("proxy-rotator")

POOL_FILE = Path(os.environ.get("POOL_FILE", "/app/data/proxy-pool.json"))
PROXY_PORT = int(os.environ.get("PROXY_PORT", "8888"))

app = FastAPI(title="proxy-rotator", version="0.1.0")

# ─── State ────────────────────────────────────────────────────

pool: list[dict] = []  # [{host, port, protocol, latency_ms, last_test, source}]

# ─── Sources ──────────────────────────────────────────────────

PROXY_SOURCES = [
    # JSON/CSV feeds that return plain lists
    "https://proxylists.net/proxylists.json",
    "https://www.proxyscrape.com/free-proxy-list",
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=all",
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=https&timeout=5000&country=all&ssl=all&anonymity=all",
    "https://www.sslproxies.org/",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-http.txt",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-https.txt",
    "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://openproxy.space/list/http",
    "https://openproxy.space/list/https",
]


async def fetch_proxies() -> set[str]:
    """Fetch raw proxy strings from all sources."""
    found = set()
    async with httpx.AsyncClient(timeout=15.0) as client:
        for url in PROXY_SOURCES:
            try:
                resp = await client.get(url, follow_redirects=True)
                text = resp.text
                # Extract IP:PORT patterns from any format
                import re
                proxies = re.findall(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{2,5})\b', text)
                for p in proxies:
                    found.add(p)
                log.info(f"fetched {url[:50]}: {len(proxies)} raw proxies")
            except Exception as e:
                log.debug(f"fetch_failed {url[:50]}: {e}")
    log.info(f"total_raw_proxies: {len(found)}")
    return found


async def test_proxy(host: str, port: int, protocol: str = "http") -> dict | None:
    """Test a single proxy. Returns latency ms or None."""
    proxy_url = f"{protocol}://{host}:{port}"
    try:
        t0 = time.monotonic()
        async with httpx.AsyncClient(proxy=proxy_url, timeout=8.0) as client:
            resp = await client.get("http://example.com")
            if resp.status_code < 500:
                latency = int((time.monotonic() - t0) * 1000)
                return {"host": host, "port": port, "protocol": protocol, "latency_ms": latency}
    except Exception:
        pass
    return None


async def test_batch(proxies: set[str], concurrency: int = 50) -> list[dict]:
    """Test a batch of proxies concurrently."""
    tasks = []
    for p in proxies:
        try:
            host, port = p.split(":")
            tasks.append(test_proxy(host, int(port), "http"))
        except ValueError:
            continue

    results = []
    sem = asyncio.Semaphore(concurrency)

    async def limited_test(coro):
        async with sem:
            r = await coro
            if r:
                results.append(r)

    await asyncio.gather(*[limited_test(t) for t in tasks])
    return sorted(results, key=lambda r: r["latency_ms"])


async def refresh_pool():
    """Full refresh cycle: fetch → test → update pool."""
    global pool
    log.info("refresh_starting")
    raw = await fetch_proxies()
    if not raw:
        log.warning("no_proxies_fetched")
        return

    working = await test_batch(raw, concurrency=50)
    if working:
        pool = working
        _save_pool()
        log.info(f"refresh_complete: {len(working)} working proxies, fastest={working[0]['latency_ms']}ms")
    else:
        log.warning("no_working_proxies")


def _save_pool():
    POOL_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "updated": datetime.now(timezone.utc).isoformat(),
        "count": len(pool),
        "proxies": pool[:200],
    }
    POOL_FILE.write_text(json.dumps(data, indent=2))


async def refresh_loop():
    """Background loop: refresh pool every 30 minutes."""
    while True:
        await refresh_pool()
        await asyncio.sleep(1800)


# ─── Routes ───────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "pool_size": len(pool)}

@app.get("/pool")
async def get_pool(limit: int = 10):
    return {"count": len(pool), "proxies": pool[:limit]}

@app.post("/refresh")
async def trigger_refresh():
    asyncio.create_task(refresh_pool())
    return {"status": "refreshing"}

@app.get("/random")
async def random_proxy():
    if not pool:
        return {"status": "empty"}
    p = random.choice(pool[:50])  # top 50 for quality
    return {"proxy": f"{p['protocol']}://{p['host']}:{p['port']}", "latency_ms": p["latency_ms"]}


@app.on_event("startup")
async def startup():
    # Load existing pool
    if POOL_FILE.exists():
        data = json.loads(POOL_FILE.read_text())
        global pool
        pool = data.get("proxies", [])
        log.info(f"loaded_pool: {len(pool)} proxies")
    asyncio.create_task(refresh_loop())
    log.info("rotator_started")
