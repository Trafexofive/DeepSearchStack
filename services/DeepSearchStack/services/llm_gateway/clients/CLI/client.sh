#!/bin/bash

# LLM Gateway CLI Client
# Simple bash client to interact with the LLM Gateway API

set -e  # Exit on any error

# Default configuration
DEFAULT_GATEWAY_URL="http://localhost:8080"
DEFAULT_MODEL="llama-3.1-8b-instant"
DEFAULT_TEMPERATURE=0.7

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Print usage information
usage() {
    echo "Usage: $0 [OPTIONS] MESSAGE"
    echo "Options:"
    echo "  -h, --help              Show this help message"
    echo "  -u, --url GATEWAY_URL   LLM Gateway URL (default: $DEFAULT_GATEWAY_URL)"
    echo "  -m, --model MODEL       Model to use (default: $DEFAULT_MODEL)"
    echo "  -t, --temperature TEMP  Temperature (0.0-2.0, default: $DEFAULT_TEMPERATURE)"
    echo "  -s, --stream            Enable streaming response"
    echo "  -p, --provider PROVIDER Specific provider to use"
    echo "  --routing STRATEGY      Routing strategy (round_robin, least_latency, etc.)"
    echo ""
    echo "Examples:"
    echo "  $0 'Hello, how are you?'"
    echo "  $0 -m 'gemini-2.0-flash' -t 0.9 'Explain quantum computing'"
    echo "  $0 -s -p groq 'Write a poem about AI'"
    exit 1
}

# Parse command line arguments
GATEWAY_URL="$DEFAULT_GATEWAY_URL"
MODEL="$DEFAULT_MODEL"
TEMPERATURE="$DEFAULT_TEMPERATURE"
STREAM=false
PROVIDER=""
ROUTING_STRATEGY=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            usage
            ;;
        -u|--url)
            GATEWAY_URL="$2"
            shift 2
            ;;
        -m|--model)
            MODEL="$2"
            shift 2
            ;;
        -t|--temperature)
            TEMPERATURE="$2"
            shift 2
            ;;
        -s|--stream)
            STREAM=true
            shift
            ;;
        -p|--provider)
            PROVIDER="$2"
            shift 2
            ;;
        --routing)
            ROUTING_STRATEGY="$2"
            shift 2
            ;;
        -*)
            echo -e "${RED}Unknown option: $1${NC}" >&2
            usage
            ;;
        *)
            break
            ;;
    esac
done

# The remaining argument is the message
if [ $# -eq 0 ]; then
    echo -e "${RED}Error: No message provided${NC}" >&2
    usage
fi

MESSAGE="$*"

# Function to send request to LLM Gateway
send_completion_request() {
    local gateway_url="$1"
    local message="$2"
    local model="$3"
    local temperature="$4"
    local stream="$5"
    local provider="$6"
    local routing_strategy="$7"
    
    # Prepare JSON payload
    local json_payload
    json_payload=$(cat <<EOF
{
    "messages": [
        {
            "role": "user",
            "content": "$message"
        }
    ],
    "model": "$model",
    "temperature": $temperature,
    "stream": $stream
EOF
)

    # Add provider if specified
    if [ -n "$provider" ]; then
        json_payload=$(echo "$json_payload" | sed "s/}$/,\"provider\":\"$provider\"}/")
    fi

    # Add routing strategy if specified
    if [ -n "$routing_strategy" ]; then
        json_payload=$(echo "$json_payload" | sed "s/}$/,\"routing_strategy\":\"$routing_strategy\"}/")
    fi

    json_payload="${json_payload}}"

    echo -e "${BLUE}Sending request to: $gateway_url${NC}"
    echo -e "${BLUE}Message: $message${NC}"
    
    if [ "$stream" = true ]; then
        # For streaming, we'll just send the request and display the response as-is
        curl -s -X POST "$gateway_url/v1/completions" \
            -H "Content-Type: application/json" \
            -d "$json_payload"
        echo
    else
        # For non-streaming, process the response
        response=$(curl -s -X POST "$gateway_url/v1/completions" \
            -H "Content-Type: application/json" \
            -d "$json_payload")
        
        # Extract content from the response
        content=$(echo "$response" | python3 -c "import sys, json; print(json.load(sys.stdin).get('content', 'Error: No content in response'))" 2>/dev/null || echo "$response")
        
        if [ "$content" = "$response" ]; then
            # If the content is the same as the whole response, it means there was an error
            echo -e "${RED}Error response:${NC}"
            echo "$response" | python3 -m json.tool
        else
            echo -e "${GREEN}Response:${NC}"
            echo "$content"
        fi
    fi
}

# Validate temperature range
if (( $(echo "$TEMPERATURE < 0.0" | bc -l) )) || (( $(echo "$TEMPERATURE > 2.0" | bc -l) )); then
    echo -e "${RED}Error: Temperature must be between 0.0 and 2.0${NC}" >&2
    exit 1
fi

# Check if curl is available
if ! command -v curl &> /dev/null; then
    echo -e "${RED}Error: curl is required but not installed.${NC}" >&2
    exit 1
fi

# Check if bc is available for temperature validation
if ! command -v bc &> /dev/null; then
    echo -e "${YELLOW}Warning: bc not found. Skipping temperature validation.${NC}" >&2
fi

# Check if python3 is available for JSON parsing
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: python3 is required for JSON parsing but not installed.${NC}" >&2
    exit 1
fi

# Send request to LLM Gateway
send_completion_request "$GATEWAY_URL" "$MESSAGE" "$MODEL" "$TEMPERATURE" "$STREAM" "$PROVIDER" "$ROUTING_STRATEGY"