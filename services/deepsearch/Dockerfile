FROM python:3.11-slim

WORKDIR /app

COPY services/deepsearch/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the libs (common library)
COPY libs /app/libs

COPY services/deepsearch/ .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8001"]
