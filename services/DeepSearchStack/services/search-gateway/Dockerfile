# Build context: DeepSearchStack root (..)
FROM python:3.11-slim

WORKDIR /app

COPY services/search-gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY libs/ /app/libs/
COPY services/search-gateway/ /app/search_gateway/

ENV PYTHONPATH=/app

EXPOSE 8002
CMD ["uvicorn", "search_gateway.main:app", "--host", "0.0.0.0", "--port", "8002"]
