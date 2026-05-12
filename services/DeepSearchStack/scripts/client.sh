#!/bin/bash
# ======================================================================================
# DeepSearchStack - Advanced Command-Line Client v2.2 (Definitive)
#
# A powerful CLI to interact with all core features of the DeepSearchStack.
# Requires: curl, jq
# ======================================================================================

# --- Configuration (can be overridden with environment variables) ---
BASE_URL=${BASE_URL:-http://localhost}
SEARCH_AGENT_URL="${BASE_URL}/agent"
LLM_GATEWAY_URL="${BASE_URL}/llm"

# --- Colors for better output ---
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# --- Helper Functions ---

check_deps() {
    for cmd in curl jq; do
        if ! command -v $cmd &> /dev/null; then
            echo -e "${RED}Error: Required command '$cmd' is not installed.${NC}" >&2
            echo "Please install it to continue." >&2
            exit 1
        fi
    done
}

usage() {
    echo -e "${BLUE}DeepSearchStack Advanced Command-Line Client${NC}"
    echo "---------------------------------------------"
    echo -e "${YELLOW}Usage:${NC} $0 [command] [options] \"<query>\""
    echo ""
    echo -e "${GREEN}Core Commands:${NC}"
    echo "  ${YELLOW}search${NC} \"<query>\"      Perform a full, end-to-end search and synthesis."
    echo "    Options:"
    echo "      --stream              Enable streaming response for the answer."
    echo "      --llm-provider <name>   Specify an LLM provider to synthesize the answer (e.g., ollama, groq)."
    echo "      -p, --providers <list>  Comma-separated list of search providers (e.g., whoogle,searxng)."
    echo "      -n, --max-results <num> Limit the number of sources used for the answer (default: 10)."
    echo "      --sort <method>       Sort results by 'relevance', 'date', or 'source_quality'."
    echo ""
    echo "  ${YELLOW}ask${NC} \"<prompt>\"         Send a direct query to the LLM Gateway."
    echo "    Options:"
    echo "      --stream              Enable streaming response from the LLM."
    echo "      -p, --provider <name>   Specify an LLM provider (e.g., ollama, groq, gemini)."
    echo "      --system \"<prompt>\"   Set a system prompt for the LLM."
    echo "      -t, --temp <float>      Set the temperature for the LLM (e.g., 0.8)."
    echo ""
    echo -e "${GREEN}Utility Commands:${NC}"
    echo "  ${YELLOW}health${NC}                 Check the health status of all core services."
    echo "  ${YELLOW}llm-providers${NC}          List available LLM providers from the gateway."
    echo "  ${YELLOW}search-providers${NC}       List available search providers from the agent."
    echo "  ${YELLOW}metrics${NC}                Fetch performance metrics from the search agent."
    echo "  ${YELLOW}help${NC}                   Show this help message."
    echo ""
    echo -e "${YELLOW}Examples:${NC}"
    echo "  $0 search \"What is the latest news on the James Webb Telescope?\" --stream"
    echo "  $0 search \"Benefits of Rust vs Go\" --llm-provider groq -p whoogle,brave -n 5"
    echo "  $0 ask \"Write a python function to find prime numbers\" --provider ollama --stream"
}

# --- Command Functions ---

cmd_health() {
    echo -e "${BLUE}--- Checking Service Health ---${NC}"
    for service in "Search Agent" "LLM Gateway"; do
        if [ "$service" = "Search Agent" ]; then
            url="${BASE_URL}/agent/health"
        else
            url="${BASE_URL}/llm/health"
        fi
        
        echo -n -e "${YELLOW}Pinging ${service}...${NC} "
        http_code=$(curl -s -o /dev/null -w "%{http_code}" "$url" || echo "000")
        
        if [ "$http_code" -eq 200 ]; then
            echo -e "${GREEN}Healthy (200 OK)${NC}"
        else
            echo -e "${RED}Unhealthy (HTTP ${http_code})${NC}"
        fi
    done
}

cmd_llm_providers() {
    echo -e "${BLUE}--- Available LLM Providers ---${NC}"
    curl -s "${LLM_GATEWAY_URL}/providers" | jq . || echo -e "${RED}Could not fetch providers from LLM Gateway.${NC}" >&2
}

cmd_search_providers() {
    echo -e "${BLUE}--- Available Search Providers ---${NC}"
    curl -s "${SEARCH_AGENT_URL}/providers" | jq . || echo -e "${RED}Could not fetch providers from Search Agent.${NC}" >&2
}

cmd_metrics() {
    echo -e "${BLUE}--- Search Agent Metrics ---${NC}"
    curl -s "${SEARCH_AGENT_URL}/metrics" | jq . || echo -e "${RED}Could not fetch metrics from Search Agent.${NC}" >&2
}

cmd_search() {
    # Defaults
    STREAM=false
    PROVIDERS="null"
    MAX_RESULTS="null"
    SORT_METHOD="null"
    LLM_PROVIDER="null"
    QUERY=""

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --stream) STREAM=true; shift ;;
            -p|--providers) PROVIDERS="$2"; shift 2 ;;
            -n|--max-results) MAX_RESULTS="$2"; shift 2 ;;
            --sort) SORT_METHOD="$2"; shift 2 ;;
            --llm-provider) LLM_PROVIDER="$2"; shift 2 ;;
            *) QUERY="$1"; shift ;;
        esac
    done

    if [ -z "$QUERY" ]; then
        echo -e "${RED}Error: A search query is required.${NC}" >&2; usage; exit 1;
    fi

    echo -e "${YELLOW}Submitting query to Search Agent (this may take a moment)...${NC}"
    
    PAYLOAD=$(jq -n \
        --arg query "$QUERY" \
        --argjson stream "$STREAM" \
        --arg providers "$PROVIDERS" \
        --arg max_results "$MAX_RESULTS" \
        --arg sort "$SORT_METHOD" \
        --arg llm_provider "$LLM_PROVIDER" \
        '{query: $query, stream: $stream} +
         (if $providers != "null" then {providers: ($providers | split(","))} else {} end) +
         (if $max_results != "null" then {max_results: ($max_results | tonumber)} else {} end) +
         (if $sort != "null" then {sort_by: $sort} else {} end) +
         (if $llm_provider != "null" then {llm_provider: $llm_provider} else {} end)'
    )

    if [ "$STREAM" = true ]; then
        URL="${SEARCH_AGENT_URL}/search/stream"
        echo -e "\n${GREEN}Answer (streaming):${NC}"
        curl -s -N -X POST -H "Content-Type: application/json" -d "$PAYLOAD" "$URL" | \
        while IFS= read -r line; do
            if [[ $line == data:* ]]; then
                data_json="${line#data:}"
                
                is_finished=$(echo "$data_json" | jq -r '.finished')
                
                if [ "$is_finished" = "true" ]; then
                    echo -e "\n\n${BLUE}Sources:${NC}"
                    echo "$data_json" | jq -r '.sources[] | "- \(.title): \(.url)"'
                    break
                else
                    echo -n "$(echo "$data_json" | jq -r '.content')"
                fi
            fi
        done
        echo ""
    else
        URL="${SEARCH_AGENT_URL}/search"
        RESPONSE=$(curl -s -X POST -H "Content-Type: application/json" -d "$PAYLOAD" "$URL")
        
        if ! echo "$RESPONSE" | jq -e 'has("answer")' >/dev/null 2>&1; then
            echo -e "${RED}Error: Received invalid or error response from the Search Agent.${NC}" >&2; echo "Response:" >&2; echo "$RESPONSE" | jq . >&2; exit 1;
        fi

        echo -e "\n${GREEN}Answer:${NC}"
        echo "$RESPONSE" | jq -r '.answer'

        echo -e "\n${BLUE}Sources:${NC}"
        echo "$RESPONSE" | jq -r '.sources[] | "- \(.title): \(.url)"'
    fi
}

cmd_ask() {
    # Defaults
    STREAM=false
    PROVIDER="null"
    SYSTEM_PROMPT="null"
    TEMPERATURE="null"
    PROMPT=""

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --stream) STREAM=true; shift ;;
            -p|--provider) PROVIDER="$2"; shift 2 ;;
            --system) SYSTEM_PROMPT="$2"; shift 2 ;;
            -t|--temp) TEMPERATURE="$2"; shift 2 ;;
            *) PROMPT="$1"; shift ;;
        esac
    done

    if [ -z "$PROMPT" ]; then
        echo -e "${RED}Error: A prompt is required.${NC}" >&2; usage; exit 1;
    fi

    echo -e "${YELLOW}Asking LLM Gateway...${NC}"

    MESSAGES=$(jq -n \
        --arg system_prompt "$SYSTEM_PROMPT" \
        --arg user_prompt "$PROMPT" \
        '
        (if $system_prompt != "null" then [{role: "system", content: $system_prompt}] else [] end) +
        [{role: "user", content: $user_prompt}]
        '
    )

    PAYLOAD=$(jq -n \
        --argjson messages "$MESSAGES" \
        --argjson stream "$STREAM" \
        --arg provider "$PROVIDER" \
        --arg temp "$TEMPERATURE" \
        '{messages: $messages, stream: $stream} +
         (if $provider != "null" then {provider: $provider} else {} end) +
         (if $temp != "null" then {temperature: ($temp | tonumber)} else {} end)'
    )

    if [ "$STREAM" = true ]; then
        echo -e "\n${GREEN}Response (streaming):${NC}"
        curl -s -N -X POST -H "Content-Type: application/json" -d "$PAYLOAD" "${LLM_GATEWAY_URL}/completion" | \
        while IFS= read -r line; do
            if [[ $line == data:* ]]; then
                data_json="${line#data:}"
                
                content_chunk=$(echo "$data_json" | jq -r '.content // ""')
                echo -n "$content_chunk"

                if echo "$data_json" | jq -e '.error' >/dev/null; then
                    error_msg=$(echo "$data_json" | jq -r '.error')
                    echo -e "\n${RED}Error during stream: $error_msg${NC}" >&2
                fi
            fi
        done
        echo ""
    else
        RESPONSE=$(curl -s -X POST -H "Content-Type: application/json" -d "$PAYLOAD" "${LLM_GATEWAY_URL}/completion")
        
        if ! echo "$RESPONSE" | jq -e 'has("content")' >/dev/null 2>&1; then
            echo -e "${RED}Error: Received invalid or error response from the LLM Gateway.${NC}" >&2; echo "Response:" >&2; echo "$RESPONSE" | jq . >&2; exit 1;
        fi
        
        echo -e "\n${GREEN}Response:${NC}"
        echo "$RESPONSE" | jq -r '.content'
    fi
}

# --- Main Logic ---

check_deps

COMMAND=$1
if [ -z "$COMMAND" ]; then
    usage
    exit 1
fi
shift

case "$COMMAND" in
    search)
        cmd_search "$@"
        ;;
    ask)
        cmd_ask "$@"
        ;;
    health)
        cmd_health
        ;;
    llm-providers)
        cmd_llm_providers
        ;;
    search-providers)
        cmd_search_providers
        ;;
    metrics)
        cmd_metrics
        ;;
    help|*)
        usage
        ;;
esac
