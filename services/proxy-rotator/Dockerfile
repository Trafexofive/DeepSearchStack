FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tor \
    privoxy \
    tinyproxy \
    && rm -rf /var/lib/apt/lists/* \
    && mkdir -p /var/run/tinyproxy /var/log/tinyproxy /var/run/tor \
    && chown nobody:nogroup /var/run/tinyproxy /var/log/tinyproxy

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .

# Tor data dir for persistence across restarts
VOLUME ["/tmp/tor"]

EXPOSE 8888 8030 9050 8118

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8030"]
