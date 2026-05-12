#!/bin/bash
# ======================================================================================
# DeepSearchStack - Search Gateway Provider Test Script v1.0
#
# This script individually tests every search provider configured in the
# search-gateway to ensure each integration is working correctly.
# ======================================================================================

# --- Configuration ---
set -o pipefail
BASE_URL=${BASE_URL:-http://localhost}
# This test talks directly to the search-gateway via the reverse proxy
SEARCH_GATEWAY_URL="${BASE_URL}/gateway"
API_TIMEOUT=45

# --- State & Colors ---
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
FAILURES=0
SUCCESSES=0
TESTS_RUN=0

# --- Main Logic ---
echo -e "\n${YELLOW}▶️  Fetching available search providers from ${SEARCH_GATEWAY_URL}/providers...${NC}"
PROVIDERS=$(curl -s -f "${SEARCH_GATEWAY_URL}/providers" | jq -r 'keys[]')

if [ -z "$PROVIDERS" ]; then
    echo -e "${RED}❌ CRITICAL: Could not fetch provider list from Search Gateway.${NC}"
    exit 1
fi

echo "✅ Found providers: ${PROVIDERS}"

for provider in $PROVIDERS; do
    TESTS_RUN=$((TESTS_RUN + 1))
    echo -e "\n--------------------------------------------------"
    echo -e "${YELLOW}▶️  Testing provider: ${provider}...${NC}"

    # Use a generic query
    QUERY="latest news on AI"
    
    # Construct payload to test only the current provider
    PAYLOAD=$(jq -n \
        --arg query "$QUERY" \
        --arg provider "$provider" \
        '{query: $query, providers: [$provider], max_results: 2}'
    )

    # Make the request and check the result
    response=$(curl -s --max-time ${API_TIMEOUT} -X POST -H "Content-Type: application/json" -d "$PAYLOAD" "${SEARCH_GATEWAY_URL}/search")
    
    # Check if the response is a valid JSON array and has at least one result
    if echo "$response" | jq -e 'type == "array" and length > 0' > /dev/null; then
        echo -e "${GREEN}✅ SUCCESS:${NC} Provider '${provider}' returned results."
        # Pretty print the first result's title for confirmation
        echo "  => Title: $(echo "$response" | jq -r '.[0].title')"
        SUCCESSES=$((SUCCESSES + 1))
    else
        echo -e "${RED}❌ FAILURE:${NC} Provider '${provider}' returned no results or an error."
        echo "   Response: $response"
        FAILURES=$((FAILURES + 1))
    fi
done


# --- Final Summary ---
echo -e "\n=================================================="
if [ $FAILURES -eq 0 ]; then
    echo -e "   🎉 ${GREEN}All ${TESTS_RUN} search providers passed! The gateway is stable.${NC} 🎉"
    exit 0
else
    echo -e "   🔥 ${RED}${FAILURES} out of ${TESTS_RUN} providers failed.${NC} 🔥"
    exit 1
fi
