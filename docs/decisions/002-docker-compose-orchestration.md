# ADR 002: Docker Compose for Orchestration

**Status**: Accepted  
**Date**: 2026-05-12

## Context
Need to orchestrate 6+ services with inter-service networking, volume persistence, and environment management. No multi-node deployment required.

## Decision
Use **Docker Compose** with a single `docker-compose.core.yml` in `infra/` and per-service `docker-compose.yml` files for standalone runs.

## Rationale
- Single network (`substrate-net`) connects all services via DNS resolution
- `make up core` boots everything; `make up api_gateway` boots just one
- No Kubernetes complexity needed for a single-machine indie hacker setup
- Volume mounts provide persistent state (SQLite tracker, Redis data)
- `.env` file provides environment variables to all containers
- Makefile v2 provides discovery, monitoring, backup, volume operations

## Network Topology
```
substrate-net (bridge)
├── api_gateway
├── workflow_engine
├── llm_gateway
├── inference_gateway ← blog_generator depends_on this
├── blog_generator
├── event_bus ← api_gateway, workflow_engine depend_on this
├── redis      ← event_bus depends_on this
└── nginx      ← depends_on api_gateway
```

## Consequences
- All services resolve each other by service name (e.g., `http://inference_gateway:8005`)
- Volumes mount local directories for dev iteration
- `make list-stacks` provides a real-time dashboard of all containers
