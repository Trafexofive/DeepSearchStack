# Humanizer Service

> Status: working · Version: 0.2.0 · Dependencies: inference-gateway

## Purpose

Two-pass LLM text humanization. Takes AI-generated text → makes it sound human-written. Mission-agnostic: no domain knowledge, only style transformation.

## Architecture

```
POST /humanize       ──→  Pass 1 (humanize prompt)  ──→  Pass 2 (anti-pattern scrub)  ──→  Response + confidence
POST /humanize/batch ──→  Concurrent Pass 1+2 per item
GET  /metrics        ──→  Cumulative token cost & performance stats
```

**Pass 1**: Rewrites text with a humanization system prompt (contractions, varied sentence length, personality injection, anti-pattern avoidance).

**Pass 2**: Scrubs Pass 1 output for remaining AI patterns. If Pass 2 changes <5%, Pass 1 output is used (avoids unnecessary token spend).

**Confidence score**: 0-1 rating of how human the output sounds. Based on anti-pattern hit density, sentence length variance, and Pass 2 application.

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service health, model, version, limit config |
| GET | `/styles` | List available humanization styles |
| GET | `/metrics` | Cumulative token cost, request count, pass2 rate, latency |
| POST | `/humanize` | Humanize a single text (max 16384 chars) |
| POST | `/humanize/batch` | Humanize 1-20 texts concurrently |

### POST /humanize

```json
{
  "text": "It is important to note that the system utilizes a paradigm-shifting architecture...",
  "style": "casual",
  "intensity": 0.7
}
```

Response:
```json
{
  "text": "So the system's got this architecture that's actually pretty clever...",
  "model": "nvidia_nim:zhipuai/glm-4-9b-chat",
  "tokens": 342,
  "pass2_applied": true,
  "confidence": 0.82
}
```

### GET /metrics

```json
{
  "uptime_seconds": 3600.0,
  "total_requests": 47,
  "total_errors": 1,
  "total_tokens": 28410,
  "pass1_tokens": 18200,
  "pass2_tokens": 10210,
  "pass2_rate": 0.62,
  "avg_latency_ms": 1240.5,
  "avg_tokens_per_request": 604.5
}
```

## Styles

| Style | Description |
|-------|-------------|
| `neutral` | Default — natural human prose, no strong stylistic tilt |
| `casual` | Like texting a friend. Slang, contractions, loose structure |
| `professional` | Confident and direct, like a senior engineer. No corporate fluff |
| `blunt` | No pleasantries. Short sentences. Straight to the point |
| `conversational` | Like talking over coffee. Rhetorical questions, personal tone |

### Intensity (0.0–1.0)

- `0.0–0.3`: Barely touched. Subtle contractions and minor smoothing.
- `0.4–0.6`: Moderate. Noticeably human but clean.
- `0.7–1.0`: Aggressive. More fragments, personality, edge.

## Configuration

| Env var | Default | Description |
|---------|---------|-------------|
| `HUMANIZER_PORT` | `8013` | Service port |
| `INFERENCE_URL` | `http://inference_gateway:8005/v1/chat/completions` | Inference gateway URL |
| `HUMANIZER_MODEL` | `nvidia_nim:zhipuai/glm-4-9b-chat` | Model in `provider:model_id` format |
| `HUMANIZER_MAX_INPUT` | `16384` | Max input text length in chars (413 if exceeded) |
| `HUMANIZER_CONFIG_DIR` | `/app/config` | Config directory (anti-patterns.txt) |
| `LOG_LEVEL` | `INFO` | Logging level |

## Anti-patterns (configurable)

The anti-pattern blocklist lives in `config/anti-patterns.txt` — one pattern per line, `#` for comments. Edit it without rebuilding the container; the service hot-reloads on changes (`@lru_cache` invalidated by file mtime).

Categories:
- Structured transitions ("delve into", "firstly/secondly")
- Corporate enthusiasm ("game-changer", "revolutionary", "unleash")
- Hedging/padding ("moreover", "furthermore", "it should be noted")
- Fake empathy ("great question", "I hope this helps")
- Structured list openers ("Here are", "Let me break this down")
- Over-formal phrases ("one must consider", "it can be argued")

## SDK

```python
from humanizer_client import HumanizerClient

async with HumanizerClient("http://localhost:8013") as hz:
    result = await hz.humanize("AI-generated text", style="blunt", intensity=0.8)
    print(result.text, result.confidence)

    # Batch
    batch = await hz.humanize_batch([
        {"text": "First..."},
        {"text": "Second...", "style": "casual"},
    ])

    # Metrics
    m = await hz.metrics()
    print(f"{m.total_tokens} tokens used across {m.total_requests} requests")
```

## CLI

```bash
# Local (direct import, no server needed)
python -m app.cli --text "AI text here" --style blunt
python -m app.cli --file input.txt --style casual --intensity 0.8 --json
python -m app.cli --styles
python -m app.cli --metrics-only

# Remote (against running server)
python -m app.cli --server http://localhost:8013 --health
python -m app.cli --server http://localhost:8013 --text "..." --style casual

# SDK CLI
python sdk/client.py health
python sdk/client.py humanize "AI text" --style blunt
python sdk/client.py metrics
```

## How to test

```bash
# Build
make build core/humanizer

# Boot
make up core/humanizer
sleep 2

# Health
curl -s localhost:8013/health | python3 -m json.tool

# List styles
curl -s localhost:8013/styles | python3 -m json.tool

# Metrics (pre-request)
curl -s localhost:8013/metrics | python3 -m json.tool

# Humanize
curl -s -X POST localhost:8013/humanize \
  -H "Content-Type: application/json" \
  -d '{"text": "It is important to note that the system architecture leverages a microservices paradigm to ensure optimal scalability and fault tolerance.", "style": "casual", "intensity": 0.7}' \
  | python3 -m json.tool

# Oversized input (should return 422 with max_length detail)
curl -s -X POST localhost:8013/humanize \
  -H "Content-Type: application/json" \
  -d "{\"text\": \"$(python3 -c 'print(\"x\" * 20000)')\"}" \
  | python3 -m json.tool
```

## Token cost

With GLM-4-Flash (free via NVIDIA NIM): **$0**. With paid models: roughly 2× the input token count (one inference per pass, plus system prompt overhead). For a 500-token input, expect ~1,200 total tokens across both passes. System prompts are cached — anti-pattern blocklist not resent on each call.
