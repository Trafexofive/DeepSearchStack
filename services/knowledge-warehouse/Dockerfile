FROM python:3.11-slim

WORKDIR /app

COPY services/knowledge-warehouse/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/knowledge-warehouse/ .

EXPOSE 8009
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8009"]
