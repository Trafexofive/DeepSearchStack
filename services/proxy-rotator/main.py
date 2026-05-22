"""proxy-rotator — Tor-backed rotating HTTP proxy for Substrate.

Architecture:
  tor (:9050)        → SOCKS5 to internet (rotating circuits, new IP every 10 min)
  privoxy (:8118)    → HTTP proxy → forwards to tor:9050
  tinyproxy (:8888)  → HTTP proxy → upstreams through privoxy:8118

Services use proxy-rotator:8888 as their HTTP_PROXY. All outbound traffic routes
through Tor for IP diversity and scrape-block avoidance.

Also fetches free HTTP proxies as a secondary pool (used when Tor is slow).
"""

import asyncio
import json
import logging
import os
import random
import re
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, Query

logging.basicConfig(level=logging.INFO, format="%(asctime)s [rotator] %(message)s")
log = logging.getLogger("proxy-rotator")

POOL_FILE = Path(os.environ.get("POOL_FILE", "/app/volumes/data/proxy-pool.json"))
TOR_DATA = Path("/tmp/tor")
TINYPROXY_BIN = os.environ.get("TINYPROXY_BIN", "tinyproxy")
PRIVOXY_BIN = os.environ.get("PRIVOXY_BIN", "privoxy")
TOR_BIN = os.environ.get("TOR_BIN", "tor")

CONFIG_PATH = Path("/app/tinyproxy.conf")
PRIVOXY_CONF = Path("/app/privoxy.conf")
TOR_CONF = Path("/app/torrc")

app = FastAPI(title="proxy-rotator", version="2.0.0")

pool: list[dict] = []
free_pool: list[dict] = []
tor_proc: subprocess.Popen | None = None
privoxy_proc: subprocess.Popen | None = None
tinyproxy_proc: subprocess.Popen | None = None

# ─── Tor ─────────────────────────────────────────────────────

def _write_tor_config():
    """Minimal Tor config — SOCKS5 on 9050, no exit policy restrictions."""
    TOR_DATA.mkdir(parents=True, exist_ok=True)
    TOR_CONF.write_text(f"""SOCKSPort 9050
SOCKSPolicy accept 0.0.0.0/0
Log notice stdout
DataDirectory {TOR_DATA}
ControlPort 9051
CookieAuthentication 0
# Rotate circuits every 10 minutes for IP diversity
MaxCircuitDirtiness 600
NewCircuitPeriod 30
""")


def _start_tor():
    global tor_proc
    _write_tor_config()
    tor_proc = subprocess.Popen(
        [TOR_BIN, "-f", str(TOR_CONF)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True,
    )
    log.info("tor_started")
    # Monitor tor output for bootstrap completion
    asyncio.ensure_future(_monitor_tor())


async def _monitor_tor():
    """Watch tor stdout for bootstrap completion."""
    if not tor_proc or not tor_proc.stdout:
        return
    loop = asyncio.get_event_loop()
    while tor_proc and tor_proc.poll() is None:
        line = await loop.run_in_executor(None, tor_proc.stdout.readline)
        if not line:
            break
        if "Bootstrapped 100%" in line:
            log.info("tor_bootstrapped")


def _stop_tor():
    global tor_proc
    if tor_proc:
        tor_proc.terminate()
        try:
            tor_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            tor_proc.kill()
        tor_proc = None


# ─── Privoxy ──────────────────────────────────────────────────

def _write_privoxy_config():
    PRIVOXY_CONF.write_text("""listen-address 0.0.0.0:8118
forward-socks5 / 127.0.0.1:9050 .
# Don't log requests
logfile /dev/null
# Accept connections from Docker networks
permit-access 0.0.0.0/0
# Disable all filtering
toggle 0
enable-edit-actions 0
enforce-blocks 0
buffer-limit 4096
keep-alive-timeout 300
default-server-timeout 60
connection-sharing 1
""")


def _start_privoxy():
    global privoxy_proc
    _write_privoxy_config()
    privoxy_proc = subprocess.Popen(
        [PRIVOXY_BIN, "--no-daemon", str(PRIVOXY_CONF)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    log.info("privoxy_started:8118")


def _stop_privoxy():
    global privoxy_proc
    if privoxy_proc:
        privoxy_proc.terminate()
        try:
            privoxy_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            privoxy_proc.kill()
        privoxy_proc = None


# ─── Tinyproxy ────────────────────────────────────────────────

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


def _write_tinyproxy_config(upstream_host: str = "127.0.0.1", upstream_port: int = 8118):
    """Tinyproxy config chaining through privoxy (default) or direct proxy."""
    config = _base_config()
    if upstream_host and upstream_port:
        config += f"Upstream http {upstream_host}:{upstream_port}\n"
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(config)


def _start_tinyproxy():
    global tinyproxy_proc
    # Default: chain through privoxy → tor
    _write_tinyproxy_config("127.0.0.1", 8118)
    tinyproxy_proc = subprocess.Popen(
        [TINYPROXY_BIN, "-d", "-c", str(CONFIG_PATH)],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    log.info("tinyproxy_started:8888 → privoxy:8118 → tor:9050")


def _restart_tinyproxy():
    global tinyproxy_proc
    if tinyproxy_proc:
        tinyproxy_proc.send_signal(signal.SIGTERM)
        try:
            tinyproxy_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            tinyproxy_proc.kill()
        tinyproxy_proc = None
    _start_tinyproxy()


# ─── Free Proxy Pool (secondary) ──────────────────────────────

PROXY_SOURCES = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-http.txt",
    "https://raw.githubusercontent.com/jetkai/proxy-list/main/online-proxies/txt/proxies-https.txt",
    "https://raw.githubusercontent.com/roosterkid/openproxylist/main/HTTPS_RAW.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=all&anonymity=all",
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=https&timeout=5000&country=all&ssl=all&anonymity=all",
]


async def fetch_free_proxies() -> list[str]:
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
    return list(found)[:500]


async def test_proxy(host: str, port: int, protocol: str = "http") -> dict | None:
    proxy_url = f"{protocol}://{host}:{port}"
    try:
        t0 = time.monotonic()
        async with httpx.AsyncClient(proxy=proxy_url, timeout=5.0) as client:
            resp = await client.get("http://httpbin.org/ip")
            if resp.status_code < 500:
                return {
                    "host": host, "port": port, "protocol": protocol,
                    "latency_ms": int((time.monotonic() - t0) * 1000),
                }
    except Exception:
        pass
    return None


async def test_batch(proxies: list[str], concurrency: int = 50) -> list[dict]:
    sem = asyncio.Semaphore(concurrency)
    results = []

    async def limited(coro):
        async with sem:
            r = await coro
            if r:
                results.append(r)

    tasks = []
    for p in proxies:
        try:
            host, port = p.split(":")
            tasks.append(test_proxy(host, int(port)))
        except ValueError:
            continue

    await asyncio.gather(*[limited(t) for t in tasks])
    return sorted(results, key=lambda r: r["latency_ms"])


async def refresh_free_pool():
    global free_pool
    raw = await fetch_free_proxies()
    if not raw:
        return
    working = await test_batch(raw, concurrency=50)
    if working:
        free_pool = working
        _save_pool()
        log.info(f"free_pool: {len(working)} working proxies, best={working[0]['latency_ms']}ms")


def _save_pool():
    POOL_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Merge tor status + free pool
    combined = [
        {"host": "tor", "port": 9050, "protocol": "socks5", "latency_ms": 0, "type": "tor"},
    ]
    combined.extend(free_pool[:50])
    POOL_FILE.write_text(json.dumps({
        "updated": datetime.now(timezone.utc).isoformat(),
        "count": len(combined),
        "proxies": combined,
    }, indent=2))


async def pool_maintenance_loop():
    """Periodic free proxy refresh."""
    await asyncio.sleep(60)  # Let Tor bootstrap first
    while True:
        try:
            await refresh_free_pool()
        except Exception as e:
            log.warning(f"free_pool_refresh_error: {e}")
        await asyncio.sleep(1800)


# ─── Routes ───────────────────────────────────────────────────

@app.get("/health")
async def health():
    tor_alive = tor_proc is not None and tor_proc.poll() is None
    privoxy_alive = privoxy_proc is not None and privoxy_proc.poll() is None
    tinyproxy_alive = tinyproxy_proc is not None and tinyproxy_proc.poll() is None
    return {
        "status": "ok",
        "version": "2.0.0",
        "tor": tor_alive,
        "privoxy": privoxy_alive,
        "tinyproxy": tinyproxy_alive,
        "free_pool_size": len(free_pool),
        "proxy_port": 8888,
    }


@app.get("/pool")
async def get_pool(limit: int = Query(default=10, ge=1, le=100)):
    combined = [{"host": "tor", "port": 9050, "protocol": "socks5", "latency_ms": 0, "type": "tor"}]
    combined.extend(free_pool[:limit - 1])
    return {"count": len(combined), "proxies": combined}


@app.post("/refresh")
async def trigger_refresh():
    asyncio.create_task(refresh_free_pool())
    return {"status": "refreshing"}


@app.get("/random")
async def random_proxy():
    """Return a random working proxy. Tor is always available."""
    proxies = [{"proxy": "socks5://127.0.0.1:9050", "type": "tor", "latency_ms": 0}]
    if free_pool:
        p = random.choice(free_pool[:30])
        proxies.append({"proxy": f"{p['protocol']}://{p['host']}:{p['port']}", "type": "free", "latency_ms": p["latency_ms"]})
    return {"proxies": proxies, "recommended": proxies[0]["proxy"]}


@app.get("/tor/status")
async def tor_status():
    return {
        "running": tor_proc is not None and tor_proc.poll() is None,
        "socks_port": 9050,
        "http_via_privoxy": 8118,
        "http_proxy_url": "http://proxy-rotator:8888",
    }


# ─── Lifecycle ───────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    log.info("proxy_rotator_v2_starting")
    _start_tor()
    # Give Tor a moment to create its socket, then start privoxy
    await asyncio.sleep(2)
    _start_privoxy()
    await asyncio.sleep(1)
    _start_tinyproxy()
    # Load saved free pool if exists
    if POOL_FILE.exists():
        try:
            data = json.loads(POOL_FILE.read_text())
            global free_pool
            saved = data.get("proxies", [])
            free_pool = [p for p in saved if p.get("type") != "tor"]
            log.info(f"loaded_free_pool: {len(free_pool)} proxies")
        except Exception:
            pass
    asyncio.create_task(pool_maintenance_loop())
    log.info("proxy_rotator_ready — :8888 (HTTP) :8118 (privoxy) :9050 (tor SOCKS5)")


@app.on_event("shutdown")
async def shutdown():
    _stop_tinyproxy()
    _stop_privoxy()
    _stop_tor()
    log.info("proxy_rotator_stopped")
