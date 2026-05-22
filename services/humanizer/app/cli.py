"""Humanizer CLI — humanize text from the command line.

Usage:
  python -m app.cli --text "AI-generated text here" --style blunt
  python -m app.cli --text "AI-generated text here" --style casual --intensity 0.8
  python -m app.cli --file input.txt --style professional
  python -m app.cli --text "..." --metrics   # show metrics after humanizing
  python -m app.cli --styles                 # list available styles
  python -m app.cli --health                 # health check
  python -m app.cli --metrics-only           # just show metrics
"""

import argparse
import asyncio
import json
import os
import sys

# Allow running as module from service dir
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.humanizer import humanize, metrics, DEFAULT_MODEL, get_anti_patterns
from app.main import AVAILABLE_STYLES, STYLE_DESCRIPTIONS


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Humanizer CLI — make AI text sound human.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  python -m app.cli --text 'Hello world' --style blunt\n"
               "  python -m app.cli --file input.txt --style casual --intensity 0.8\n"
               "  python -m app.cli --styles",
    )

    p.add_argument("--text", "-t", type=str, help="Text to humanize")
    p.add_argument("--file", "-f", type=str, help="Read text from file")
    p.add_argument("--style", "-s", type=str, default="neutral",
                   choices=AVAILABLE_STYLES,
                   help="Humanization style")
    p.add_argument("--intensity", "-i", type=float, default=0.5,
                   help="Humanization intensity (0.0-1.0)")
    p.add_argument("--model", "-m", type=str, default=None,
                   help="Model override (provider:model_id)")
    p.add_argument("--json", "-j", action="store_true",
                   help="Output as JSON (includes confidence, tokens, pass2 info)")
    p.add_argument("--metrics", action="store_true",
                   help="Show metrics after operation")
    p.add_argument("--metrics-only", action="store_true",
                   help="Only show metrics, no humanization")
    p.add_argument("--health", action="store_true",
                   help="Print health/status info and exit")
    p.add_argument("--styles", action="store_true",
                   help="List available styles and exit")
    p.add_argument("--server", type=str, default=None,
                   help="Server URL for remote humanization (e.g. http://localhost:8013)")

    return p.parse_args()


async def _remote_humanize(args: argparse.Namespace):
    """Use the HTTP API instead of direct import."""
    import httpx

    base = args.server.rstrip("/")
    async with httpx.AsyncClient(timeout=120.0) as client:
        # Health
        if args.health:
            r = await client.get(f"{base}/health")
            print(json.dumps(r.json(), indent=2))
            return

        # Styles
        if args.styles:
            r = await client.get(f"{base}/styles")
            for s in r.json():
                print(f"  {s['name']:<18} {s['description']}")
            return

        # Metrics only
        if args.metrics_only:
            r = await client.get(f"{base}/metrics")
            print(json.dumps(r.json(), indent=2))
            return

        # Humanize
        text = args.text
        if args.file:
            text = open(args.file).read()
        if not text:
            print("Error: --text or --file required", file=sys.stderr)
            sys.exit(1)

        payload = {
            "text": text,
            "style": args.style,
            "intensity": args.intensity,
        }
        if args.model:
            payload["model"] = args.model

        r = await client.post(f"{base}/humanize", json=payload)
        if r.status_code != 200:
            print(f"Error {r.status_code}: {r.text}", file=sys.stderr)
            sys.exit(1)

        data = r.json()
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            print(data["text"])
            print(f"\n── tokens={data['tokens']} confidence={data['confidence']:.2f} pass2={data['pass2_applied']}")

        if args.metrics:
            r2 = await client.get(f"{base}/metrics")
            print("\n── Metrics ──")
            print(json.dumps(r2.json(), indent=2))


async def _local_humanize(args: argparse.Namespace):
    """Direct import — bypass HTTP, use the humanizer module directly."""
    # Styles
    if args.styles:
        for name in AVAILABLE_STYLES:
            desc = STYLE_DESCRIPTIONS.get(name, "")
            print(f"  {name:<18} {desc}")
        return

    # Health
    if args.health:
        info = {
            "model": DEFAULT_MODEL,
            "styles": AVAILABLE_STYLES,
            "anti_patterns_count": len(get_anti_patterns()),
        }
        print(json.dumps(info, indent=2))
        return

    # Metrics only
    if args.metrics_only:
        print(json.dumps(metrics.snapshot(), indent=2))
        return

    # Humanize
    text = args.text
    if args.file:
        text = open(args.file).read()
    if not text:
        print("Error: --text or --file required", file=sys.stderr)
        sys.exit(1)

    model = args.model or DEFAULT_MODEL
    result = await humanize(
        text=text,
        style=args.style,
        intensity=args.intensity,
        model=model,
    )

    if args.json:
        print(json.dumps({
            "text": result.text,
            "model": result.model,
            "tokens": result.total_tokens,
            "pass2_applied": result.pass2_applied,
            "confidence": result.confidence,
        }, indent=2))
    else:
        print(result.text)
        print(f"\n── tokens={result.total_tokens} confidence={result.confidence:.2f} pass2={result.pass2_applied} model={result.model}")

    if args.metrics:
        print("\n── Metrics ──")
        print(json.dumps(metrics.snapshot(), indent=2))


async def main():
    args = parse_args()

    if args.server:
        await _remote_humanize(args)
    else:
        await _local_humanize(args)


if __name__ == "__main__":
    asyncio.run(main())
