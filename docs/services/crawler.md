# Crawler (port 8000 POC / 8004 test)

> **Status**: POC port — working prototype · **Source**: `services/DeepSearchStack/services/crawler/`

## Purpose
Web scraping microservice powered by crawl4ai. Extracts content from URLs with configurable strategies (markdown, LLM extraction, CSS selectors).

## Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/crawl` | Crawl a URL |
| GET | `/health` | Health check |

## Extraction Strategies

| Strategy | Description |
|---|---|
| `markdown` (default) | Extracts cleaned markdown from page |
| `llm` | Uses LLM to extract structured data |
| `json_css` | CSS selector-based structured extraction |

## Request

```json
{
  "url": "https://example.com/article",
  "extraction_strategy": "markdown"
}
```

## Dependencies

- crawl4ai (AsyncWebCrawler)
- Playwright (browser automation)
- Optional: LLM for extraction strategy

## Quick test

```bash
curl -X POST http://localhost:8000/crawl \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com", "extraction_strategy": "markdown"}'
```

## Files

```
services/DeepSearchStack/services/crawler/
├── main.py           # FastAPI + crawl4ai integration
├── Dockerfile
└── requirements.txt
```
