# SESSION_PICKUP.md — Substrate State

> Last updated: 2026-05-17 · Session: reverse proxy consolidation

## Current Status

**3 proxy ports, all services healthy.**

### Running (via reverse proxies)
- **Core** (:8080) — 11 services, nginx routes / → api_gateway, /inference/ → inference_gateway
- **Site** (:8082) — Astro static, 21 pages
- **DSS** (:8083) — 12 services, nginx routes /dss/{api,search,crawl,warehouse,vectors,agent,gateway}/
- searxng (:8888) — external meta-search

### Ready (not running)
- **light** (:8084) — DSS light stack
- **test** (:8085) — DSS test stack

### Reverse Proxy Architecture (NEW — eb737de)
- One nginx per stack. All internal service ports removed.
- Docs: `docs/architecture/reverse-proxy.md`
- Port-map updated: `docs/architecture/port-map.md`

## Quick Health

```bash
curl localhost:8080/health              # core nginx
curl localhost:8080/inference/health    # inference through proxy
curl localhost:8083/health              # dss nginx
curl localhost:8083/dss/api/health      # web-api through proxy
curl localhost:8082/                    # site
```

## Git
- Latest: `eb737de feat: reverse proxy consolidation — one port per stack`
- Pushed to origin/main
- Dirty: `services/proxy-rotator/data/proxy-pool.json` (runtime data — not committed)

## Files Changed This Session
| File | Change |
|---|---|
| `infra/docker-compose.core.yml` | Removed inference_gateway port exposure |
| `infra/nginx/nginx.conf` | Added /inference/ route + /health |
| `services/DeepSearchStack/infra/docker-compose.dss.yml` | Added nginx, stripped 7 ports |
| `services/DeepSearchStack/infra/docker-compose.light.yml` | Added nginx, stripped 3 ports |
| `services/DeepSearchStack/infra/docker-compose.test.yml` | Added nginx, stripped 4 ports |
| `services/DeepSearchStack/infra/nginx/nginx.conf` | NEW — DSS reverse proxy config |
| `docs/architecture/reverse-proxy.md` | NEW — architecture doc |
| `docs/architecture/port-map.md` | Updated for proxy-only exposure |
