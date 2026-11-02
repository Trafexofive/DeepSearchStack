# Browser renderer — heavyweight Playwright Chromium service.
# Renders JS-heavy pages, applies a realistic UA + viewport, returns HTML
# plus an optional screenshot. Heavy enough to scale independently from
# the lightweight crawler service.
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

WORKDIR /app

COPY services/browser-renderer/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-cache RapidOCR's ONNX models into the image so cold-start is instant
# (no first-request download). Same anti-pattern as vector-store had — we
# avoid it here by baking the models in.
RUN python3 -c "from rapidocr_onnxruntime import RapidOCR; RapidOCR()" || true

COPY libs/ /app/libs/
COPY services/browser-renderer/ .

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app
EXPOSE 8015
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8015"]
