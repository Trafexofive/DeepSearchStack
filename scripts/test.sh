#!/bin/bash
# ======================================================================================
# DeepSearchStack - Comprehensive Integration Test Suite v2.0
#
# This script tests all services through the reverse proxy, ensuring that routing,
# service health, API contracts, and core logic are functioning correctly.
# It uses `jq` for robust JSON parsing and validation.
# ======================================================================================

# --- Script Configuration ---
set -e
set -o pipefail

# --- Load environment variables from .env file if it exists ---
if [ -f .env ]; then
    echo "Loading environment variables from .env file..."
    # Exports the variables to be available to the script
    export $(grep -v '^#' .env | xargs)
fi

# --- Test Configuration (URLs point to the reverse proxy) ---
BASE_URL=${BASE_URL:-http://localhost} # Default to http://localhost if not set
LLM_GATEWAY_URL="${BASE_URL}/llm"
SEARCH_AGENT_URL="${BASE_URL}/agent"
WEB_API_URL="${BASE_URL}/"
SEARXNG_URL="${BASE_URL}/searxng/"
WHOOGLE_URL="${BASE_URL}/whoogle/"
YACY_URL="${BASE_URL}/yacy/"

# Model to use for testing. Must match OLLAMA_DEFAULT_MODEL in your .env
OLLAMA_MODEL_TO_TEST=${OLLAMA_DEFAULT_MODEL:-llama3}
HEALTH_CHECK_TIMEOUT=10 # seconds
API_TIMEOUT=90 # seconds

# --- Colors for better output ---
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'

# --- Helper Functions ---
function run_test() {
    local test_name=$1
    local command=$2
    echo -e "${YELLOW}▶️  Running test: ${test_name}...${NC}"
    if eval "$command"; then
        echo -e "${GREEN}✅ SUCCESS: ${test_name}.${NC}"
    else
        echo -e "${RED}❌ FAILURE: ${test_name}. See output above for details.${NC}"
        exit 1
    fi
}

function check_service_health() {
    local service_name=$1
    local url=$2
    local expected_code=${3:-200}
    echo -e "  - Checking health of ${YELLOW}${service_name}${NC} at ${url}..."
    for i in {1..15}; do
        # THE FIX: Corrected %{http_code} and added --max-time for timeout
        local http_code=$(curl -s -o /dev/null -w "%{http_code}" -L --max-time ${HEALTH_CHECK_TIMEOUT} "$url" || true)
        if [[ "$http_code" -eq "$expected_code" ]]; then
            echo -e "    ${GREEN}OK! Service is healthy (Status: $http_code).${NC}"
            return 0
        fi
        echo -e "    Attempt $i/15 failed (Status: $http_code). Retrying in 4 seconds..."
        sleep 4
    done
    echo -e "    ${RED}FATAL: ${service_name} is unhealthy after multiple attempts.${NC}"; exit 1
}

# --- TEST SUITE START ---
echo -e "\n${GREEN}======================================================="
echo -e "  DeepSearchStack Comprehensive Integration Test Suite"
echo -e "=======================================================${NC}\n"

# --- 1. Initial Health Checks ---
echo -e "${YELLOW}--- STEP 1: Verifying Service Health via Reverse Proxy ---${NC}"
check_service_health "Web API" "${WEB_API_URL}" 200
check_service_health "LLM Gateway" "${LLM_GATEWAY_URL}/health" 200
check_service_health "Search Agent" "${SEARCH_AGENT_URL}/health" 200
check_service_health "SearXNG" "${SEARXNG_URL}" 200
check_service_health "Whoogle" "${WHOOGLE_URL}" 200
# YaCy root often returns 401/403 by default, which is an "up" state
check_service_health "YaCy" "${YACY_URL}" 401

# --- 2. LLM Gateway API Tests (/llm/) ---
echo -e "\n${YELLOW}--- STEP 2: Testing LLM Gateway Functionality ---${NC}"

run_test "Get available providers and confirm Ollama is ready" \
    "curl -s -f --max-time ${API_TIMEOUT} '${LLM_GATEWAY_URL}/providers' | jq -e '.ollama.available == true'"

run_test "Successful completion with Ollama" \
    "curl -s -f --max-time ${API_TIMEOUT} -X POST '${LLM_GATEWAY_URL}/completion' \
    -H 'Content-Type: application/json' \
    -d '{\"provider\": \"ollama\", \"messages\": [{\"role\": \"user\", \"content\": \"Why is the sky blue?\"}]}' \
    | jq -e '.provider_name == \"ollama\" and .model == \"${OLLAMA_MODEL_TO_TEST}\" and (.content | length > 10)'"

run_test "Handles invalid provider gracefully (should not fail)" \
    "curl -s -f --max-time ${API_TIMEOUT} -X POST '${LLM_GATEWAY_URL}/completion' \
    -H 'Content-Type: application/json' \
    -d '{\"provider\": \"non_existent_provider\", \"messages\": [{\"role\": \"user\", \"content\": \"This is a test\"}]}' \
    | jq -e '.provider_name | test(\"ollama|groq|gemini\")'" # Checks that it fell back to a real provider

run_test "Handles request with no messages (expects 422 Unprocessable Entity)" \
    "http_code=\$(curl -s -o /dev/null -w '%{http_code}' --max-time ${API_TIMEOUT} -X POST '${LLM_GATEWAY_URL}/completion' \
    -H 'Content-Type: application/json' -d '{}'); [[ \$http_code -eq 422 ]]"

# --- Conditional Tests for External Providers ---
if [[ -n "$GROQ_API_KEY" && "${ENABLE_GROQ}" == "true" ]]; then
    run_test "Successful completion with Groq" \
        "curl -s -f --max-time ${API_TIMEOUT} -X POST '${LLM_GATEWAY_URL}/completion' \
        -H 'Content-Type: application/json' \
        -d '{\"provider\": \"groq\", \"messages\": [{\"role\": \"user\", \"content\": \"What is the capital of France?\"}]}' \
        | jq -e '.provider_name == \"groq\" and .content | test(\"(?i)paris\")'"
else
    echo -e "${YELLOW}ℹ️  SKIPPED: Groq provider test (ENABLE_GROQ is not 'true' or GROQ_API_KEY is not set).${NC}"
fi

if [[ -n "$GEMINI_API_KEY" && "${ENABLE_GEMINI}" == "true" ]]; then
    run_test "Successful completion with Gemini" \
        "curl -s -f --max-time ${API_TIMEOUT} -X POST '${LLM_GATEWAY_URL}/completion' \
        -H 'Content-Type: application/json' \
        -d '{\"provider\": \"gemini\", \"messages\": [{\"role\": \"user\", \"content\": \"What is 2 + 2?\"}]}' \
        | jq -e '.provider_name == \"gemini\" and .content | contains(\"4\")'"
else
    echo -e "${YELLOW}ℹ️  SKIPPED: Gemini provider test (ENABLE_GEMINI is not 'true' or GEMINI_API_KEY is not set).${NC}"
fi

# --- 3. Search Agent End-to-End Tests (/agent/) ---
echo -e "\n${YELLOW}--- STEP 3: Running Search Agent End-to-End Tests ---${NC}"

run_test "End-to-end search returns synthesized answer and structured sources" \
    "curl -s -f --max-time ${API_TIMEOUT} -X POST '${SEARCH_AGENT_URL}/search' \
    -H 'Content-Type: application/json' \
    -d '{\"query\": \"What are the latest developments in AI?\"}' \
    | jq -e '(.answer | length > 20) and (.sources | length > 0) and (.[_sources][0] | has(\"title\") and has(\"url\"))'"

run_test "Search for a nonsensical query returns a graceful message" \
    "curl -s -f --max-time ${API_TIMEOUT} -X POST '${SEARCH_AGENT_URL}/search' \
    -H 'Content-Type: application/json' \
    -d '{\"query\": \"asdfqwerlkjhpoiu12345\"}' \
    | jq -e '(.answer | contains(\"couldn't find\")) and (.sources | length == 0)'"

# --- 4. Search Backend Passthrough Tests ---
echo -e "\n${YELLOW}--- STEP 4: Verifying Search Backend Proxy Routes ---${NC}"

run_test "SearXNG UI is accessible through the reverse proxy" \
    "curl -s -f -L --max-time ${HEALTH_CHECK_TIMEOUT} '${SEARXNG_URL}' | grep -q 'SearXNG'"

run_test "Whoogle UI is accessible through the reverse proxy" \
    "curl -s -f -L --max-time ${HEALTH_CHECK_TIMEOUT} '${WHOOGLE_URL}' | grep -q 'Whoogle Search'"


# --- TEST SUITE END ---
echo -e "\n${GREEN}======================================================="
echo -e "🎉 All tests passed successfully! The stack is fully operational. 🎉"
echo -e "=======================================================${NC}\n"
exit 0
