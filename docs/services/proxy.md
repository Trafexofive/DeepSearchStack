# Proxy — HTTP Forward Proxy

> Status: running · Port: 8888 (internal) · Updated: 2026-05-17

## Purpose
Lightweight HTTP/HTTPS forward proxy for Docker services needing residential-adjacent outbound IPs. Runs tinyproxy on Alpine. Services set `HTTP_PROXY=http://proxy:8888` to route outbound traffic through it.

## Configuration
- Anonymous mode: strips Cookie and Authorization headers
- Via header disabled (doesn't advertise proxy)
- Allows all Docker networks (172.x, 10.x, 192.168.x, localhost)
- Upstream chaining: uncomment `Upstream` in tinyproxy.conf to chain through VPN/WireGuard

## Services Using It
| Service | Reason |
|---|---|
| `crawler` (DSS) | Reddit scraping (IP block evasion) |
| `search-gateway` (DSS) | arXiv, Reddit provider calls |

## Limitations
- Runs in Docker → source IP is still Docker's NAT. For true IP diversity, chain through an external residential proxy via `Upstream` config.
- YouTube: use host networking (`network_mode: host`) for yt-lab instead. YouTube aggressively blocks known DC IPs regardless of proxy.
- Not a SOCKS5 proxy — HTTP only.

## Health
```
docker exec infra-proxy-1 nc -z localhost 8888  # true if running
```
Docker HEALTHCHECK uses the same check every 30s.
