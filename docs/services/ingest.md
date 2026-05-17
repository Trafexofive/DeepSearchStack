# Ingest (port 8008)

> **Status**: ✅ Working · **Dependencies**: crawler (DSS), blog_generator

## Purpose
RSS/Atom feed watcher with auto-generation. Polls feeds on interval, detects new entries by GUID, extracts full content via DSS crawler, generates researched blog posts, and stores drafts for human review.

## Pipeline
```
Feed poll → GUID dedup → Crawler extraction → Blog generation → MDX draft
```

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | `{"status":"ok","feeds":N,"drafts":M}` |
| GET | `/feeds` | List configured feeds |
| POST | `/feeds` | Add a feed |
| DELETE | `/feeds/{id}` | Remove a feed |
| POST | `/poll` | Force immediate poll |
| GET | `/drafts` | List generated drafts |

## Configured Feeds
Currently 3 arXiv feeds:
- `cs.AI` — Artificial Intelligence
- `cs.PL` — Programming Languages
- `cs.SE` — Software Engineering

## Draft Storage
Drafts written to `services/ingest/volumes/drafts/*.mdx` with YAML frontmatter:
```yaml
---
title: "Paper Title"
source: "arXiv:XXXX.XXXXX"
date: "2026-05-13"
generator: "ingest/0.1.0"
---
```

## Feed Config (YAML)
```yaml
feeds:
  - url: "https://arxiv.org/rss/cs.AI"
    interval: 3600
    category: "research"
    tags: ["ai", "arxiv"]
```

## Docker
```bash
make up core/ingest
```

## E2E Test
```bash
curl -s http://localhost:8008/health | python3 -m json.tool
curl -s http://localhost:8008/feeds | python3 -m json.tool

# Force poll
curl -s -X POST http://localhost:8008/poll | python3 -m json.tool
```
