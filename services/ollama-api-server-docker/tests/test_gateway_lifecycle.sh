#!/bin/bash

# ======================================================================================
# Chimera Gateway Test Script - Forged by Gemini
#
# This script tests the full lifecycle of the orchestrator:
# 1. Prunes all existing workers.
# 2. Spawns 4 new workers.
# 3. Immediately fires 4 concurrent generation requests.
# The gateway is expected to queue these requests and process them as workers
# become ready (i.e., finish downloading the required model).
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

# --- Step 2: Spawn 4 new worker instances ---
print_header "Spawning 4 new worker instances..."
for i in {1..4}; do
  curl -s -X POST -H "Host: $GATEWAY_HOST" "$GATEWAY_URL/admin/instances/spawn" > /dev/null & 

done
wait
echo "Spawn commands sent for 4 workers."

# --- Step 3: Immediately send 4 concurrent requests ---
# The gateway's internal logic should handle queueing these until workers are ready.
print_header "Sending 4 concurrent generation requests..."

PROMPT_1="Tell me a short story about a robot who dreams of electric sheep."
PROMPT_2="What are the fundamental differences between object-oriented and functional programming?"
PROMPT_3="Write a haiku about the city skyline at dusk."
PROMPT_4="Explain the concept of 'Infrastructure as Code' and its benefits."

# Fire all requests in the background
curl -s -X POST -H "Host: $GATEWAY_HOST" -d "{\"model\": \"gemma3:1b\", \"prompt\": \"$PROMPT_1\"}" "$GATEWAY_URL/api/generate" & \
curl -s -X POST -H "Host: $GATEWAY_HOST" -d "{\"model\": \"gemma3:1b\", \"prompt\": \"$PROMPT_2\"}" "$GATEWAY_URL/api/generate" & \
curl -s -X POST -H "Host: $GATEWAY_HOST" -d "{\"model\": \"gemma3:1b\", \"prompt\": \"$PROMPT_3\"}" "$GATEWAY_URL/api/generate" & \
curl -s -X POST -H "Host: $GATEWAY_HOST" -d "{\"model\": \"gemma3:1b\", \"prompt\": \"$PROMPT_4\"}" "$GATEWAY_URL/api/generate" & 

print_header "Waiting for all background requests to complete..."
wait

print_header "All tests complete!"
