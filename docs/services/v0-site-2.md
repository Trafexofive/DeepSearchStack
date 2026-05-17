# v0-site-2 — Affiliate Site with Blog Pipeline

> Status: working · Dependencies: inference-gateway, blog_generator, redis

## Purpose

Astro 4.16 static site for v0 by Vercel affiliate content. Includes auto-generated blog content via the blog_generator API, served through Docker via the substrate Makefile.

## Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                         v0-site-2 Stack                            │
│                                                                    │
│  ┌─────────────┐     ┌──────────────────┐     ┌────────────────┐  │
│  │  Scripts    │────▶│ blog_generator   │────▶│ inference-     │  │
│  │  (SDK/CLI)  │     │ :8006            │     │ gateway :8005  │  │
│  └──────┬──────┘     └────────┬─────────┘     └───────┬────────┘  │
│         │                     │                       │          │
│         │ writes .md          │                       │ DeepSeek │
│         ▼                     │                       │ API      │
│  ┌──────────────┐             │                                 │
│  │ src/content/ │             │                                 │
│  │ blog/*.md    │             │                                 │
│  └──────┬───────┘             │                                 │
│         │                     │                                 │
│         ▼                     │                                 │
│  ┌──────────────┐             │                                 │
│  │ astro build  │             │                                 │
│  │ → dist/      │             │                                 │
│  └──────┬───────┘             │                                 │
│         │                     │                                 │
│         ▼                     │                                 │
│  ┌──────────────┐             │                                 │
│  │ nginx :8081  │             │                                 │
│  │ (Docker)     │             │                                 │
│  └──────────────┘             │                                 │
└────────────────────────────────────────────────────────────────────┘
```

## Endpoints

| Port | Service | Description |
|---|---|---|
| `:8081` | nginx (prod) | Static site with gzip + caching |
| `:4321` | astro dev | Hot-reload dev server (frontend-dev profile) |

### Blog Routes

| Path | Slug | Category |
|---|---|---|
| `/blog/` | — | Blog index (dynamic listing) |
| `/blog/getting-started-with-v0/` | getting-started-with-v0 | tutorials |
| `/blog/v0-vs-cursor-ai/` | v0-vs-cursor-ai | reviews |
| `/blog/v0-github-integration-guide/` | v0-github-integration-guide | guides |

## Stack Commands

```bash
make build v0-site-2        # Build the Docker image
make up v0-site-2           # Start nginx serving static dist
make up v0-site-2/frontend-dev  # Start astro dev server (hot reload)
make logs v0-site-2         # Follow nginx logs
make status v0-site-2       # Container status
make down v0-site-2         # Stop and remove
make health v0-site-2       # Health check
```

### Blog Generation Pipeline

```bash
cd services/v0-site-2

# Python SDK
python scripts/pipeline_generate_blogs.py --dry-run
python scripts/pipeline_generate_blogs.py --topics 3

# Bash script
./scripts/generate-blogs.sh --dry-run
./scripts/generate-blogs.sh
```

## Files

```
services/v0-site-2/
├── docker-compose.yml              ← Stack entrypoint (Makefile discoverable)
├── scripts/
│   ├── blog_generator_client.py    ← Python SDK for blog_generator API
│   ├── pipeline_generate_blogs.py  ← Pipeline: generate → frontmatter → .md
│   └── generate-blogs.sh           ← Bash variant
├── services/frontend-service/
│   ├── Dockerfile                  ← Multi-stage: deps → dev → builder → nginx
│   ├── nginx.conf                  ← gzip, caching, security headers
│   ├── docker-compose.yml          ← Standalone compose
│   └── src/content/blog/           ← Generated .md files
└── Makefile                        ← (stub, v0-site-2 project-level)
```

## Generation Cost Reference

| Model | Prompt $/M | Completion $/M | Sample (2K blog) |
|---|---|---|---|
| deepseek-chat | $0.27 | $1.10 | ~$0.002 |
| deepseek-reasoner | $0.55 | $2.19 | ~$0.004 |

## How to Test

```bash
# 1. Build and start
make build v0-site-2 && make up v0-site-2

# 2. Verify pages
curl -so /dev/null -w "%{http_code}" http://localhost:8081/blog/
curl -so /dev/null -w "%{http_code}" http://localhost:8081/blog/getting-started-with-v0/

# 3. Generate new blogs
cd services/v0-site-2
python scripts/pipeline_generate_blogs.py

# 4. Rebuild site (Docker picks up new .md files)
make build v0-site-2 && make up v0-site-2
```

## Known Issues

- `rss.xml.ts` endpoint returns `EndpointDidNotReturnAResponse` — Astro endpoint missing explicit `return Response`. Does not block build.
- `base: '/v0-site-2/'` in `astro.config.mjs` is for GitHub Pages — Docker build overrides to `/` via build arg.
- Blog index was hardcoded to 4 slugs — patched to use `getCollection('blog')`.
