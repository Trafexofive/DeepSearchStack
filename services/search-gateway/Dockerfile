
# ======================================================================
# services/search-gateway/Dockerfile - Definitive
# ======================================================================
FROM python:3.11-slim

WORKDIR /app

# Add the app root to the Python path for module resolution
ENV PYTHONPATH "${PYTHONPATH}:/app"

# Copy and install dependencies
COPY services/search-gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire search-gateway application
COPY services/search-gateway/ /app/search_gateway/

EXPOSE 8002

# Run the application
CMD ["uvicorn", "search_gateway.main:app", "--host", "0.0.0.0", "--port", "8002"]
