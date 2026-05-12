#!/bin/bash

# ======================================================================================
# Chimera Orchestrator Test Script - Forged by Gemini
#
# A script to rigorously test the Ollama API Orchestrator.
# ======================================================================================

set -e # Exit immediately if a command exits with a non-zero status.

# --- Pre-Test Cleanup ---
# Forcefully remove any leftover worker containers from previous runs
cleanup() {
    echo "Performing pre-test cleanup..."
    WORKER_IDS=$(docker ps -a -q --filter "label=ollama-worker")
    if [ -n "$WORKER_IDS" ]; then
        echo "Found and removing leftover worker containers: $WORKER_IDS"
        docker rm -f $WORKER_IDS
    else
        echo "No leftover worker containers found."
    fi
}
cleanup

# --- Configuration ---
GATEWAY_URL="http://localhost:11434"
GATEWAY_HOST=""
CLIENT="./scripts/client.sh"
export OLLAMA_HOST="localhost"
export OLLAMA_PORT=11434 # Make client.sh talk to the orchestrator directly

# --- Helper Functions ---
print_header() {
    echo -e "\n\033[1;35m####### TESTING: $1 #######\033[0m"
}

# --- Configuration ---
print_header() {
    echo -e "\n\033[1;35m####### TESTING: $1 #######\033[0m"
}

make_gateway_request() {
    local method=$1
    local endpoint=$2
    echo "--> $method $GATEWAY_URL$endpoint"
    curl -s -X $method "$GATEWAY_URL$endpoint"
    echo -e "\n"
}

# --- Test Execution ---

print_header "Initial State: Pruning any existing workers"
make_gateway_request "POST" "/admin/instances/prune"

print_header "Initial State: Listing workers (should be empty)"
make_gateway_request "GET" "/admin/instances"

print_header "Spawning the first worker (ollama-worker-1)"
make_gateway_request "POST" "/admin/instances/spawn"

print_header "Listing workers (should show one worker)"
make_gateway_request "GET" "/admin/instances"

# Give the worker a moment to start up fully
sleep 5

print_header "Attempting to pull gemma:2b via the gateway"
$CLIENT pull --model "gemma:2b"

print_header "Listing models on the worker (via gateway)"
$CLIENT list

print_header "Running generation request via gateway"
$CLIENT generate --prompt "First worker operational."

print_header "Spawning a second worker (ollama-worker-2)"
make_gateway_request "POST" "/admin/instances/spawn"

print_header "Listing workers (should show two workers)"
make_gateway_request "GET" "/admin/instances"

print_header "Running second generation request to test load balancing"
$CLIENT generate --prompt "Second worker operational."

print_header "Final State: Pruning all workers"
make_gateway_request "POST" "/admin/instances/prune"

print_header "Final State: Listing workers (should be empty)"
make_gateway_request "GET" "/admin/instances"


echo -e "\n\033[1;32m####### ORCHESTRATOR TEST COMPLETE #######\033[0m"
