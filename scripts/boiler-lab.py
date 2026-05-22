#!/usr/bin/env python3
"""boiler-lab — Scaffold a new Substrate microservice.

Usage:
  python scripts/boiler-lab.py my_service [--port 8015]

Generates a complete, production-ready service skeleton following the
Substrate service pattern (matching humanizer, inference-gateway, etc.):

  services/{name}/
  ├── Dockerfile
  ├── docker-compose.yml
  ├── requirements.txt
  ├── app/
  │   ├── __init__.py
  │   ├── main.py
  │   └── logger.py
  ├── config/.gitkeep
  └── volumes/data/.gitkeep
"""

import argparse
import os
import sys
from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parent.parent / "services"

DOCKERFILE = '''FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ ./app/

EXPOSE {port}

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "{port}"]
'''

COMPOSE = '''services:
  {name}:
    build: .
    ports:
      - "${{{env_var}:-{port}}}:{port}"
    environment:
      - {env_var}={port}
    volumes:
      - ./config:/app/config:ro
      - ./volumes/data:/app/volumes/data
    networks:
      - substrate-net

networks:
  substrate-net:
    external: true
    name: infra_substrate-net
'''

REQUIREMENTS = '''fastapi>=0.110.0
uvicorn>=0.29.0
httpx>=0.27.0
pydantic>=2.6.0
'''

INIT_PY = ''

MAIN_PY = '''"""{name} — Substrate service."""

import os
from fastapi import FastAPI
from app.logger import setup_logger

logger = setup_logger("{name}")

PORT = int(os.environ.get("{env_var}", "{port}"))

app = FastAPI(title="{name}", version="0.1.0")


@app.get("/health")
async def health():
    return {{"status": "ok", "service": "{name}"}}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
'''

LOGGER = '''"""Structured JSON logging with request correlation IDs."""

import logging
import json
import sys
from datetime import datetime, timezone


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if hasattr(record, "rid"):
            log_entry["rid"] = record.rid
        return json.dumps(log_entry)


def setup_logger(name: str, level: str = "INFO") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    logger.handlers = [handler]
    return logger
'''


def snake_case(name: str) -> str:
    return name.lower().replace("-", "_").replace(" ", "_")


def env_var(name: str) -> str:
    return snake_case(name).upper() + "_PORT"


def scaffold(name: str, port: int) -> Path:
    service_dir = SERVICE_ROOT / name
    if service_dir.exists():
        print(f"✖ {service_dir} already exists", file=sys.stderr)
        sys.exit(1)

    env = env_var(name)
    files = {
        "Dockerfile": DOCKERFILE.format(port=port),
        "docker-compose.yml": COMPOSE.format(name=name, env_var=env, port=port),
        "requirements.txt": REQUIREMENTS,
        "app/__init__.py": INIT_PY,
        "app/main.py": MAIN_PY.format(name=name, env_var=env, port=port),
        "app/logger.py": LOGGER,
        "config/.gitkeep": "",
        "volumes/data/.gitkeep": "",
    }

    for rel_path, content in files.items():
        full_path = service_dir / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content)

    return service_dir


def main():
    p = argparse.ArgumentParser(description="Scaffold a new Substrate microservice")
    p.add_argument("name", help="Service name (kebab-case, e.g. my-service)")
    p.add_argument("--port", type=int, default=None,
                   help="Service port (auto-assigned from 8015+ if not specified)")
    args = p.parse_args()

    if args.port is None:
        # Auto-assign next available port
        existing = set()
        for d in SERVICE_ROOT.iterdir():
            if d.is_dir():
                try:
                    for line in (d / "Dockerfile").read_text().splitlines():
                        if "EXPOSE" in line:
                            pn = int(line.split()[-1])
                            existing.add(pn)
                            break
                except (FileNotFoundError, ValueError, IndexError):
                    pass
        port = 8015
        while port in existing:
            port += 1
        if port > 8099:
            print(f"✖ No free ports in 8015-8099 range", file=sys.stderr)
            sys.exit(1)
    else:
        port = args.port

    service_dir = scaffold(args.name, port)
    print(f"✓ Created: {service_dir}/")
    print(f"  Port: {port}")
    print(f"  Files:")
    for f in sorted(service_dir.rglob("*")):
        if f.is_file():
            rel = f.relative_to(service_dir)
            print(f"    {rel}")
    print()
    print(f"  Next steps:")
    print(f"    cd {service_dir}")
    print(f"    # edit app/main.py — add your routes")
    print(f"    make build {args.name}")
    print(f"    make up {args.name}")


if __name__ == "__main__":
    main()
