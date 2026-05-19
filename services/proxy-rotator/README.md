# proxy-rotator v2 — Tor-Backed Rotating HTTP Proxy

Embeds tor + privoxy + tinyproxy in a single container. All outbound traffic routes through Tor with automatic circuit rotation (new exit IP every 10 minutes). Also maintains a secondary pool of free HTTP proxies.

## Architecture

```
proxy-rotator (single container, :8888)
  ├── tor (:9050)         → SOCKS5 to internet (rotating circuits)
  ├── privoxy (:8118)     → HTTP→SOCKS5 bridge, forwards to tor
  └── tinyproxy (:8888)   → HTTP forward proxy, upstreams through privoxy
```

Services set `HTTP_PROXY=http://proxy-rotator:8888` — all outbound traffic automatically routes through Tor.

## Quick Start

```bash
# Health check
curl http://localhost:8030/health
# {"status":"ok","version":"2.0.0","tor":true,"privoxy":true,"tinyproxy":true,...}

# Test proxy chain
curl -x http://localhost:8888 http://httpbin.org/ip
# {"origin": "193.189.100.201"}  ← Tor exit node

# View pool (Tor + free proxies)
curl http://localhost:8030/pool?limit=5

# Get random proxy
curl http://localhost:8030/random

# Tor status
curl http://localhost:8030/tor/status
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Tor, privoxy, tinyproxy status + pool size |
| GET | `/pool?limit=` | Combined pool: Tor + working free proxies |
| POST | `/refresh` | Trigger free proxy pool refresh |
| GET | `/random` | Random working proxy (Tor always available) |
| GET | `/tor/status` | Tor circuit status |

## Proxy Ports

| Port | Service | Protocol |
|------|---------|----------|
| 8888 | tinyproxy | HTTP forward proxy (use this) |
| 8118 | privoxy | HTTP proxy → Tor (internal) |
| 9050 | tor | SOCKS5 (internal) |
| 8030 | API | Health/pool management |

## Tor Circuit Rotation

- **MaxCircuitDirtiness: 600s** — New circuit (new exit IP) every 10 minutes
- **NewCircuitPeriod: 30s** — Circuit pre-building for smooth rotation
- Tor data persists in `/tmp/tor` volume for faster restarts

## Using from Docker Services

```yaml
services:
  my-service:
    environment:
      - HTTP_PROXY=http://proxy-rotator:8888
      - HTTPS_PROXY=http://proxy-rotator:8888
    networks:
      - infra_substrate-net  # Must share network with proxy-rotator
```

## Free Proxy Pool

Secondary pool of free HTTP proxies from GitHub sources — refreshed every 30 minutes. Used as fallback when Tor is slow. Tested against httpbin.org/ip for connectivity.

Sources: TheSpeedX, jetkai, roosterkid, monosans, ProxyScrape

## Building

```bash
make build core/proxy-rotator
make up core/proxy-rotator
```
