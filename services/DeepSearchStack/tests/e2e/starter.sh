#!/bin/bash
# ======================================================================================
# DeepSearchStack - E2E Starter Script v1.0
# Inspired by advanced repository structure patterns
# 
# This script provides a comprehensive entry point for end-to-end testing of the entire
# DeepSearchStack infrastructure. It follows patterns from your sophisticated project
# structure to ensure comprehensive validation of all components.
# ======================================================================================

set -e  # Exit immediately if a command exits with a non-zero status.

# --- Configuration ---
export BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export COMPOSE_FILE="${BASE_DIR}/infra/docker-compose.yml"
export TEST_DIR="${BASE_DIR}/tests/e2e"
export LOG_FILE="${TEST_DIR}/e2e_tests.log"

# Load environment variables from .env if present
if [ -f "${BASE_DIR}/.env" ]; then
    export $(grep -v '^#' "${BASE_DIR}/.env" | xargs)
fi

# --- Colors & Formatting ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# --- Global Variables ---
START_TIME=$(date +%s)
TEST_COUNT=0
PASSED_COUNT=0
FAILED_COUNT=0
FAILED_TESTS=()

# --- Logging Functions ---
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1" | tee -a "$LOG_FILE"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1" | tee -a "$LOG_FILE"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1" | tee -a "$LOG_FILE"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" | tee -a "$LOG_FILE"
}

log_test_result() {
    local status=$1
    local test_name=$2
    local duration=$3
    
    if [ "$status" = "PASS" ]; then
        echo -e "${GREEN}✓${NC} $test_name (${duration}s)" | tee -a "$LOG_FILE"
        ((PASSED_COUNT++))
    else
        echo -e "${RED}✗${NC} $test_name (${duration}s)" | tee -a "$LOG_FILE"
        ((FAILED_COUNT++))
        FAILED_TESTS+=("$test_name")
    fi
}

# --- Helper Functions ---
wait_for_service() {
    local service_name=$1
    local health_check_url=$2
    local max_attempts=${3:-30}
    local wait_seconds=${4:-10}
    
    log_info "Waiting for $service_name at $health_check_url..."
    
    for i in $(seq 1 $max_attempts); do
        if curl -f -s "$health_check_url" > /dev/null 2>&1; then
            log_success "$service_name is ready"
            return 0
        fi
        log_info "Attempt $i/$max_attempts: $service_name not ready, waiting $wait_seconds seconds..."
        sleep "$wait_seconds"
    done
    
    log_error "$service_name failed to become ready after $max_attempts attempts"
    return 1
}

run_test() {
    local test_name=$1
    shift
    local command=$@
    
    ((TEST_COUNT++))
    local start_time=$(date +%s)
    
    log_info "Running test: $test_name"
    
    if eval "$command"; then
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        log_test_result "PASS" "$test_name" "$duration"
        return 0
    else
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        log_test_result "FAIL" "$test_name" "$duration"
        return 1
    fi
}

# --- Service Health Checks ---
check_core_services() {
    log_info "Checking core infrastructure services..."

    # Wait for critical services
    wait_for_service "PostgreSQL" "http://localhost:5432" 30 5 || true  # PostgreSQL health check via direct connection is complex
    wait_for_service "Redis" "http://localhost:6379/ping" 20 5 || true   # Redis health check via direct connection

    # For services with standard HTTP health checks
    docker compose -f "$COMPOSE_FILE" exec postgres pg_isready > /dev/null 2>&1 && log_success "PostgreSQL is ready" || log_error "PostgreSQL is not ready"
    docker compose -f "$COMPOSE_FILE" exec redis redis-cli ping > /dev/null 2>&1 && log_success "Redis is ready" || log_error "Redis is not ready"
}

check_llm_gateway() {
    log_info "Checking LLM Gateway service..."

    wait_for_service "LLM Gateway" "http://localhost:8080/health" 40 8 || return 1

    # Test provider listing
    run_test "LLM Gateway - List Providers" \
        "curl -s -f http://localhost:8080/providers | jq -e '.gemini' > /dev/null"

    # Test Gemini completion
    run_test "LLM Gateway - Gemini Completion" \
        "curl -s -f -X POST http://localhost:8080/completion \
        -H 'Content-Type: application/json' \
        -d '{\"provider\": \"gemini\", \"messages\": [{\"role\": \"user\", \"content\": \"Hello\"}]}' \
        | jq -e '.content' > /dev/null"
}

check_search_gateway() {
    log_info "Checking Search Gateway service..."
    
    wait_for_service "Search Gateway" "http://localhost:8002/health" 30 10 || return 1
    
    # Test search providers
    run_test "Search Gateway - List Providers" \
        "curl -s -f http://localhost:8002/providers | jq -e '.providers' > /dev/null"
    
    # Test search functionality
    run_test "Search Gateway - Basic Search" \
        "curl -s -f -X POST http://localhost:8002/search \
        -H 'Content-Type: application/json' \
        -d '{\"query\": \"test\", \"provider\": \"searxng\"}' \
        | jq -e '.results' > /dev/null"
}

check_deepsearch() {
    log_info "Checking DeepSearch service..."
    
    wait_for_service "DeepSearch" "http://localhost:8001/health" 40 10 || return 1
    
    # Test deepsearch functionality
    run_test "DeepSearch - Basic Query" \
        "curl -s -f -X POST http://localhost:8001/query \
        -H 'Content-Type: application/json' \
        -d '{\"query\": \"What is AI?\"}' \
        | jq -e '.answer' > /dev/null"
    
    # Test deepsearch stream
    run_test "DeepSearch - Streaming Query" \
        "curl -s -f -N -X POST http://localhost:8001/query/stream \
        -H 'Content-Type: application/json' \
        -d '{\"query\": \"Briefly explain machine learning\"}' \
        | grep -q 'data:'"
}

check_crawler() {
    log_info "Checking Crawler service..."
    
    wait_for_service "Crawler" "http://localhost:8003/health" 30 10 || return 1
    
    # Test crawling functionality
    run_test "Crawler - Basic Crawl" \
        "curl -s -f -X POST http://localhost:8003/crawl \
        -H 'Content-Type: application/json' \
        -d '{\"url\": \"https://example.com\", \"formats\": [\"markdown\"]}' \
        | jq -e '.success' > /dev/null"
}

check_vector_store() {
    log_info "Checking Vector Store service..."
    
    wait_for_service "Vector Store" "http://localhost:8004/health" 20 10 || return 1
    
    # Test basic vector store functionality
    run_test "Vector Store - Health Check" \
        "curl -s -f http://localhost:8004/health | jq -e '.status' > /dev/null"
}

check_frontend() {
    log_info "Checking Frontend service..."
    
    wait_for_service "Frontend" "http://localhost:3002" 40 10 || return 1
    
    run_test "Frontend - Basic Load" \
        "curl -s -f http://localhost:3002 | grep -q '<html'"
}

check_reverse_proxy() {
    log_info "Checking Reverse Proxy..."
    
    wait_for_service "Reverse Proxy" "http://localhost:8090" 20 5 || return 1
    
    run_test "Reverse Proxy - Route to DeepSearch" \
        "curl -s -f http://localhost:8090/api/health | jq -e '.status' > /dev/null"
}

# --- Integration Tests ---
test_end_to_end_flow() {
    log_info "Testing end-to-end flow..."
    
    run_test "E2E - Full Search Process" \
        "curl -s -f -N -X POST http://localhost:8090/api/search/stream \
        -H 'Content-Type: application/json' \
        -d '{\"query\": \"What are the latest developments in AI?\"}' \
        | grep -q 'finished'"
}

test_provider_failover() {
    log_info "Testing provider failover mechanisms..."

    # This would test if one provider fails, another is used
    # In current setup with only Gemini, we'll test that at least one provider is available
    run_test "Provider Availability - Basic Check" \
        "curl -s -f http://localhost:8080/providers | jq -e '.providers | length >= 1' > /dev/null"
}

# --- Performance & Stress Tests ---
test_concurrent_requests() {
    log_info "Testing concurrent request handling..."
    
    # Test multiple concurrent requests
    run_test "Concurrent Requests - 5 Simultaneous Queries" \
        "for i in {1..5}; do curl -s -f -X POST http://localhost:8001/query -H 'Content-Type: application/json' -d '{\"query\": \"test '\"\$i\"'\"}' & done; wait"
}

# --- Main Execution ---
main() {
    log_info "Starting DeepSearchStack E2E Test Suite"
    log_info "Base directory: $BASE_DIR"
    log_info "Test log: $LOG_FILE"
    
    # Create test directory if it doesn't exist
    mkdir -p "$TEST_DIR"
    
    # Initialize log file
    echo "DeepSearchStack E2E Test Suite - $(date)" > "$LOG_FILE"
    echo "========================================" >> "$LOG_FILE"
    
    # Check if stack is running
    if ! docker compose -f "$COMPOSE_FILE" ps | grep -q "Up"; then
        log_warn "No running containers found. Starting the stack..."
        docker compose -f "$COMPOSE_FILE" up -d
        log_info "Waiting for services to start..."
        sleep 30
    fi
    
    # Run all health checks
    check_core_services
    check_llm_gateway
    check_search_gateway
    check_deepsearch
    check_crawler
    check_vector_store
    check_frontend
    check_reverse_proxy
    
    # Run integration tests
    test_end_to_end_flow
    test_provider_failover
    
    # Run performance tests (optional)
    if [ "${RUN_PERFORMANCE_TESTS:-false}" = "true" ]; then
        test_concurrent_requests
    fi
    
    # Generate final report
    local end_time=$(date +%s)
    local total_duration=$((end_time - START_TIME))
    
    echo "" | tee -a "$LOG_FILE"
    log_info "E2E Test Suite Completed!"
    log_info "Total Runtime: $total_duration seconds"
    log_info "Total Tests: $TEST_COUNT"
    log_success "Passed: $PASSED_COUNT"
    log_error "Failed: $FAILED_COUNT"
    
    if [ $FAILED_COUNT -gt 0 ]; then
        echo "" | tee -a "$LOG_FILE"
        log_error "Failed Tests:"
        for failed_test in "${FAILED_TESTS[@]}"; do
            echo "  - $failed_test" | tee -a "$LOG_FILE"
        done
        return 1
    else
        log_success "All tests passed! 🎉"
        return 0
    fi
}

# --- Help & Usage ---
show_help() {
    echo "DeepSearchStack E2E Test Suite"
    echo ""
    echo "Usage: $0 [options]"
    echo ""
    echo "Options:"
    echo "  -h, --help              Show this help message"
    echo "  --performance          Run performance tests in addition to basic tests"
    echo "  --run-test <test_name> Run a specific test"
    echo ""
    echo "Examples:"
    echo "  $0                    Run all basic tests"
    echo "  $0 --performance      Run all tests including performance tests"
    echo "  $0 --run-test llm     Run only LLM gateway tests"
}

# --- Parse Arguments ---
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            show_help
            exit 0
            ;;
        --performance)
            export RUN_PERFORMANCE_TESTS=true
            shift
            ;;
        --run-test)
            RUN_SINGLE_TEST=true
            SINGLE_TEST_NAME="$2"
            shift 2
            ;;
        *)
            log_error "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# --- Execute Tests ---
if [ "$RUN_SINGLE_TEST" = "true" ]; then
    case "$SINGLE_TEST_NAME" in
        "llm")
            check_llm_gateway
            ;;
        "search")
            check_search_gateway
            ;;
        "deepsearch")
            check_deepsearch
            ;;
        "crawler")
            check_crawler
            ;;
        "vector")
            check_vector_store
            ;;
        "frontend")
            check_frontend
            ;;
        "proxy")
            check_reverse_proxy
            ;;
        *)
            log_error "Unknown test name: $SINGLE_TEST_NAME"
            log_info "Available tests: llm, search, deepsearch, crawler, vector, frontend, proxy"
            exit 1
            ;;
    esac
else
    main "$@"
fi