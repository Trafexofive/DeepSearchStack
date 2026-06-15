FROM python:3.11-slim

WORKDIR /app

COPY services/knowledge-warehouse/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY libs/ /app/libs/
COPY services/knowledge-warehouse/ .

ENV PYTHONPATH=/app

EXPOSE 8009
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8009"]
