# Build context: DeepSearchStack root (..)
FROM python:3.11-slim

WORKDIR /app

COPY services/web-api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY libs/ /app/libs/
COPY services/web-api/ /app/web_api/

ENV PYTHONPATH=/app

EXPOSE 8014
CMD ["uvicorn", "web_api.main:app", "--host", "0.0.0.0", "--port", "8014"]
