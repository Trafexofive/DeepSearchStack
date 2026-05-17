# yt-lab — YouTube Automation Service

Fetches YouTube video transcripts, generates LLM summaries, cross-references with warehouse content, and monitors channels for new videos.

## Quick Start

```bash
# Ingest a channel's videos into the warehouse
curl -X POST http://localhost:8080/api/yt-lab/channels/ingest \
  -H 'Content-Type: application/json' \
  -d '{"channel_url":"https://www.youtube.com/@Fireship","limit":10}'

# Summarize a video
curl -X POST http://localhost:8080/api/yt-lab/videos/summarize \
  -H 'Content-Type: application/json' \
  -d '{"video_url":"https://www.youtube.com/watch?v=dQw4w9WgXcQ","style":"bullet"}'

# Cross-reference with warehouse
curl -X POST http://localhost:8080/api/yt-lab/videos/crossref \
  -H 'Content-Type: application/json' \
  -d '{"video_url":"https://www.youtube.com/watch?v=..."}'
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/channels/ingest` | Ingest channel videos (transcripts → warehouse) |
| POST | `/channels/watch` | Start background monitoring of a channel |
| GET | `/channels/watching` | List watched channels |
| POST | `/videos/summarize` | Generate summary via inference_gateway |
| POST | `/videos/crossref` | Find related warehouse content |
| POST | `/videos/ingest` | Single video ingest |
| GET | `/health` | Health + watching count |

## Summarize Styles

| Style | Output |
|-------|--------|
| `bullet` | 5-7 bullet points |
| `paragraph` | 2-paragraph summary |
| `tl;dr` | Single sentence + 3 takeaways |

## Architecture

```
yt-lab (host networking, :8020)
  ├── yt-dlp → extract transcripts + metadata
  ├── inference_gateway:8005 → LLM summaries
  └── warehouse:8009 → transcript storage
```

**Host networking** is required because YouTube blocks Docker data center IPs. The `network_mode: host` in docker-compose gives yt-lab the host's residential IP.

## Transcription

Transcription is abstracted behind a single `_transcribe()` function. Currently relies on YouTube's built-in captions. To add Whisper or another backend, implement `_transcribe()` without changing the rest of the service.

## Building

```bash
make build core/yt-lab
make up core/yt-lab
```
