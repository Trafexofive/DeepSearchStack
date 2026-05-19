# trend-engine — Viral Trend Analysis Engine

> Status: working · Port: 8021 · Dependencies: yt-lab (:8020), knowledge-warehouse (:8009), inference_gateway (:8005)
> Last tuned: 2026-05-18 — live-tested with @Fireship (13 videos), 2 HOT detected

## Purpose

Real-time viral trend detection and scoring for YouTube content. Computes view velocity, engagement ratios, outlier scores, and composite viral coefficients. Surfaces hot content, trending topics, and channel-level trend trajectories.

## Architecture

```
trend-engine (:8021, host network)
├── yt-lab (:8020)              ← GET /videos/metadata (view_count, like_count, upload_date)
├── knowledge-warehouse (:8009) ← content search + historical data
└── inference_gateway (:8005)   ← LLM-powered trend insights
```

> **Network note:** trend-engine and yt-lab both use host networking. All internal URLs
> are `http://localhost:{port}`. This is required because Docker bridge containers
> can't reach host-bound ports on this machine.

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

## Tuning Notes

### Engagement Ratio (currently 0.0 in most cases)
yt-dlp's `--write-info-json` doesn't reliably include `like_count`/`comment_count`
in the default extract. These fields require `--parse-metadata` or the YouTube API.
To fix: add `like_count`/`comment_count` extraction via yt-dlp parse flags, or
switch to YouTube Data API v3 for engagement data.

### Topic Extraction
Current implementation is keyword-based with bigram extraction from titles.
Noise issues: stopword bigrams leak through ("can't believe", "just hijacked").
To fix: LLM-powered topic extraction on the top-N videos per scan, or use a
proper NLP pipeline (spaCy noun phrase extraction).

### Channel Baseline
Outlier scores max out at 5.0σ for all videos when computed from small samples
(<20 videos per channel). The baseline needs a minimum of ~30 videos for
statistical significance. Consider caching baselines in the trend data store.

### Performance
Metadata enrichment runs 5 concurrent yt-dlp calls via semaphore. A 13-video
channel pulse takes ~2-3 minutes. For production: cache metadata in warehouse
or trend-engine's own data store. Consider adding `view_count`, `like_count`,
`upload_date` columns to the warehouse schema so bulk scans don't need yt-dlp.

### Score Calibration
The model currently scores known viral Fireship videos at ~20-46 (warm-hot).
Megaviral (80+) requires 10K+ views/hr with high engagement and youth factor.
Calibrate against known viral benchmarks: MrBeast, trending tab, breakouts.

### yt-lab Dependency
Trend-engine depends on the new `GET /videos/metadata?video_url=` endpoint
added to yt-lab (commit `bb4d9eb`). Without it, view counts come back as 0
and all scores flatline.

### Network Topology
Both yt-lab and trend-engine use `network_mode: host` because:
1. yt-lab needs host IP to avoid YouTube's datacenter blocking
2. trend-engine needs host network to reach yt-lab via localhost
3. Docker bridge containers on this machine cannot reach host-bound ports
   (iptables/firewalld restriction)

Warehouse (:8009) and inference (:8005) must be port-mapped to host for the
same reason when trend-engine is on host network.
