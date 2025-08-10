# ======================================================================
# services/search-agent/Dockerfile - Definitive Flawless Version
# ======================================================================
FROM python:3.11-slim

WORKDIR /app

# Add the app root to the Python path to enable correct module resolution
ENV PYTHONPATH "${PYTHONPATH}:/app"

# Copy requirements and install dependencies
COPY services/search-agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire self-contained search-agent application
COPY services/search-agent/ /app/search_agent/

EXPOSE 8001

# Run the application using its correct module path
CMD ["uvicorn", "search_agent.main:app", "--host", "0.0.0.0", "--port", "8001"]
