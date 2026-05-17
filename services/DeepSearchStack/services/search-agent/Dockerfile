# Build context: DeepSearchStack root (..)
FROM python:3.11-slim

WORKDIR /app

COPY services/search-agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY libs/ /app/libs/
COPY services/search-agent/ /app/search_agent/

ENV PYTHONPATH=/app

EXPOSE 8013
CMD ["uvicorn", "search_agent.main:app", "--host", "0.0.0.0", "--port", "8013"]
