#!/bin/bash

# Start the Ollama server in the background
/bin/ollama serve &

# Capture the PID of the server process
SERVER_PID=$!

# Wait a moment for the server to initialize
sleep 5

# Check if the OLLAMA_MODELS_PULL environment variable is set and not empty
if [ -n "$OLLAMA_MODELS_PULL" ]; then
  echo "OLLAMA_MODELS_PULL is set to: $OLLAMA_MODELS_PULL"
  
  # Get the list of already downloaded models
  downloaded_models=$(ollama list | awk 'NR>1 {print $1}')
  echo "Models already downloaded: $downloaded_models"

  # Convert the comma-separated string into an array
  IFS=',' read -r -a models_to_pull <<< "$OLLAMA_MODELS_PULL"

  # Loop through the models and pull them if they are not already downloaded
  for model in "${models_to_pull[@]}"; do
    # Trim whitespace
    model=$(echo "$model" | xargs)
    if [[ ! " ${downloaded_models[@]} " =~ " ${model} " ]]; then
      echo "Pulling model: $model..."
      ollama pull "$model"
    else
      echo "Model $model is already downloaded, skipping."
    fi
  done
else
  echo "OLLAMA_MODELS_PULL is not set. No models will be pulled automatically."
fi

# Wait for the Ollama server process to exit
wait $SERVER_PID
