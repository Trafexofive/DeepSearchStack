#!/bin/bash

# ======================================================================================
# Ollama API Force Test Client - Forged by Gemini
#
# A script to rigorously test the Ollama API with various arguments.
#
# Usage:
#   ./force_test_client.sh
#
# ======================================================================================

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
CLIENT="./scripts/client.sh"

# --- Helper Functions ---

# Function to print test headers
print_test_header() {
    echo -e "\n\033[1;35m####### TESTING: $1 #######\033[0m"
}

# --- Test Execution ---

print_test_header "Displaying help message"
$CLIENT --help

print_test_header "Listing initial models"
$CLIENT list

print_test_header "Generating with default model"
$CLIENT generate

print_test_header "Generating with a specific model and prompt"
$CLIENT generate --model "gemma:2b" --prompt "Tell me a joke."

print_test_header "Chatting with the default model"
$CLIENT chat

print_test_header "Chatting with a specific model and message"
$CLIENT chat --model "gemma:2b" --message "What is the meaning of life?"

print_test_header "Showing info for a specific model"
$CLIENT show --model "gemma:2b"

print_test_header "Copying a model"
$CLIENT copy --source "gemma:2b" --destination "gemma:2b-test-copy"

print_test_header "Listing models after copy"
$CLIENT list

print_test_header "Showing info for the copied model"
$CLIENT show --model "gemma:2b-test-copy"

print_test_header "Deleting the copied model"
$CLIENT delete --model "gemma:2b-test-copy"

print_test_header "Listing models after delete"
$CLIENT list

print_test_header "Pulling a new model"
$CLIENT pull --model "gemma:7b"

print_test_header "Listing models after pull"
$CLIENT list

print_test_header "Creating a new model from a Modelfile"
echo -e "FROM gemma:2b\nSYSTEM \"You are a testing assistant.\"" > Modelfile.test
$CLIENT create --name "my-test-model" --modelfile "Modelfile.test"

print_test_header "Listing models after create"
$CLIENT list

print_test_header "Showing info for the new model"
$CLIENT show --model "my-test-model"

print_test_header "Deleting the new model"
$CLIENT delete --model "my-test-model"

print_test_header "Final model list"
$CLIENT list

rm Modelfile.test

echo -e "\n\033[1;32m####### ALL TESTS COMPLETE #######\033[0m"
