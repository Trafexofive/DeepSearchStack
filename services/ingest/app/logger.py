"""Structured JSON logger with request correlation IDs."""

import json
import logging
import sys
import time
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Include 'extra' fields passed via extra={...} kwarg
        if hasattr(record, "extra_fields") and record.extra_fields:
            log_entry.update(record.extra_fields)
        if record.exc_info and record.exc_info[1]:
            log_entry["error"] = str(record.exc_info[1])
        return json.dumps(log_entry)


class StructuredAdapter(logging.LoggerAdapter):
    """Adapter that converts kwargs to extra_fields for JSON logging."""
    def process(self, msg, kwargs):
        extra = kwargs.get("extra", {})
        # Merge all non-standard kwargs into extra_fields
        std_keys = {"exc_info", "extra", "stack_info", "stacklevel"}
        for key in list(kwargs.keys()):
            if key not in std_keys:
                extra[key] = kwargs.pop(key)
        kwargs["extra"] = {"extra_fields": extra}
        return msg, kwargs


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return StructuredAdapter(logger, {})  # type: ignore[return-value]
