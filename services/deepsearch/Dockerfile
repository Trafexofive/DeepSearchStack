# Build context: DeepSearchStack root (..)
# Copies libs/ (shared) + services/deepsearch/
FROM python:3.11-slim

WORKDIR /app

COPY services/deepsearch/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY libs/ /app/libs/
COPY services/deepsearch/ .

ENV PYTHONPATH=/app

EXPOSE 8001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
