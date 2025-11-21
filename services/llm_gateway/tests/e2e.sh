#!/bin/bash

# E2E Tests for LLM Gateway
# This script runs end-to-end tests to verify the LLM Gateway functionality

set -e  # Exit on any error

# Configuration
GATEWAY_URL="${GATEWAY_URL:-http://localhost:8080}"
TIMEOUT="${TIMEOUT:-30}"
LOG_FILE="e2e_tests.log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test counter
test_counter=0
passed_tests=0

# Function to log messages
log_message() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

# Function to run a test
run_test() {
    local test_name="$1"
    local test_command="$2"
    
    ((test_counter++))
    echo -e "${BLUE}Test $test_counter: $test_name${NC}"
    log_message "Running test: $test_name"
    
    if eval "$test_command"; then
        echo -e "${GREEN}✓ PASSED${NC}"
        log_message "PASSED: $test_name"
        ((passed_tests++))
    else
        echo -e "${RED}✗ FAILED${NC}"
        log_message "FAILED: $test_name"
    fi
    echo
}

# Function to wait for gateway to be ready
wait_for_gateway() {
    local timeout=$1
    local interval=5
    local count=0
    
    echo -e "${BLUE}Waiting for LLM Gateway to be ready...${NC}"
    
    while [ $count -lt $((timeout / interval)) ]; do
        if curl -f -s "$GATEWAY_URL/health" > /dev/null 2>&1; then
            echo -e "${GREEN}LLM Gateway is ready!${NC}"
            return 0
        fi
        sleep $interval
        ((count++))
    done
    
    echo -e "${RED}Timeout waiting for LLM Gateway${NC}"
    return 1
}

# Main test execution
main() {
    log_message "Starting E2E tests"
    
    # Wait for gateway to be ready
    if ! wait_for_gateway $TIMEOUT; then
        log_message "Gateway not ready, aborting tests"
        exit 1
    fi
    
    # Test 1: Health check endpoint
    run_test "Health Check" '
        response=$(curl -s -w "\n%{http_code}" $GATEWAY_URL/health)
        http_code=$(echo "$response" | tail -n1)
        [ "$http_code" -eq 200 ]
    '
    
    # Test 2: Basic completion request
    run_test "Basic Completion Request" '
        response=$(curl -s -w "\n%{http_code}" -X POST $GATEWAY_URL/v1/completions \
            -H "Content-Type: application/json" \
            -d "{
                \"messages\": [{\"role\": \"user\", \"content\": \"Hello\"}],
                \"model\": \"llama-3.1-8b-instant\",
                \"temperature\": 0.7
            }")
        http_code=$(echo "$response" | tail -n1)
        response_body=$(echo "$response" | sed \$d)
        
        [ "$http_code" -eq 200 ] && [ -n "$(echo "$response_body" | jq -r ".content" 2>/dev/null)" ]
    '
    
    # Test 3: Stream request
    run_test "Stream Request" '
        response=$(curl -s -w "\n%{http_code}" -X POST $GATEWAY_URL/v1/completions \
            -H "Content-Type: application/json" \
            -d "{
                \"messages\": [{\"role\": \"user\", \"content\": \"Write a short poem.\"}],
                \"model\": \"llama-3.1-8b-instant\",
                \"temperature\": 0.7,
                \"stream\": true
            }")
        http_code=$(echo "$response" | tail -n1)
        
        [ "$http_code" -eq 200 ]
    '
    
    # Test 4: Check metrics endpoint
    run_test "Metrics Endpoint" '
        response=$(curl -s -w "\n%{http_code}" $GATEWAY_URL/metrics)
        http_code=$(echo "$response" | tail -n1)
        
        [ "$http_code" -eq 200 ]
    '
    
    # Test 5: Invalid request
    run_test "Invalid Request Handling" '
        response=$(curl -s -w "\n%{http_code}" -X POST $GATEWAY_URL/v1/completions \
            -H "Content-Type: application/json" \
            -d "{}")
        http_code=$(echo "$response" | tail -n1)
        
        [ "$http_code" -ge 400 ]
    '
    
    # Summary
    echo -e "${BLUE}E2E Test Summary${NC}"
    echo -e "${BLUE}--------------${NC}"
    echo "Total tests: $test_counter"
    echo -e "${GREEN}Passed: $passed_tests${NC}"
    echo -e "${RED}Failed: $((test_counter - passed_tests))${NC}"
    
    if [ $passed_tests -eq $test_counter ]; then
        echo -e "${GREEN}All tests passed! ✓${NC}"
        log_message "All tests passed"
        exit 0
    else
        echo -e "${RED}Some tests failed! ✗${NC}"
        log_message "Some tests failed"
        exit 1
    fi
}

# Run the tests
main "$@"