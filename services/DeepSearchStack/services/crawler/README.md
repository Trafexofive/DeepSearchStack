# Getting Started with the Crawler Service

## Prerequisites

Make sure you have the DeepSearchStack up and running:

```bash
make up
```

The crawler service will be available at `http://localhost:8003`.

## Quick Start

1. **Check service health:**
   ```bash
   curl http://localhost:8003/health
   ```

2. **Crawl a webpage:**
   ```bash
   curl -X POST http://localhost:8003/crawl \
     -H "Content-Type: application/json" \
     -d '{
       "url": "https://example.com",
       "extraction_strategy": "llm"
     }'
   ```

3. **Run the example script:**
   ```bash
   python3 examples/crawler_example.py
   ```

## Integration with Other Services

The crawler service can be easily integrated with other services in the stack:

```python
import requests

# In your search-agent or other service
def fetch_and_process(url):
    response = requests.post('http://crawler:8000/crawl', 
                           json={
                               'url': url,
                               'extraction_strategy': 'llm'
                           })
    
    if response.status_code == 200:
        data = response.json()
        if data['success']:
            # Process the crawled content
            return data['content']
    
    return None
```

## Next Steps

1. Check out the full API documentation in `docs/crawler-guide.md`
2. Review the example scripts in the `examples/` directory
3. Run the test suite: `make test-crawler`