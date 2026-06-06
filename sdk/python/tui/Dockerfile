FROM python:3.11-slim

WORKDIR /app

# Install TUI + SDK deps
COPY sdk/python/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# Copy the SDK + TUI source
COPY sdk/python/ /app/sdk/python/
ENV PYTHONPATH=/app/sdk/python

# TUI defaults (overridable at runtime)
ENV DEEPSEARCH_BASE_URL=http://localhost:8083
ENV DEEPSEARCH_MODEL=virtual/free-coder

# Use a TTY-friendly terminal (xterm-256color) for nicer colors
ENV TERM=xterm-256color

# TUI is interactive — needs a TTY
# Run with:  docker compose run --rm dss-tui
# Or:        make tui
ENTRYPOINT ["python", "-m", "tui.app"]
