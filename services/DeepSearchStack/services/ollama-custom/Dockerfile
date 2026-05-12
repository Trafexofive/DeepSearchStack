# Use the official Ollama image as the base
FROM ollama/ollama:latest

# Copy the custom entrypoint script into the container
COPY services/ollama-custom/entrypoint.sh /entrypoint.sh

# Make the script executable
RUN chmod +x /entrypoint.sh

# Set the custom script as the entrypoint
ENTRYPOINT ["/entrypoint.sh"]