# ======================================================================
# services/web-api/Dockerfile - Definitive Flawless Version
# ======================================================================
FROM python:3.11-slim

WORKDIR /app

# Add the app root to the Python path
ENV PYTHONPATH "${PYTHONPATH}:/app"

# Copy and install its own dependencies
COPY services/web-api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy only its own application code
COPY services/web-api/ /app/web_api/

EXPOSE 8000

# Run the application using its correct module path
CMD ["uvicorn", "web_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
