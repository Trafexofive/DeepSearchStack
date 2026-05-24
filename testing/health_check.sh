#!/bin/bash
# testing/health_check.sh

# Exit immediately if a command exits with a non-zero status.
set -e

# Define variables
BASE_URL=${1:-http://llm-gateway:8080}
HEALTH_ENDPOINT="/health"
MAX_RETRIES=10
RETRY_INTERVAL=5

# Function to check the health of the LLM Gateway
check_health() {
    echo "Pinging LLM Gateway at ${BASE_URL}${HEALTH_ENDPOINT}..."
    for i in $(seq 1 $MAX_RETRIES); do
        response=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}${HEALTH_ENDPOINT}")
        if [ "$response" -eq 200 ]; then
            echo "LLM Gateway is healthy! (HTTP Status: $response)"
            exit 0
        else
            echo "Attempt $i of $MAX_RETRIES failed. Retrying in $RETRY_INTERVAL seconds..."
            sleep $RETRY_INTERVAL
        fi
    done

    echo "LLM Gateway is unhealthy after $MAX_RETRIES attempts."
    exit 1
}

# Run the health check
check_health
