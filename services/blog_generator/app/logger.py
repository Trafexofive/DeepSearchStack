"""Structured JSON logging with request correlation IDs."""

import logging
import json
import sys
import uuid
from datetime import datetime, timezone
from typing import Optional


class JSONFormatter(logging.Formatter):
    """Emit log records as single-line JSON."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "rid": getattr(record, "rid", None),
            "module": record.module,
            "line": record.lineno,
        }
        if record.exc_info and record.exc_info[1]:
            entry["exc"] = str(record.exc_info[1])
        return json.dumps(entry, default=str)


def init_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    # Remove any existing handlers to avoid duplicates
    root.handlers = [handler]


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]


class RequestLogger(logging.LoggerAdapter):
    """Logger adapter that injects a request ID into every log record."""

    def __init__(self, logger: logging.Logger, rid: str):
        super().__init__(logger, {"rid": rid})

    def process(self, msg, kwargs):
        kwargs["extra"] = kwargs.get("extra", {})
        kwargs["extra"]["rid"] = self.extra["rid"]
        return msg, kwargs
