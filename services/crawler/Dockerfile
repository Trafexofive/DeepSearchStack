# DeepSearch Crawler — crawl4ai-based web scraper
FROM python:3.11-slim

WORKDIR /app

COPY services/crawler/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN playwright install chromium --with-deps

COPY services/crawler/ .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
