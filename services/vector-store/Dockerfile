FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir chromadb fastapi uvicorn pydantic

# Pre-fetch the embedding model ONNX (~79 MB from S3) so cold-start is
# instant. Without this, the first /embed or /query triggers the download
# while the service is reported "healthy" — RAG hangs for ~10 minutes.
# We force the default ONNXMiniLM_L6_V2 to materialize its model files.
RUN python3 -c "\
import chromadb, os, shutil; \
os.makedirs('/tmp/warm', exist_ok=True); \
c = chromadb.PersistentClient(path='/tmp/warm'); \
col = c.get_or_create_collection('warmup'); \
col.add(documents=['warm'], ids=['1']); \
col.query(query_texts=['warm'], n_results=1); \
shutil.rmtree('/tmp/warm', ignore_errors=True); \
print('ONNX model cached')"

COPY services/vector-store/main.py .

RUN mkdir -p /app/data

EXPOSE 8004
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8004"]
