# Geo Audit (port 8011)

> **Status**: ✅ Working · **Dependencies**: crawler (DSS), inference-gateway

## Purpose
AI-SEO / GEO (Generative Engine Optimization) content auditor. Scores content for LLM-citability and compares against competitor URLs. Quantifies how likely your content is to be cited by AI assistants.

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/audit/status` | Health + stats |
| POST | `/audit/content` | Score content for LLM-citability |
| POST | `/audit/compare` | Compare against competitor URLs |
| POST | `/audit/llm-citation` | LLM-based citation potential check |

## Score Dimensions
| Dimension | Weight | Description |
|---|---|---|
| Clarity | 20% | Readability, structure |
| Authority | 25% | Citations, expertise signals |
| Freshness | 15% | Recency, temporal relevance |
| Structure | 20% | Headings, lists, tables, schema |
| Citeability | 20% | Quote-worthiness, fact density |

## Content Audit
```bash
curl -s -X POST http://localhost:8011/audit/content \
  -H "Content-Type: application/json" \
  -d '{
    "content": "# My Article\n\nDetailed content...",
    "keyword": "rust async patterns"
  }' | python3 -m json.tool
```

Response:
```json
{
  "overall_score": 72,
  "dimensions": {
    "clarity": 80, "authority": 65, "freshness": 70,
    "structure": 75, "citeability": 70
  },
  "suggestions": [
    "Add structured data (schema.org) for better LLM parsing",
    "Include more external citations to boost authority"
  ],
  "model_used": "deepseek-chat",
  "tokens_used": 1847
}
```

## Compare Mode
```bash
curl -s -X POST http://localhost:8011/audit/compare \
  -H "Content-Type: application/json" \
  -d '{
    "my_content": "# My Article...",
    "competitor_urls": ["https://example.com/similar-article"],
    "keyword": "rust async"
  }' | python3 -m json.tool
```

## Docker
```bash
make up core/geo_audit
```
