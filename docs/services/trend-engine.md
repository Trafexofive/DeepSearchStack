# trend-engine — Viral Trend Analysis Engine

> Status: working · Port: 8021 · Dependencies: yt-lab, knowledge-warehouse, inference_gateway

## Purpose

Real-time viral trend detection and scoring for YouTube content. Computes view velocity, engagement ratios, outlier scores, and composite viral coefficients. Surfaces hot content, trending topics, and channel-level trend trajectories.

## Architecture

```
trend-engine (:8021)
├── yt-lab (:8020)           ← video metadata extraction
├── knowledge-warehouse (:8009) ← content search + historical data
└── inference_gateway (:8005)   ← LLM-powered trend insights
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/trends/analyze` | Analyze a single video for viral signals |
| POST | `/trends/scan` | Scan warehouse for trending content (bulk) |
| GET | `/trends/hot` | Current hot/trending content (cached or live) |
| GET | `/trends/topics` | Trending topics with velocity scores |
| POST | `/trends/compare` | Compare viral signals across 2–10 videos |
| GET | `/trends/signals/{id}` | Detailed signal breakdown for a video |
| POST | `/trends/channel-pulse` | Channel-wide trend trajectory analysis |
| GET | `/health` | Health check |

## Viral Scoring Model

Six signals combine into a 0–100 composite score:

| Signal | Weight | Description |
|--------|--------|-------------|
| View Velocity | 40% | Views per hour since upload (normalized to 10K/hr max) |
| Engagement Ratio | 15% | (Likes + 2×Comments) / Views — comments weighted 2× |
| Acceleration | 25% | Youth factor × velocity — penalizes old content |
| Outlier Score | 20% | Stddevs above channel baseline (or global default) |

### Viral Tiers

| Score | Tier | Meaning |
|-------|------|---------|
| 80–100 | megaviral | Breakout hit — 10K+ views/hr, high engagement |
| 60–79 | viral | Strong signals — likely building momentum |
| 35–59 | hot | Above average — worth watching |
| 15–34 | warm | Normal performance |
| 0–14 | cold | Low engagement or old content |

### Momentum

- **rising** — Young video with high velocity (>10K/hr) or early traction
- **stable** — Consistent velocity (1K–10K/hr)
- **falling** — Low velocity, older content
- **cold** — Negligible velocity (<10/hr)

## Quick Start

```bash
# Analyze a video for viral potential
curl -X POST http://localhost:8021/trends/analyze \
  -H 'Content-Type: application/json' \
  -d '{"video_url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'

# Scan warehouse for trending content
curl -X POST http://localhost:8021/trends/scan \
  -H 'Content-Type: application/json' \
  -d '{"max_videos":30,"since_hours":72,"min_views":1000}'

# Get hot content
curl http://localhost:8021/trends/hot?limit=10 | python3 -m json.tool

# Compare videos
curl -X POST http://localhost:8021/trends/compare \
  -H 'Content-Type: application/json' \
  -d '{"video_urls":["https://...","https://..."]}'

# Channel pulse
curl -X POST http://localhost:8021/trends/channel-pulse \
  -H 'Content-Type: application/json' \
  -d '{"channel_url":"https://www.youtube.com/@Fireship","limit":20}'
```

## via nginx (core stack)

When booted in the core stack:

```bash
curl -X POST http://localhost:8080/trends/analyze \
  -H 'Content-Type: application/json' \
  -d '{"video_url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ"}'
```

## Data Persistence

Trend signals are saved to `volumes/data/trends-{timestamp}.json` on every `/trends/analyze` and `/trends/scan` call. Historical data enables trend-line queries via `/trends/hot` and `/trends/topics`.

## Building

```bash
make build core/trend-engine
make up core/trend-engine
```

Or as a standalone stack with yt-lab:

```bash
make build viral-trend
make up viral-trend
```
