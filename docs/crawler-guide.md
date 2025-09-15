# Crawler Service with crawl4ai

## Overview

The crawler service is a microservice built using [crawl4ai](https://github.com/unclecode/crawl4ai), an open-source LLM-friendly web crawler and scraper. It provides a simple API for crawling web pages and extracting content that can be used by other services in the DeepSearchStack.

## Features

- Web page crawling with JavaScript rendering support
- Content extraction in various formats (HTML, Markdown, etc.)
- LLM-based content extraction and structuring
- CSS selector-based extraction
- Fast and efficient crawling with browser automation

## API Endpoints

### Health Check
```
GET /health
```
Returns the health status of the crawler service.

### Crawl URL
```
POST /crawl
```

**Request Body:**
```json
{
  "url": "https://example.com",
  "extraction_strategy": "llm", // or "json_css"
  "css_selector": ".content" // Optional, used when extraction_strategy is "json_css"
}
```

**Response:**
```json
{
  "url": "https://example.com",
  "content": "Extracted content...",
  "extracted_data": {}, // Structured data extracted using LLM
  "success": true,
  "error_message": null
}
```

## Usage Examples

### Python Example
```python
import requests

# Crawl a webpage
response = requests.post('http://crawler:8000/crawl', json={
    'url': 'https://example.com',
    'extraction_strategy': 'llm'
})

if response.status_code == 200:
    data = response.json()
    print(data['content'])
```

### Using with curl
```bash
# Health check
curl http://localhost:8003/health

# Crawl a webpage
curl -X POST http://localhost:8003/crawl \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com",
    "extraction_strategy": "llm"
  }'
```

## Integration with DeepSearchStack

The crawler service can be integrated with other services in the stack:

1. **Search Agent**: Can use the crawler to fetch fresh content for queries
2. **Vector Store**: Can send crawled content for indexing
3. **LLM Gateway**: Can process extracted content for summarization or analysis

## Configuration

The crawler service can be configured through environment variables:

- `PORT`: The port the service listens on (default: 8000)

## Development

### Running Locally
```bash
cd services/crawler
pip install -r requirements.txt
playwright install-deps
playwright install chromium
python main.py
```

### Building the Docker Image
```bash
docker build -t crawler-service .
```

### Adding New Features

1. Extend the `CrawlRequest` model in `main.py` for new parameters
2. Add new endpoints as needed
3. Update the Dockerfile if new system dependencies are required

## Troubleshooting

### Common Issues

1. **Playwright browser not found**: Ensure `playwright install` has been run
2. **Memory issues**: The crawler uses browser automation which can be memory-intensive
3. **Timeout errors**: Some websites may take longer to load; adjust timeout settings as needed

### Logs
Check the service logs for debugging information:
```bash
make logs service=crawler
```