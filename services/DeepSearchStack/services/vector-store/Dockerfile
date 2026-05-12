FROM python:3.11-slim

WORKDIR /app

RUN pip install chromadb fastapi uvicorn pydantic

COPY main.py .

EXPOSE 8004

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8004"]