FROM python:3.11-slim

WORKDIR /app

RUN pip install fastapi uvicorn

COPY services/web-api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/web-api/main.py .

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
