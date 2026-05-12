# Build context: DeepSearchStack root (..)
FROM python:3.11-slim

WORKDIR /app

# System deps for Playwright
RUN apt-get update && apt-get install -y \
    wget gnupg libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 \
    libgbm1 libxss1 libasound2 libpangocairo-1.0-0 libpango-1.0-0 \
    libcairo2 libgdk-pixbuf-2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY services/crawler/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN playwright install-deps && playwright install chromium

COPY services/crawler/ .

EXPOSE 8000
CMD ["python", "main.py"]
