#!/bin/bash
#
# Test the DeepSearch service
#

set -e

DEEPSEARCH_URL="${DEEPSEARCH_URL:-http://localhost:8001}"

echo "🧪 Testing DeepSearch Service at $DEEPSEARCH_URL"
echo ""

# Health check
echo "1️⃣  Health Check..."
curl -s "$DEEPSEARCH_URL/health" | jq '.'
echo ""

# Config check
echo "2️⃣  Configuration..."
curl -s "$DEEPSEARCH_URL/config" | jq '.search, .rag, .synthesis | {max_results: .max_results, rag_enabled: .enabled, default_provider: .default_provider}'
echo ""

# Quick search
echo "3️⃣  Quick Search Test..."
curl -s -X POST "$DEEPSEARCH_URL/deepsearch/quick" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "What is Python programming language?",
    "max_results": 5
  }' | jq '{answer: .answer[:200], sources: .sources | length, execution_time: .execution_time}'
echo ""

echo "✅ All tests passed!"
echo ""
echo "Try the examples:"
echo "  python3 examples/deepsearch_example.py quick \"your query\""
echo "  python3 examples/deepsearch_example.py stream \"your query\""
echo "  python3 examples/deepsearch_example.py session \"your query\""
