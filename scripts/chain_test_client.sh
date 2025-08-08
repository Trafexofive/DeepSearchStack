#!/bin/bash
# ======================================================================================
# DeepSearchStack - Exhaustive Feature Test Script v2.1 (Argument-Fixed)
#
# This script runs all major client commands via the new Python client to provide
# a comprehensive integration test of the entire stack.
# ======================================================================================

# --- Configuration ---
CLIENT_SCRIPT="python3 scripts/client.py"
FAILURES=0
TESTS_RUN=0

# --- Colors for better output ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

# --- Helper Function ---
run_command() {
    TESTS_RUN=$((TESTS_RUN + 1))
    echo -e "${CYAN}=======================================================================${NC}"
    # Note: We now quote "$@" to show how the arguments are properly grouped.
    echo -e "${YELLOW}▶️  EXECUTING COMMAND:${NC} ${GREEN}${CLIENT_SCRIPT} \"$@\"${NC}"
    echo -e "${CYAN}-----------------------------------------------------------------------${NC}"
    
    # Execute command and capture its exit code
    $CLIENT_SCRIPT "$@"
    local exit_code=$?
    
    if [ $exit_code -ne 0 ]; then
        echo -e "${RED}❌ COMMAND FAILED (Exit Code: $exit_code)${NC}"
        FAILURES=$((FAILURES + 1))
    fi
    
    sleep 1
}

# --- Main Test Sequence ---

echo -e "\n${BLUE}🚀 STARTING DEEPSEARCHSTACK EXHAUSTIVE TEST SUITE 🚀${NC}"

# 1. System Health and Provider Listing
run_command health
run_command llm-providers
run_command search-providers

# 2. 'ask' Command Combinations
echo -e "\n${BLUE}--- TESTING 'ask' COMMANDS ---${NC}"
# FIX: Queries are now properly quoted to be passed as a single argument.
run_command ask "What are the three laws of robotics?" --provider groq
run_command ask "What are the three laws of robotics?" --provider gemini
run_command ask "What are the three laws of robotics?" --provider ollama
run_command ask "Write a short poem about the ocean." --provider ollama --stream
run_command ask "Write a short poem about the ocean." --provider gemini --stream
run_command ask "Write a short poem about the ocean." --provider groq --stream

# 3. 'search' Command Combinations
echo -e "\n${BLUE}--- TESTING 'search' COMMANDS ---${NC}"
run_command search "What is the doppler effect?" --llm-provider ollama
run_command search "What is the doppler effect?" --llm-provider groq
run_command search "Explain black holes to a five-year-old." --llm-provider ollama --stream
run_command search "Explain black holes to a five-year-old." --llm-provider groq --stream
run_command search "Latest news on Mars rovers" --providers whoogle
run_command search "Top 3 recipes for vegetarian chili" --max-results 3

# --- Final Summary ---
echo -e "\n${CYAN}=======================================================================${NC}"
if [ $FAILURES -eq 0 ]; then
    echo -e "${GREEN}✅ EXHAUSTIVE TEST SUITE COMPLETE. All ${TESTS_RUN} commands passed! ✅${NC}\n"
    exit 0
else
    echo -e "${RED}❌ TEST SUITE FAILED. ${FAILURES} out of ${TESTS_RUN} commands failed. ❌${NC}"
    echo -e "${YELLOW}Note: Failures related to 'gemini' may be due to API rate limits and not a bug.${NC}\n"
    exit 1
fi
