# yt-lab — YouTube Automation Stack

> Status: working · Version: 0.2.0 · Dependencies: yt-extractor, inference-gateway, knowledge-warehouse, humanizer (optional)

Decoupled into two services following the DSS stack pattern:

```
services/yt-lab/
├── docker-compose.yml           ← stack compose (binds both services)
├── services/
│   ├── yt-extractor/            ← yt-dlp + ffmpeg, host networking
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   └── app/main.py          ← GET /video, POST /channel/list
│   └── yt-lab/                  ← orchestration (host networking)
│       ├── Dockerfile
│       ├── requirements.txt
│       └── app/main.py          ← summarize, crossref, ingest, watch
├── sdk/
│   └── client.py                ← typed async client
├── volumes/data/                ← persistent watch state
└── README.md
```

## Architecture

```
yt-extractor (:8020, host-net)
  └── yt-dlp → video metadata + transcript extraction

yt-lab (:8021, host-net)
  ├── yt-extractor (:8020)          → extraction
  ├── inference-gateway (:8005)     → LLM summaries
  ├── knowledge-warehouse (:8009)   → transcript storage
  └── humanizer (:8013, optional)   → summary humanization
```

Both services use host networking because YouTube blocks datacenter IPs. The separation is logical — extractor handles all yt-dlp/ffmpeg heavy lifting, lab handles orchestration.

## Quick Start

```bash
# Boot the stack
make up yt-lab

# Or directly
cd services/yt-lab && docker compose up -d

# Health
curl -s localhost:8020/health  # extractor
curl -s localhost:8021/health  # lab

# Extract video metadata
curl "localhost:8020/video?url=https://www.youtube.com/watch?v=..."

# Summarize (via lab)
curl -X POST localhost:8021/videos/summarize \
  -H 'Content-Type: application/json' \
  -d '{"video_url":"https://www.youtube.com/watch?v=...", "style":"tl;dr", "humanize":true}'
```

## Endpoints

### yt-extractor (:8020)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service health |
| GET | `/video?url=...` | Extract metadata + transcript |
| POST | `/channel/list` | List video URLs from channel |

### yt-lab (:8021)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service health + deps |
| GET | `/videos/metadata?video_url=...` | Proxy to extractor |
| POST | `/videos/ingest` | Single video → warehouse |
| POST | `/videos/summarize` | Extract → LLM summary (optional humanize) |
| POST | `/videos/crossref` | Cross-reference with warehouse |
| POST | `/channels/ingest` | Bulk channel ingest |
| POST | `/channels/watch` | Start monitoring |
| GET | `/channels/watching` | List watched channels |

## SDK

```python
from ytlab_client import YtLabClient

async with YtLabClient() as yt:
    result = await yt.summarize("https://youtube.com/watch?v=...", style="tl;dr")
    print(result.summary)

    ingest = await yt.ingest_channel("https://youtube.com/@Fireship", limit=10)
    print(f"{ingest.videos_ingested}/{ingest.videos_found} videos ingested")
```

## Configuration

| Env var | Default | Service |
|---------|---------|---------|
| `YT_EXTRACTOR_PORT` | `8020` | extractor |
| `YT_LAB_PORT` | `8021` | lab |
| `EXTRACTOR_URL` | `http://localhost:8020` | lab |
| `WAREHOUSE_URL` | `http://localhost:8009` | lab |
| `INFERENCE_URL` | `http://localhost:8005/v1/chat/completions` | lab |
| `HUMANIZER_URL` | `http://localhost:8013` | lab |
| `YTDLP_PATH` | `yt-dlp` | extractor |

## Compared to v0.1 (monolith)

| Aspect | v0.1 | v0.2 |
|--------|------|------|
| Structure | Single service in `app/main.py` | Two services in `services/{name}/` |
| Registry | In `infra/docker-compose.core.yml` | Own stack `services/yt-lab/docker-compose.yml` |
| Extraction | Inline yt-dlp calls | Separate yt-extractor service |
| Humanizer | Not integrated | Optional: `humanize: true` on summarize/ingest |
| SDK | None | `sdk/client.py` with typed client |
| Discovery | `make up core` | `make up yt-lab` (stack auto-discovery) |
