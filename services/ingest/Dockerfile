FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libxml2 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/output /app/volumes/data

ENV INGEST_CONFIG=/app/config/feeds.yml
ENV INGEST_OUTPUT_DIR=/app/output
ENV INGEST_STATE_DIR=/app/volumes/data

EXPOSE 8008

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8008"]
