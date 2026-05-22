"""Humanizer Service — LLM text humanization API.

Endpoints:
  GET  /health              — service health
  GET  /styles              — list available humanization styles
  GET  /metrics             — token cost & performance metrics
  POST /humanize            — humanize a single text
  POST /humanize/batch      — humanize multiple texts concurrently
"""

import os
import asyncio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from typing import Optional

from app.humanizer import (
    humanize,
    HumanizeResult,
    metrics,
    DEFAULT_MODEL,
    MAX_INPUT_LENGTH,
    get_anti_patterns,
)
from app.logger import setup_logger

logger = setup_logger("humanizer-api")

app = FastAPI(
    title="Substrate Humanizer",
    version="0.2.0",
    description="Two-pass LLM text humanization with confidence scoring. Mission-agnostic.",
)

AVAILABLE_STYLES = ["neutral", "casual", "professional", "blunt", "conversational"]


# ═══════════════════════════════════════════════════════════════════════════════
# Models
# ═══════════════════════════════════════════════════════════════════════════════

class HumanizeRequest(BaseModel):
    text: str = Field(
        ...,
        min_length=1,
        max_length=MAX_INPUT_LENGTH,
        description=f"Text to humanize. Max {MAX_INPUT_LENGTH} chars.",
    )
    style: str = Field(
        default="neutral",
        description=f"Humanization style. One of: {AVAILABLE_STYLES}",
    )
    intensity: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="How aggressively to humanize. 0=barely, 0.5=moderate, 1.0=aggressive.",
    )
    model: Optional[str] = Field(
        default=None,
        description="Override model (format: 'provider:model_id'). Default from HUMANIZER_MODEL env.",
    )


class HumanizeResponse(BaseModel):
    text: str
    model: str
    tokens: int
    pass2_applied: bool
    confidence: float = Field(..., ge=0.0, le=1.0, description="Humanization confidence score")


class BatchHumanizeRequest(BaseModel):
    items: list[HumanizeRequest] = Field(..., min_length=1, max_length=20)
    concurrency: int = Field(default=3, ge=1, le=10, description="Max concurrent LLM calls")


class BatchHumanizeResponse(BaseModel):
    results: list[HumanizeResponse]
    total_tokens: int


class StyleInfo(BaseModel):
    name: str
    description: str


STYLE_DESCRIPTIONS = {
    "neutral": "Default — natural human prose, no strong stylistic tilt.",
    "casual": "Like texting a friend. Slang, contractions, loose structure.",
    "professional": "Confident and direct, like a senior engineer explaining something. No corporate fluff.",
    "blunt": "No pleasantries. Short sentences. Straight to the point.",
    "conversational": "Like talking over coffee. Rhetorical questions, personal tone.",
}


# ═══════════════════════════════════════════════════════════════════════════════
# Exception handler — 413 for oversized input
# ═══════════════════════════════════════════════════════════════════════════════

@app.exception_handler(413)
async def payload_too_large_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=413,
        content={
            "error": "payload_too_large",
            "detail": f"Input text exceeds maximum length of {MAX_INPUT_LENGTH} characters.",
            "max_length": MAX_INPUT_LENGTH,
        },
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Routes
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "humanizer",
        "version": "0.2.0",
        "model": DEFAULT_MODEL,
        "inference_url": os.getenv("INFERENCE_URL", "http://inference_gateway:8005/v1/chat/completions"),
        "styles": AVAILABLE_STYLES,
        "max_input_length": MAX_INPUT_LENGTH,
        "anti_patterns_count": len(get_anti_patterns()),
    }


@app.get("/styles", response_model=list[StyleInfo])
async def list_styles():
    return [
        StyleInfo(name=name, description=STYLE_DESCRIPTIONS.get(name, ""))
        for name in AVAILABLE_STYLES
    ]


@app.get("/metrics")
async def get_metrics():
    """Return cumulative token cost & performance metrics."""
    snap = metrics.snapshot()
    snap["max_input_length"] = MAX_INPUT_LENGTH
    snap["anti_patterns_count"] = len(get_anti_patterns())
    snap["model"] = DEFAULT_MODEL
    return snap


@app.post("/humanize", response_model=HumanizeResponse)
async def humanize_endpoint(req: HumanizeRequest):
    if req.style not in AVAILABLE_STYLES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown style '{req.style}'. Available: {AVAILABLE_STYLES}",
        )

    # Explicit length check (Pydantic handles max_length, but double-check)
    if len(req.text) > MAX_INPUT_LENGTH:
        raise HTTPException(
            status_code=413,
            detail=f"Input text ({len(req.text)} chars) exceeds maximum ({MAX_INPUT_LENGTH} chars).",
        )

    model = req.model or DEFAULT_MODEL

    try:
        result: HumanizeResult = await humanize(
            text=req.text,
            style=req.style,
            intensity=req.intensity,
            model=model,
        )
    except Exception as e:
        logger.error("Humanize failed: %s", str(e))
        metrics.record_error()
        raise HTTPException(status_code=502, detail=f"Inference error: {str(e)}")

    return HumanizeResponse(
        text=result.text,
        model=result.model,
        tokens=result.total_tokens,
        pass2_applied=result.pass2_applied,
        confidence=result.confidence,
    )


@app.post("/humanize/batch", response_model=BatchHumanizeResponse)
async def humanize_batch(req: BatchHumanizeRequest):
    sem = asyncio.Semaphore(req.concurrency)

    async def _one(item: HumanizeRequest) -> HumanizeResult:
        async with sem:
            model = item.model or DEFAULT_MODEL
            if item.style not in AVAILABLE_STYLES:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown style '{item.style}'. Available: {AVAILABLE_STYLES}",
                )
            if len(item.text) > MAX_INPUT_LENGTH:
                raise HTTPException(
                    status_code=413,
                    detail=f"Input text ({len(item.text)} chars) exceeds maximum ({MAX_INPUT_LENGTH} chars).",
                )
            return await humanize(
                text=item.text,
                style=item.style,
                intensity=item.intensity,
                model=model,
            )

    try:
        results: list[HumanizeResult] = await asyncio.gather(
            *[_one(item) for item in req.items]
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Batch humanize failed: %s", str(e))
        metrics.record_error()
        raise HTTPException(status_code=502, detail=f"Inference error: {str(e)}")

    responses = [
        HumanizeResponse(
            text=r.text,
            model=r.model,
            tokens=r.total_tokens,
            pass2_applied=r.pass2_applied,
            confidence=r.confidence,
        )
        for r in results
    ]
    total = sum(r.total_tokens for r in results)

    return BatchHumanizeResponse(results=responses, total_tokens=total)
