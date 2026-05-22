"""Humanizer SDK — typed async Python client for Substrate's humanizer service.

Usage:
    from humanizer_client import HumanizerClient

    async with HumanizerClient() as hz:
        # Health check
        health = await hz.health()

        # List styles
        styles = await hz.styles()

        # Humanize text
        result = await hz.humanize("AI-generated text here", style="casual", intensity=0.7)
        print(result.text)
        print(f"Confidence: {result.confidence:.2f}")

        # Batch humanize
        results = await hz.humanize_batch([
            {"text": "First text..."},
            {"text": "Second text...", "style": "blunt"},
        ])

        # Get metrics
        metrics = await hz.metrics()
"""

from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import dataclass, field
from typing import Optional

import httpx


# ═══════════════════════════════════════════════════════════════════════════════
# Models
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class HumanizeResult:
    text: str
    model: str = ""
    tokens: int = 0
    pass2_applied: bool = False
    confidence: float = 0.5


@dataclass
class BatchResult:
    results: list[HumanizeResult]
    total_tokens: int


@dataclass
class HealthStatus:
    status: str
    version: str
    model: str
    styles: list[str]
    max_input_length: int
    anti_patterns_count: int


@dataclass
class MetricsSnapshot:
    uptime_seconds: float
    total_requests: int
    total_errors: int
    total_tokens: int
    pass1_tokens: int
    pass2_tokens: int
    pass2_rate: float
    avg_latency_ms: float
    avg_tokens_per_request: float


@dataclass
class StyleInfo:
    name: str
    description: str


# ═══════════════════════════════════════════════════════════════════════════════
# Client
# ═══════════════════════════════════════════════════════════════════════════════

class HumanizerClient:
    """Async client for Substrate's humanizer service."""

    def __init__(self, base_url: str = "http://localhost:8013", timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        self._client = httpx.AsyncClient(timeout=self.timeout)
        return self

    async def __aexit__(self, *args):
        if self._client:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Use as context manager: async with HumanizerClient() as hz:")
        return self._client

    # ── Health ────────────────────────────────────────────────────────────

    async def health(self) -> HealthStatus:
        """GET /health — check service status."""
        r = await self.client.get(f"{self.base_url}/health")
        r.raise_for_status()
        data = r.json()
        return HealthStatus(
            status=data["status"],
            version=data.get("version", "0.1.0"),
            model=data["model"],
            styles=data["styles"],
            max_input_length=data.get("max_input_length", 16384),
            anti_patterns_count=data.get("anti_patterns_count", 0),
        )

    # ── Styles ────────────────────────────────────────────────────────────

    async def styles(self) -> list[StyleInfo]:
        """GET /styles — list available humanization styles."""
        r = await self.client.get(f"{self.base_url}/styles")
        r.raise_for_status()
        return [StyleInfo(name=s["name"], description=s["description"]) for s in r.json()]

    # ── Humanize ──────────────────────────────────────────────────────────

    async def humanize(
        self,
        text: str,
        style: str = "neutral",
        intensity: float = 0.5,
        model: str | None = None,
    ) -> HumanizeResult:
        """POST /humanize — humanize a single text."""
        payload: dict = {
            "text": text,
            "style": style,
            "intensity": intensity,
        }
        if model:
            payload["model"] = model

        r = await self.client.post(f"{self.base_url}/humanize", json=payload)
        r.raise_for_status()
        data = r.json()
        return HumanizeResult(
            text=data["text"],
            model=data["model"],
            tokens=data["tokens"],
            pass2_applied=data["pass2_applied"],
            confidence=data["confidence"],
        )

    # ── Batch ─────────────────────────────────────────────────────────────

    async def humanize_batch(
        self,
        items: list[dict],
        concurrency: int = 3,
    ) -> BatchResult:
        """POST /humanize/batch — humanize multiple texts concurrently.

        Args:
            items: List of dicts with keys: text (required), style, intensity, model.
            concurrency: Max concurrent LLM calls (1-10).
        """
        r = await self.client.post(
            f"{self.base_url}/humanize/batch",
            json={"items": items, "concurrency": concurrency},
        )
        r.raise_for_status()
        data = r.json()
        results = [
            HumanizeResult(
                text=item["text"],
                model=item["model"],
                tokens=item["tokens"],
                pass2_applied=item["pass2_applied"],
                confidence=item["confidence"],
            )
            for item in data["results"]
        ]
        return BatchResult(results=results, total_tokens=data["total_tokens"])

    # ── Metrics ───────────────────────────────────────────────────────────

    async def metrics(self) -> MetricsSnapshot:
        """GET /metrics — token cost & performance metrics."""
        r = await self.client.get(f"{self.base_url}/metrics")
        r.raise_for_status()
        data = r.json()
        return MetricsSnapshot(
            uptime_seconds=data["uptime_seconds"],
            total_requests=data["total_requests"],
            total_errors=data["total_errors"],
            total_tokens=data["total_tokens"],
            pass1_tokens=data["pass1_tokens"],
            pass2_tokens=data["pass2_tokens"],
            pass2_rate=data["pass2_rate"],
            avg_latency_ms=data["avg_latency_ms"],
            avg_tokens_per_request=data["avg_tokens_per_request"],
        )


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

USAGE = """humanizer_client.py — CLI for Substrate humanizer service

Usage:
  python humanizer_client.py health
  python humanizer_client.py styles
  python humanizer_client.py humanize <text> [--style casual] [--intensity 0.7]
  python humanizer_client.py metrics
"""


async def _main():
    if len(sys.argv) < 2:
        print(USAGE)
        sys.exit(1)

    cmd = sys.argv[1]

    async with HumanizerClient() as hz:
        if cmd == "health":
            h = await hz.health()
            print(json.dumps({
                "status": h.status,
                "version": h.version,
                "model": h.model,
                "styles": h.styles,
                "max_input_length": h.max_input_length,
                "anti_patterns_count": h.anti_patterns_count,
            }, indent=2))

        elif cmd == "styles":
            for s in await hz.styles():
                print(f"  {s.name:<18} {s.description}")

        elif cmd == "humanize":
            text = sys.argv[2] if len(sys.argv) > 2 else "Hello"
            style = "neutral"
            intensity = 0.5
            for i, arg in enumerate(sys.argv):
                if arg == "--style" and i + 1 < len(sys.argv):
                    style = sys.argv[i + 1]
                elif arg == "--intensity" and i + 1 < len(sys.argv):
                    intensity = float(sys.argv[i + 1])

            result = await hz.humanize(text, style=style, intensity=intensity)
            print(result.text)
            print(f"\n── tokens={result.tokens} confidence={result.confidence:.2f} pass2={result.pass2_applied}")

        elif cmd == "metrics":
            m = await hz.metrics()
            print(json.dumps({
                "uptime_seconds": m.uptime_seconds,
                "total_requests": m.total_requests,
                "total_errors": m.total_errors,
                "total_tokens": m.total_tokens,
                "pass1_tokens": m.pass1_tokens,
                "pass2_tokens": m.pass2_tokens,
                "pass2_rate": m.pass2_rate,
                "avg_latency_ms": m.avg_latency_ms,
                "avg_tokens_per_request": m.avg_tokens_per_request,
            }, indent=2))

        else:
            print(f"Unknown command: {cmd}\n{USAGE}")
            sys.exit(1)


if __name__ == "__main__":
    asyncio.run(_main())
