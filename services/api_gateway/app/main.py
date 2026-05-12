"""
api_gateway — Substrate Omni-Entrypoint

Routes all external requests (TUI, WebUI, Android) to internal services.
Handles JWT auth, CORS, rate limiting, and WebSocket upgrade for event_bus.
"""

import os
import json
import logging
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api_gateway")


# ─── Models ──────────────────────────────────────────────────────────────────

class WorkflowTrigger(BaseModel):
    workflow: str
    params: dict = {}


class HealthResponse(BaseModel):
    status: str
    version: str
    services: dict


# ─── Lifecycle ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("api_gateway starting...")
    # TODO: connect to event_bus, load JWT keys
    yield
    logger.info("api_gateway shutting down...")


app = FastAPI(
    title="Substrate API Gateway",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health():
    """Health check — used by sentinel agent."""
    return HealthResponse(
        status="ok",
        version="0.1.0",
        services={
            "api_gateway": "running",
            "workflow_engine": "unknown",
            "llm_gateway": "unknown",
            "event_bus": "unknown",
        },
    )


@app.post("/api/workflows/trigger")
async def trigger_workflow(payload: WorkflowTrigger):
    """
    Trigger a workflow by name.
    Forwards to workflow_engine for DAG execution.
    """
    logger.info(f"Workflow trigger: {payload.workflow}")
    # TODO: forward to workflow_engine via HTTP/gRPC
    return {
        "status": "accepted",
        "workflow": payload.workflow,
        "params": payload.params,
    }


@app.get("/api/workflows/{workflow_id}/status")
async def workflow_status(workflow_id: str):
    """Poll workflow execution status."""
    # TODO: query workflow_engine for status
    return {"workflow_id": workflow_id, "status": "running"}


@app.post("/api/webhooks/stripe")
async def stripe_webhook(request: Request):
    """Stripe webhook receiver — forwards to broker agent."""
    body = await request.body()
    logger.info(f"Stripe webhook received: {len(body)} bytes")
    # TODO: verify signature, forward to broker agent
    return {"received": True}


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    import uvicorn
    port = int(os.getenv("API_GATEWAY_PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
