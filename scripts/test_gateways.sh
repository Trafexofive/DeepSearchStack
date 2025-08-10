#!/bin/bash
# ======================================================================================
# DeepSearchStack - Global Integration Test Suite v2.3 (Final)
#
# This script tests all core services, continues on failure, and provides a
# summary report at the end. Includes a more patient check for YaCy.
# ======================================================================================

# --- Script Configuration ---
set -o pipefail

# --- Load environment variables ---
if [ -f .env ]; then
    echo "Loading environment variables from .env file..."
    export $(grep -v '^#' .env | xargs)
fi

# --- Test Configuration ---
BASE_URL=${BASE_URL:-http://localhost}
LLM_GATEWAY_URL="${BASE_URL}/llm"
SEARCH_AGENT_URL="${BASE_URL}/agent"
WEB_API_URL="${BASE_URL}/"
SEARXNG_URL="${BASE_URL}/searxng/"
WHOOGLE_URL="${BASE_URL}/whoogle/"
YACY_URL="${BASE_URL}/yacy/"

OLLAMA_MODEL_TO_TEST=${OLLAMA_DEFAULT_MODEL:-llama3}
HEALTH_CHECK_TIMEOUT=20
API_TIMEOUT=150

# --- State & Colors ---
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
FAILURES=0
TESTS_RUN=0

# --- Helper Functions ---
function run_test() {
    local test_name=$1
    shift
    local command=$@
    TESTS_RUN=$((TESTS_RUN + 1))
    echo -e "\n${YELLOW}▶️  Running test: ${test_name}...${NC}"
    if eval "$command"; then
        echo -e "${GREEN}✅ SUCCESS: ${test_name}.${NC}"
    else
        echo -e "${RED}❌ FAILURE: ${test_name}. See output above for details.${NC}"
        FAILURES=$((FAILURES + 1))
    fi
}

function check_service_health() {
    local service_name=$1
    local url=$2
    local expected_code=${3:-200}
    local retries=${4:-5}
    local delay=${5:-5}
    TESTS_RUN=$((TESTS_RUN + 1))
    echo -e "\n${YELLOW}▶️  Running health check: ${service_name}...${NC}"
    for i in $(seq 1 $retries); do
        local http_code=$(curl -s -o /dev/null -w "%{http_code}" -L --max-time ${HEALTH_CHECK_TIMEOUT} "$url" || true)
        if [[ "$http_code" -eq "$expected_code" ]]; then
            echo -e "    ${GREEN}✅ SUCCESS: ${service_name} is healthy (Status: $http_code).${NC}"
            return 0
        fi
        echo -e "    Attempt $i/$retries failed (Status: $http_code). Retrying in ${delay}s..."
        sleep $delay
    done
    echo -e "    ${RED}❌ FAILURE: ${service_name} is unhealthy after multiple attempts.${NC}"
    FAILURES=$((FAILURES + 1))
    return 1
}

# --- TEST SUITE START ---
echo -e "\n${GREEN}======================================================="
echo -e "      DeepSearchStack Global Integration Test"
echo -e "=======================================================${NC}\n"

# --- 1. Initial Health Checks ---
echo -e "${YELLOW}--- STEP 1: Verifying All Service Health via Reverse Proxy ---${NC}"
check_service_health "Web API / Frontend" "${WEB_API_URL}" 200
check_service_health "LLM Gateway" "${LLM_GATEWAY_URL}/health" 200
check_service_health "Search Agent" "${SEARCH_AGENT_URL}/health" 200
check_service_health "SearXNG" "${SEARXNG_URL}" 200
check_service_health "Whoogle" "${WHOOGLE_URL}" 200
check_service_health "YaCy API" "${YACY_URL}/api/status.json" 200 35 6 # Extra patient check for YaCy

# --- 2. LLM Gateway API Tests ---
echo -e "${YELLOW}--- STEP 2: Testing LLM Gateway Functionality ---${NC}"

run_test "LLM Gateway: Get available providers" \
    "curl -s -f --max-time ${API_TIMEOUT} '${LLM_GATEWAY_URL}/providers' | jq -e '.ollama.available == true'"

run_test "LLM Gateway: Successful completion with Ollama" \
    "curl -s -f --max-time ${API_TIMEOUT} -X POST '${LLM_GATEWAY_URL}/completion' \
    -H 'Content-Type: application/json' \
    -d '{\"provider\": \"ollama\", \"messages\": [{\"role\": \"user\", \"content\": \"Why is the sky blue?\"}]}' \
    | jq -e '.provider_name == \"ollama\" and .model == \"${OLLAMA_MODEL_TO_TEST}\" and (.content | length > 10)'"

# --- 3. Search Agent End-to-End Tests ---
echo -e "${YELLOW}--- STEP 3: Running Search Agent End-to-End Tests ---${NC}"

run_test "Search Agent: End-to-end search returns valid answer and sources" \
    "curl -s -f --max-time ${API_TIMEOUT} -X POST '${SEARCH_AGENT_URL}/search' \
    -H 'Content-Type: application/json' \
    -d '{\"query\": \"What are the latest developments in AI?\"}' \
    | jq -e '(.answer | length > 20) and (.sources | length > 0) and (.sources[0] | has(\"title\") and has(\"url\"))'"


# --- TEST SUITE END ---
echo -e "\n${GREEN}=======================================================${NC}"
if [ $FAILURES -eq 0 ]; then
    echo -e "   🎉 ${GREEN}All ${TESTS_RUN} global tests passed successfully! The stack is flawless.${NC} 🎉"
    exit 0
else
    echo -e "   🔥 ${RED}${FAILURES} out of ${TESTS_RUN} global tests failed. Review the logs above.${NC} 🔥"
    exit 1
fi
