# Reverse Proxy Architecture

> Status: deployed · Updated: 2026-05-17 · Stacks: core, dss, light, test, site

## Philosophy

One proxy per stack. Services communicate internally via Docker DNS. No direct host port exposure — everything routes through a stack-specific nginx reverse proxy.

## Proxy Map

| Stack | Proxy Port | Config | Routes |
|---|---|---|---|
| **core** | `:8080` | `infra/nginx/nginx.conf` | `/` → api_gateway:8000, `/inference/` → inference_gateway:8005 |
| **dss** | `:8083` | `services/DeepSearchStack/infra/nginx/nginx.conf` | `/dss/{service}/` → {service} |
| **light** | `:8084` | `services/DeepSearchStack/infra/nginx/nginx.conf` (shared) | `/dss/{service}/` → {service} |
| **test** | `:8085` | `services/DeepSearchStack/infra/nginx/nginx.conf` (shared) | `/dss/{service}/` → {service} |
| **site** | `:8082` | `services/site/nginx.conf` | Static Astro site (serves own content + `/api/` proxy to blog_generator) |

Ports are configurable via env vars: `DSS_PORT`, `DSS_LIGHT_PORT`, `DSS_TEST_PORT`, `SITE_PORT`.

## DSS Proxy Routes

All DSS stacks share the same nginx config with path-based routing:

| Path | Upstream | Port |
|---|---|---|
| `/dss/api/` | web-api | 8014 |
| `/dss/search/` | deepsearch | 8001 |
| `/dss/crawl/` | crawler | 8000 |
| `/dss/warehouse/` | knowledge-warehouse | 8009 |
| `/dss/vectors/` | vector-store | 8004 |
| `/dss/agent/` | search-agent | 8013 |
| `/dss/gateway/` | search-gateway | 8002 |

## Nginx Pattern

All proxy configs follow the same pattern:

```nginx
location /prefix/ {
    proxy_pass http://service:port/;      # trailing slash strips prefix
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 120s;              # 300s for LLM endpoints
    proxy_connect_timeout 10s;
    proxy_send_timeout 120s;
}
```

Note: both `location` and `proxy_pass` must end with `/` for proper path stripping. Without the trailing slash on `proxy_pass`, the full original URI is forwarded.

## What's NOT Proxied

Standalone per-service compose files (`services/{name}/docker-compose.yml`) still expose ports directly. These are development conveniences for debugging a single service in isolation. When services run as part of a stack, ports are internal-only.

## Health

Every proxy exposes `/health`:
```bash
curl localhost:8080/health   # core
curl localhost:8083/health   # dss
```
