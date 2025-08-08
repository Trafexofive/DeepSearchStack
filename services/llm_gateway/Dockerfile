# ======================================================================================
# LLM Gateway Dockerfile - Final Version
#
# Base Image: Uses the full `python:3.11` image instead of `slim` to ensure all
# system-level libraries required by dependencies (like google-generativeai's
# grpcio) are present. This resolves the instant-crash issue on startup.
# ======================================================================================

FROM python:3.11

# Set the working directory
WORKDIR /app

# Add the application directory to the Python path to allow for module imports
ENV PYTHONPATH "${PYTHONPATH}:/app"

# Copy and install only the runtime requirements
COPY services/llm_gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code into the container
COPY services/llm_gateway/ ./llm_gateway

# Expose the port the application runs on
EXPOSE 8080

# The command to run the application using Uvicorn
CMD ["uvicorn", "llm_gateway.api_gateway:app", "--host", "0.0.0.0", "--port", "8080"]
