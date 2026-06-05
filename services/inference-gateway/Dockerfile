# Build context: DeepSearchStack root (..)
FROM python:3.12-slim

WORKDIR /app

COPY services/inference-gateway/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY libs/ /app/libs/
COPY services/inference-gateway/ /app/

EXPOSE 8005

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8005"]
