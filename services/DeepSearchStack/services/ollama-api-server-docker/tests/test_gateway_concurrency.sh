#!/bin/bash

# ======================================================================================
# Chimera Gateway Concurrency Test - Forged by Gemini
#
# This script tests the gateway's ability to handle concurrent requests while scaling.
# 1. Prunes all existing workers.
# 2. Spawns 2 new workers in the background.
# 3. Immediately fires 2 concurrent generation requests.
# The gateway is expected to queue these requests and process them in parallel
# as soon as the two workers become available.
# ======================================================================================

set -e

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

GATEWAY_URL="http://localhost"
GATEWAY_HOST="api.localhost"

print_header() {
    echo -e "\n\033[1;35m####### $1 #######\033[0m"
}

# --- Step 1: Prune all existing workers for a clean slate ---
print_header "Pruning all existing workers..."
curl -s -X POST -H "Host: $GATEWAY_HOST" "$GATEWAY_URL/admin/instances/prune" -w "
Prune complete.
"

# --- Step 2: Spawn 2 new worker instances in the background ---
print_header "Spawning 2 new worker instances..."
curl -s -X POST -H "Host: $GATEWAY_HOST" "$GATEWAY_URL/admin/instances/spawn" > /dev/null &
curl -s -X POST -H "Host: $GATEWAY_HOST" "$GATEWAY_URL/admin/instances/spawn" > /dev/null &
wait
echo "Spawn commands sent for 2 workers."

# --- Step 3: Immediately send 2 concurrent requests ---
print_header "Sending 2 concurrent generation requests..."

PROMPT_1="Explain the theory of relativity in simple terms."
PROMPT_2="Write a python function that calculates the factorial of a number."

# Fire both requests in the background and pipe output to files
curl -s -X POST -H "Host: $GATEWAY_HOST" -d "{\"model\": \"gemma3:1b\", \"prompt\": \"$PROMPT_1\"}" "$GATEWAY_URL/api/generate" > response1.log & \
curl -s -X POST -H "Host: $GATEWAY_HOST" -d "{\"model\": \"gemma3:1b\", \"prompt\": \"$PROMPT_2\"}" "$GATEWAY_URL/api/generate" > response2.log & 

print_header "Waiting for both background requests to complete..."
wait

print_header "Request 1 Response:"
cat response1.log

print_header "Request 2 Response:"
cat response2.log

# Clean up log files
rm response1.log response2.log

print_header "Concurrent test complete!"
