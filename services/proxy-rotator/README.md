# proxy-rotator — Free Proxy Aggregation + Rotation

Fetches HTTP proxies from 10 free sources, tests them for reliability, and maintains a pool of working proxies. Bundles tinyproxy as a forward proxy that routes through the best available proxy.

## Quick Start

```bash
# Check health + pool size
curl http://localhost:8030/health

# View working proxies
curl http://localhost:8030/pool?limit=5

# Trigger manual refresh
curl -X POST http://localhost:8030/refresh

# Get a random working proxy
curl http://localhost:8030/random
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Pool size, proxy alive status |
| GET | `/pool?limit=` | List working proxies by latency |
| POST | `/refresh` | Trigger manual pool refresh |
| GET | `/random` | Random proxy from top 30 |

## Proxy

Services use `proxy-rotator:8888` as their HTTP proxy. The rotator automatically selects the fastest working proxy and configures tinyproxy to forward through it.

```bash
# From any Docker container
export HTTP_PROXY=http://proxy-rotator:8888
curl http://example.com  # routed through fastest free proxy
```

## Architecture

```
proxy-rotator (:8030 API, :8888 proxy)
  ├── Fetch 10 free proxy list sources
  ├── Test 500 proxies with 100 concurrency (5s timeout)
  ├── Sort by latency, keep top 32
  ├── Write fastest as tinyproxy Upstream
  ├── Restart tinyproxy with new upstream
  └── Refresh every 30 minutes
```

## Proxy Sources

- TheSpeedX PROXY-List (GitHub)
- jetkai proxy-list (GitHub)
- hookzof socks5_list (GitHub)
- roosterkid openproxylist (GitHub)
- monosans proxy-list (GitHub)
- ProxyScrape v2 API
- ProxyLists.net JSON feed

## Limitations

- Free proxies are unstable — pool size fluctuates
- Some proxies strip headers or inject content
- Reddit/Facebook aggressively block known proxy IPs
- Not a SOCKS5 proxy — HTTP only
- Docker source IP still traces back to host (not anonymized)

## Building

```bash
make build core/proxy-rotator
make up core/proxy-rotator
```
