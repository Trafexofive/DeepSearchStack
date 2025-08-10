#!/bin/bash

# ======================================================================================
# Ollama API Client - Forged by Gemini
#
# A comprehensive and well-documented client for interacting with the Ollama API.
# ======================================================================================

# --- Configuration ---
# OLLAMA_HOST is the actual address to connect to (e.g., localhost)
# TRAEFIK_HOST is the domain name Traefik uses for routing (e.g., api.localhost)
OLLAMA_HOST=${OLLAMA_HOST:-localhost}
PORT=${OLLAMA_PORT:-80}
TRAEFIK_HOST=${TRAEFIK_HOST:-${OLLAMA_HOST}}
API_URL="http://${OLLAMA_HOST}:${PORT}/api"

# --- Helper Functions ---

# Function to print headers
print_header() {
    echo -e "\n\033[1;34m====== $1 ======\033[0m"
}

# Function to make curl requests
make_request() {
    local method=$1
    local endpoint=$2
    local data=$3

    print_header "Request: $method $API_URL$endpoint"
    echo "Data: $data"

    if [ -z "$data" ]; then
        curl -s -X $method -H "Host: ${TRAEFIK_HOST}" "$API_URL$endpoint"
    else
        curl -s -X $method -H "Host: ${TRAEFIK_HOST}" -d "$data" "$API_URL$endpoint"
    fi
    echo -e "\n"
}

# --- API Commands ---

# Generate a completion
generate() {
    local model="gemma:2b"
    local prompt="Why is the sky blue?"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --model)
                model="$2"
                shift 2
                ;;
            --prompt)
                prompt="$2"
                shift 2
                ;;
            *)
                echo "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    make_request "POST" "/generate" "{\"model\": \"$model\", \"prompt\": \"$prompt\"}"
}

# Chat with a model
chat() {
    local model="gemma:2b"
    local message="Hello!"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --model)
                model="$2"
                shift 2
                ;;
            --message)
                message="$2"
                shift 2
                ;;
            *)
                echo "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    make_request "POST" "/chat" "{\"model\": \"$model\", \"messages\": [{\"role\": \"user\", \"content\": \"$message\"}]}"
}

# List local models
list_models() {
    make_request "GET" "/tags"
}

# Show model information
show_model_info() {
    local model="gemma:2b"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --model)
                model="$2"
                shift 2
                ;;
            *)
                echo "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    make_request "POST" "/show" "{\"name\": \"$model\"}"
}

# Copy a model
copy_model() {
    local source="gemma:2b"
    local destination="gemma:2b-copy"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --source)
                source="$2"
                shift 2
                ;;
            --destination)
                destination="$2"
                shift 2
                ;;
            *)
                echo "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    make_request "POST" "/copy" "{\"source\": \"$source\", \"destination\": \"$destination\"}"
}

# Delete a model
delete_model() {
    local model="gemma:2b-copy"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --model)
                model="$2"
                shift 2
                ;;
            *)
                echo "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    make_request "DELETE" "/delete" "{\"name\": \"$model\"}"
}

# Pull a model
pull_model() {
    local model="gemma:7b"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --model)
                model="$2"
                shift 2
                ;;
            *)
                echo "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    make_request "POST" "/pull" "{\"name\": \"$model\"}"
}

# Push a model
push_model() {
    local model="gemma:2b-copy"
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --model)
                model="$2"
                shift 2
                ;;
            *)
                echo "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    make_request "POST" "/push" "{\"name\": \"$model\"}"
}

# Create a model from a Modelfile
create_model() {
    local name="my-custom-model"
    local modelfile_content="FROM gemma:2b\nSYSTEM \"You are a helpful assistant.\""
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --name)
                name="$2"
                shift 2
                ;;
            --modelfile)
                modelfile_content="$(cat $2)"
                shift 2
                ;;
            *)
                echo "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    make_request "POST" "/create" "{\"name\": \"$name\", \"modelfile\": \"$modelfile_content\"}"
}

# --- Help Message ---

usage() {
    echo "Usage: $0 <command> [options]"
    echo ""
    echo "Commands:"
    echo "  generate      Generate a completion from a model."
    echo "  chat          Have a conversation with a model."
    echo "  list          List all local models."
    echo "  show          Show information about a model."
    echo "  copy          Copy a model."
    echo "  delete        Delete a model."
    echo "  pull          Pull a model from a registry."
    echo "  push          Push a model to a registry."
    echo "  create        Create a model from a Modelfile."
    echo "  help          Show this help message."
    echo ""
    echo "Options for generate:"
    echo "  --model       The model to use (default: gemma:2b)."
    echo "  --prompt      The prompt to use (default: 'Why is the sky blue?')."
    echo ""
    echo "Options for chat:"
    echo "  --model       The model to use (default: gemma:2b)."
    echo "  --message     The message to send (default: 'Hello!')."
    echo ""
    echo "Options for show, delete, pull, push:"
    echo "  --model       The model to use."
    echo ""
    echo "Options for copy:"
    echo "  --source      The source model."
    echo "  --destination The destination model."
    echo ""
    echo "Options for create:"
    echo "  --name        The name of the new model."
    echo "  --modelfile   The path to the Modelfile."
}

# --- Main Logic ---

if [ "$1" == "-h" ] || [ "$1" == "--help" ]; then
    usage
    exit 0
fi

COMMAND=$1
shift

case "$COMMAND" in
    generate)
        generate "$@"
        ;;
    chat)
        chat "$@"
        ;;
    list)
        list_models
        ;;
    show)
        show_model_info "$@"
        ;;
    copy)
        copy_model "$@"
        ;;
    delete)
        delete_model "$@"
        ;;
    pull)
        pull_model "$@"
        ;;
    push)
        push_model "$@"
        ;;
    create)
        create_model "$@"
        ;;
    help)
        usage
        ;;
    *)
        usage
        exit 1
        ;;
esac