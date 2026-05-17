"""proxy-rotator — fetch, test, rotate free HTTP proxies into tinyproxy upstream."""
import asyncio
import json
import logging
import os
import random
import re
import shutil
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI

logging.basicConfig(level=logging.INFO, format="%(asctime)s [rotator] %(message)s")
log = logging.getLogger("proxy-rotator")

POOL_FILE = Path(os.environ.get("POOL_FILE", "/app/data/proxy-pool.json"))
TINYPROXY_BIN = os.environ.get("TINYPROXY_BIN", "tinyproxy")
CONFIG_PATH = Path("/app/tinyproxy.conf")

app = FastAPI(title="proxy-rotator", version="0.1.0")

pool: list[dict] = []
tinyproxy_proc: subprocess.Popen | None = None

PROXY_SOURCES = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks4.txt",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-http.txt",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-https.txt",
    "https://raw.githubusercontent.com/hookzof/socks5_list/master/proxy.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=all",
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=https&timeout=5000&country=all&ssl=all&anonymity=all",
    "https://proxylists.net/proxylists.json",
]


def _base_config() -> str:
    return """User nobody
Group nogroup
Port 8888
Listen 0.0.0.0
Timeout 60

Allow 127.0.0.1
Allow 172.0.0.0/8
Allow 10.0.0.0/8
Allow 192.168.0.0/16

DisableViaHeader Yes
Anonymous "Cookie"
Anonymous "Authorization"

LogLevel Error
PidFile "/var/run/tinyproxy/tinyproxy.pid"

MaxClients 50
MinSpareServers 3
MaxSpareServers 10
StartServers 5
MaxRequestsPerChild 5000
"""


def _write_config(upstream_host: str = "", upstream_port: int = 0):
    """Write tinyproxy config with optional upstream."""
    config = _base_config()
    if upstream_host and upstream_port:
        config += f"Upstream http {upstream_host}:{upstream_port}\n"
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(config)


def _start_tinyproxy():
    """Start tinyproxy subprocess."""
    global tinyproxy_proc
    # Ensure config has valid upstream (use loopback if no pool)
    best = pool[0] if pool else {"host": "127.0.0.1", "port": 1}
    _write_config(best["host"], best["port"])
    tinyproxy_proc = subprocess.Popen(
        [TINYPROXY_BIN, "-d", "-c", str(CONFIG_PATH)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    log.info("tinyproxy_started")


def _restart_tinyproxy():
    """Restart tinyproxy with current best proxy."""
    global tinyproxy_proc
    if tinyproxy_proc:
        tinyproxy_proc.send_signal(signal.SIGTERM)
        try:
            tinyproxy_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            tinyproxy_proc.kill()
    _start_tinyproxy()


async def fetch_proxies() -> list[str]:
    """Fetch raw proxy strings from all sources."""
    found = set()
    async with httpx.AsyncClient(timeout=15.0) as client:
        for url in PROXY_SOURCES:
            try:
                resp = await client.get(url, follow_redirects=True)
                proxies = re.findall(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}:\d{2,5})\b', resp.text)
                for p in proxies:
                    found.add(p)
            except Exception:
                pass
    return list(found)[:500]  # cap for speed


async def test_proxy(host: str, port: int, protocol: str = "http") -> dict | None:
    proxy_url = f"{protocol}://{host}:{port}"
    try:
        t0 = time.monotonic()
        async with httpx.AsyncClient(proxy=proxy_url, timeout=5.0) as client:
            resp = await client.get("http://example.com")
            if resp.status_code < 500:
                return {"host": host, "port": port, "protocol": protocol, "latency_ms": int((time.monotonic() - t0) * 1000)}
    except Exception:
        pass
    return None


async def test_batch(proxies: list[str], concurrency: int = 100) -> list[dict]:
    tasks = []
    for p in proxies:
        try:
            host, port = p.split(":")
            tasks.append(test_proxy(host, int(port)))
        except ValueError:
            continue

    results = []
    sem = asyncio.Semaphore(concurrency)

    async def limited(coro):
        async with sem:
            r = await coro
            if r:
                results.append(r)

    await asyncio.gather(*[limited(t) for t in tasks])
    return sorted(results, key=lambda r: r["latency_ms"])


async def refresh_pool():
    global pool
    raw = await fetch_proxies()
    if not raw:
        return
    working = await test_batch(raw, concurrency=100)
    if working:
        pool = working
        _save_pool()
        _restart_tinyproxy()
        log.info(f"pool_refreshed: {len(working)} proxies, best={working[0]['latency_ms']}ms")
    else:
        log.warning("no_working_proxies")


def _save_pool():
    POOL_FILE.parent.mkdir(parents=True, exist_ok=True)
    POOL_FILE.write_text(json.dumps({
        "updated": datetime.now(timezone.utc).isoformat(),
        "count": len(pool),
        "proxies": pool[:200],
    }, indent=2))


async def refresh_loop():
    await refresh_pool()
    while True:
        await asyncio.sleep(1800)
        await refresh_pool()


# ─── Routes ─────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "pool_size": len(pool), "proxy_alive": tinyproxy_proc is not None and tinyproxy_proc.poll() is None}

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
    p = random.choice(pool[:30])
    return {"proxy": f"{p['protocol']}://{p['host']}:{p['port']}", "latency_ms": p["latency_ms"]}


@app.on_event("startup")
async def startup():
    if POOL_FILE.exists():
        data = json.loads(POOL_FILE.read_text())
        global pool
        pool = data.get("proxies", [])
        log.info(f"loaded_pool: {len(pool)} proxies")
    _start_tinyproxy()
    asyncio.create_task(refresh_loop())
    log.info("rotator_started")

@app.on_event("shutdown")
async def shutdown():
    if tinyproxy_proc:
        tinyproxy_proc.terminate()
