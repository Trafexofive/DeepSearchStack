#!/bin/bash
# ======================================================================================
# DeepSearchStack - Flawless Resilience Test Suite v7.0 (Post-Decoupling)
#
# Principles:
# 1. Relies on Docker's internal health status for service readiness.
# 2. Tests the new decoupled architecture via the main web-api endpoint.
# 3. Validates critical failure paths for the orchestrator.
# ======================================================================================

# --- Load environment variables from .env file if it exists ---
if [ -f .env ]; then
    echo "Loading environment variables from .env file..."
    export $(grep -v '^#' .env | xargs)
fi

# --- Test Configuration ---
BASE_URL=${BASE_URL:-http://localhost}
# All tests now go through the final, user-facing API endpoint.
API_URL="${BASE_URL}/api"
API_TIMEOUT=180

# --- State & Colors ---
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'
FAILURES=0
TESTS_RUN=0

# --- Helper Functions ---
function run_test() {
    local test_name=$1
    shift
    local command=$@
    TESTS_RUN=$((TESTS_RUN + 1))
    echo -e "\n${YELLOW}▶️  Running test:${NC} ${test_name}..."

    output=$(eval "$command" 2>&1)
    local exit_code=$?

    if [ $exit_code -eq 0 ]; then
        echo -e "${GREEN}✅ SUCCESS:${NC} ${test_name}."
    else
        echo -e "${RED}❌ FAILURE:${NC} ${test_name}. (Exit Code: $exit_code)"
        echo -e "--------- Output ---------\n${output}\n--------------------------"
        FAILURES=$((FAILURES + 1))
    fi
    sleep 1
}

function await_stack_health() {
    echo -e "\n${YELLOW}▶️  Awaiting stack health...${NC}"
    local required_healthy_count=5 # postgres, redis, ollama, llm-gateway, yacy
    for i in {1..45}; do # Wait up to 3 minutes
        healthy_count=$(docker compose -p deepsearch -f infra/docker-compose.yml ps | grep -c "(healthy)" || true)
        if [ "$healthy_count" -ge "$required_healthy_count" ]; then
            echo -e "${GREEN}✅ SUCCESS:${NC} All critical services are healthy."
            return 0
        fi
        echo "  - Waiting for services to become healthy ($healthy_count/$required_healthy_count)... attempt $i/45"
        sleep 4
    done
    
    echo -e "${RED}❌ CRITICAL FAILURE:${NC} Stack did not become healthy in time. Current status:"
    docker compose -p deepsearch -f infra/docker-compose.yml ps
    FAILURES=$((FAILURES + 1))
    exit 1
}


# --- TEST SUITE START ---
echo -e "\n${BLUE}======================================================="
echo -e "      DeepSearchStack Flawless Resilience Test Suite v7.0"
echo -e "=======================================================${NC}"

# --- 1. Initial Health Checks ---
await_stack_health

# --- 2. Web API Orchestrator Happy Path ---
echo -e "\n${BLUE}--- STEP 2: Testing Web API Orchestrator Happy Path ---${NC}"
run_test "Web API: End-to-end streaming search via orchestrator" \
    "curl -s -f -N --max-time ${API_TIMEOUT} -X POST '${API_URL}/search/stream' \
    -H 'Content-Type: application/json' \
    -d '{\"query\": \"What are the latest developments in AI?\"}' \
    | grep -q 'finished\": true'"

# --- 2.5. LLM Provider Specific Tests ---
echo -e "\n${BLUE}--- STEP 2.5: Testing Specific LLM Providers via Web API ---${NC}"

run_test "Web API: Direct chat completion with Ollama" \
    "curl -s -f -N --max-time ${API_TIMEOUT} -X POST '${API_URL}/completion/stream' \
    -H 'Content-Type: application/json' \
    -d '{\"provider\": \"ollama\", \"messages\": [{\"role\": \"user\", \"content\": \"Why is the sky blue?\"}]}' \
    | grep -q 'data:'"

# Conditional Groq Test
if [[ -n "$GROQ_API_KEY" && "${ENABLE_GROQ}" == "true" ]]; then
    run_test "Web API: Direct chat completion with Groq" \
        "curl -s -f -N --max-time ${API_TIMEOUT} -X POST '${API_URL}/completion/stream' \
        -H 'Content-Type: application/json' \
        -d '{\"provider\": \"groq\", \"messages\": [{\"role\": \"user\", \"content\": \"What is the capital of France?\"}]}' \
        | grep -q 'Paris'"
else
    echo -e "${YELLOW}ℹ️  SKIPPED: Groq provider test (ENABLE_GROQ is not 'true' or GROQ_API_KEY is not set).${NC}"
fi

# Conditional Gemini Test
if [[ -n "$GEMINI_API_KEY" && "${ENABLE_GEMINI}" == "true" ]]; then
    run_test "Web API: Direct chat completion with Gemini" \
        "curl -s -f -N --max-time ${API_TIMEOUT} -X POST '${API_URL}/completion/stream' \
        -H 'Content-Type: application/json' \
        -d '{\"provider\": \"gemini\", \"messages\": [{\"role\": \"user\", \"content\": \"What is 2 + 2?\"}]}' \
        | grep -q '4'"
else
    echo -e "${YELLOW}ℹ️  SKIPPED: Gemini provider test (ENABLE_GEMINI is not 'true' or GEMINI_API_KEY is not set).${NC}"
fi

# --- 3. CRITICAL FAILURE SIMULATION ---
echo -e "\n${BLUE}--- STEP 3: Simulating LLM Gateway Failure for Web API ---${NC}"
run_test "Web API: Gracefully handles LLM failure during synthesis" \
    "docker compose -p deepsearch -f infra/docker-compose.yml stop llm-gateway >/dev/null && \
    curl -s -f -N --max-time ${API_TIMEOUT} -X POST '${API_URL}/search/stream' \
    -H 'Content-Type: application/json' \
    -d '{\"query\": \"This will fail.\"}' \
    | grep -q 'Error during synthesis'"

# --- 4. System Recovery Check ---
echo -e "\n${BLUE}--- STEP 4: Verifying System Recovery ---${NC}"
echo "  - Restarting 'llm-gateway' container..."
docker compose -p deepsearch -f infra/docker-compose.yml start llm-gateway >/dev/null
# Wait for the service to report healthy again
for i in {1..15}; do if docker compose -p deepsearch -f infra/docker-compose.yml ps llm-gateway | grep -q "(healthy)"; then break; fi; sleep 2; done

run_test "Web API: Functions correctly after simulated failure" \
    "curl -s -f -N --max-time ${API_TIMEOUT} -X POST '${API_URL}/search/stream' \
    -H 'Content-Type: application/json' \
    -d '{\"query\": \"Does the system still work after recovery?\"}' \
    | grep -q 'finished\": true'"


# --- TEST SUITE END ---
echo -e "\n${BLUE}=======================================================${NC}"
if [ $FAILURES -eq 0 ]; then
    echo -e "   🎉 ${GREEN}All critical tests passed! The stack is flawless and resilient.${NC} 🎉"
    echo -e "${BLUE}=======================================================${NC}\n"
    exit 0
else
    echo -e "   🔥 ${RED}${FAILURES} critical test(s) failed. Review the logs above.${NC} 🔥"
    echo -e "${BLUE}=======================================================${NC}\n"
    exit 1
fi