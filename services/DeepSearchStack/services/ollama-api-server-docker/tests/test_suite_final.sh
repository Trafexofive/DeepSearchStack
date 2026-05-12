#!/bin/bash

# ======================================================================================
# Chimera Final Test Suite - Forged by Gemini
#
# A minimal, end-to-end test script to validate the core functionality of the stack.
# 1. Waits for the gateway to be healthy.
# 2. Prunes any old workers.
# 3. Spawns one new worker.
# 4. Waits for the new worker to be ready.
# 5. Runs a generation request through the gateway.
# 6. Cleans up by pruning the worker.
# ======================================================================================

set -e

# --- Configuration ---
GATEWAY_URL="http://localhost"
GATEWAY_HOST="api.localhost"
CLIENT="./scripts/client.sh"
export OLLAMA_HOST="localhost"
export TRAEFIK_HOST="api.localhost"
export OLLAMA_PORT=80

# --- Helper Functions ---
print_header() {
    echo -e "\n\033[1;35m####### $1 #######\033[0m"
}

# Check for jq
if ! command -v jq &> /dev/null
then
    echo "jq could not be found. Please install jq to run this test suite."
    exit 1
fi

# --- Test Execution ---

# 1. Wait for Gateway
print_header "Waiting for API Gateway to become healthy..."
for i in {1..30}; do
    # Check the health endpoint, which is now available thanks to the healthcheck in docker-compose
    if curl -s -f -H "Host: $GATEWAY_HOST" "$GATEWAY_URL/admin/instances" > /dev/null; then
        echo "Gateway is healthy and ready!"
        break
    fi
    echo "Gateway not ready, waiting 2 seconds... (Attempt $i/30)"
    sleep 2
done

if ! curl -s -f -H "Host: $GATEWAY_HOST" "$GATEWAY_URL/admin/instances" > /dev/null; then
    echo "Error: Gateway did not become healthy in time." >&2
    exit 1
fi

# 2. Prune
print_header "Pruning any existing workers for a clean slate"
curl -s -X POST -H "Host: $GATEWAY_HOST" "$GATEWAY_URL/admin/instances/prune" > /dev/null

# 3. Spawn
print_header "Spawning 1 new worker instance"
curl -s -X POST -H "Host: $GATEWAY_HOST" "$GATEWAY_URL/admin/instances/spawn" > /dev/null

# 4. Wait for Worker to be IDLE
print_header "Waiting for worker to become IDLE..."
for i in {1..60}; do # Wait up to 2 minutes for model download
    WORKER_STATUS_JSON=$(curl -s -H "Host: $GATEWAY_HOST" "$GATEWAY_URL/admin/instances")
    echo "Checking worker status: $WORKER_STATUS_JSON"
    # Check if any worker state is IDLE
    if echo "$WORKER_STATUS_JSON" | jq -e '.states | values[] | select(. == "IDLE")' > /dev/null; then
        echo "Worker is IDLE and ready for inference!"
        break
    fi
    echo "Worker not yet ready, waiting 2 seconds... (Attempt $i/60)"
    sleep 2
done

# Final check before proceeding
WORKER_STATUS_JSON=$(curl -s -H "Host: $GATEWAY_HOST" "$GATEWAY_URL/admin/instances")
if ! echo "$WORKER_STATUS_JSON" | jq -e '.states | values[] | select(. == "IDLE")' > /dev/null; then
    echo "Error: Worker did not become IDLE in time." >&2
    echo "Final status: $WORKER_STATUS_JSON"
    exit 1
fi
    echo "Error: Worker did not become IDLE in time." >&2
    echo "Current status:"
    curl -s -H "Host: $GATEWAY_HOST" "$GATEWAY_URL/admin/instances"
    exit 1
fi

# 5. Generate
print_header "Running generation request via gateway"
$CLIENT generate --prompt "Final test successful. The Chimera stack is fully operational."

# 6. Final Prune
print_header "Final cleanup: Pruning worker"
curl -s -X POST -H "Host: $GATEWAY_HOST" "$GATEWAY_URL/admin/instances/prune" > /dev/null

echo -e "\n\033[1;32m####### FINAL TEST SUITE PASSED #######\033[0m"
