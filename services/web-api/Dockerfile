# Build context: DeepSearchStack root (..)
FROM python:3.11-slim

WORKDIR /app

COPY services/web-api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-cache the cross-encoder reranker model (~80 MB) so first-request
# latency stays low. RERANKER_ENABLED=false at runtime disables it; the
# bake step still runs so the image is consistent either way.
ENV TRANSFORMERS_OFFLINE=0 HF_HUB_DISABLE_TELEMETRY=1
RUN python3 -c "from sentence_transformers import CrossEncoder; CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2', max_length=512)" || \
    echo "rerank model pre-cache failed — will download at runtime"

COPY libs/ /app/libs/
COPY services/web-api/ /app/web_api/

ENV PYTHONPATH=/app

EXPOSE 8014
CMD ["uvicorn", "web_api.main:app", "--host", "0.0.0.0", "--port", "8014"]
