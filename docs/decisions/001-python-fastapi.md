# ADR 001: Python/FastAPI as Backend Runtime

**Status**: Accepted  
**Date**: 2026-05-12

## Context
Need a backend runtime for the indie hacker control plane. Services must be async-native, easy to scaffold, and have strong library ecosystems.

## Decision
Use **Python 3.12** with **FastAPI** as the web framework and **uvicorn** as the ASGI server.

## Rationale
- FastAPI is async-native, auto-generates OpenAPI docs, has built-in validation via Pydantic
- Python has excellent libraries for LLM integration (httpx, tenacity), web scraping, data processing
- Single Dockerfile pattern (`FROM python:3.12-slim`) works for every service
- `pip install` is fast and cacheable in Docker layers
- Lower cognitive overhead than Go/Rust for a solo indie hacker

## Alternatives Considered
- **Go + Fiber**: Faster but less library ecosystem for LLM/ML work
- **Node/TypeScript**: Already used for pi-agent; Python gives diversity
- **Rust + Axum**: Overkill for service orchestration, slower to iterate

## Consequences
- All services use the same Python/FastAPI/uvicorn stack
- Docker images share base layers (python:3.12-slim)
- Provider pattern is language-agnostic (any provider that speaks HTTP works)
