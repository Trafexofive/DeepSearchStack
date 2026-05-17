"""
LLM Auditor — uses inference_gateway to score content for AI-citation potential.

Scores how likely an LLM would cite this content for a given keyword query.
"""

import json
import logging
import os
from typing import Optional

import httpx

log = logging.getLogger("geo-audit.llm")
INFERENCE_URL = os.environ.get("INFERENCE_URL", "http://inference_gateway:8005")


async def score_citation_potential(
    client: httpx.AsyncClient,
    content: str,
    keyword: str,
    max_tokens: int = 300,
) -> dict:
    """Ask an LLM to rate how likely it would cite this content.

    Uses mid-2026 GEO benchmarks:
    - 55% of AI Overview citations come from first 30% of page content
    - 59.6% of citations come from URLs outside top-20 organic results
    - FAQPage schema is highest-value schema for AI extraction
    - Content not updated quarterly loses citations at 3x normal rate
    - Brand mentions (0.664) correlate 3x more than backlinks (0.218)
    - 3+ comparison tables = +25.7% more ChatGPT citations
    - Princeton GEO benchmark: +40% citing sources, +37% statistics, +30% quotations
    - BLUF: 90% of Grok wins answer query in first 100 words
    """
    prompt = (
        "You are an AI citation auditor. Rate the following content on a scale of 0-100 "
        "for how likely an AI assistant would cite it when answering a question about "
        f"'{keyword}'.\n\n"
        "GEO scoring criteria (weighted):\n"
        "1. Answer in first 100-150 words (critical — 55% of citations from first 30%)\n"
        "2. Answer capsules: 40-60 word self-contained blocks per section\n"
        "3. Sourced statistics with dates (+37% citation probability)\n"
        "4. Named expert quotations (+30%)\n"
        "5. Heading hierarchy matching natural language queries\n"
        "6. Comparison tables (3+ tables = +25.7% ChatGPT citations)\n"
        "7. FAQ section with direct self-contained answers\n"
        "8. Visible last-updated date (content not refreshed quarterly loses 3x)\n"
        "9. Named author with credentials\n"
        "10. Brand entity clarity — is it clear what this brand/entity is?\n"
        "\n"
        "Respond with ONLY a JSON object:\n"
        '{"citation_score": 0-100, "reasoning": "short explanation of score", '
        '"strengths": ["strength1", ...], "gaps": ["gap1", ...]}\n\n'
        "CONTENT:\n"
        f"{content[:4000]}"
    )

    try:
        resp = await client.post(
            f"{INFERENCE_URL}/v1/chat/completions",
            json={
                "model": "deepseek-v4-pro",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.3,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        return _parse_llm_response(raw)

    except Exception as e:
        log.warning("llm_audit_failed: %s", str(e))
        return {
            "citation_score": 0,
            "reasoning": "LLM audit unavailable",
            "strengths": [],
            "gaps": ["LLM scoring failed — service unreachable"],
        }


async def compare_content(
    client: httpx.AsyncClient,
    target_content: str,
    competitor_contents: list[str],
    keyword: str,
) -> dict:
    """Compare target content against competitor content for AI-citation potential.

    Uses mid-2026 competition benchmarks:
    - Top 15 domains capture 68% of all AI citation share
    - Only 38% of AI citations from top-10 organic results
    - LinkedIn now #1 for professional queries across all platforms
    - Wikipedia ~48% of ChatGPT top-10 citations
    - FAQPage schema is highest single-value implementation
    """
    prompt = (
        "Compare the following content pieces for AI citation potential on the topic "
        f"'{keyword}'. Rate each 0-100 considering: answer presence, fact density, "
        "structure quality, authority signals, and entity clarity.\n\n"
        f"TARGET CONTENT:\n{target_content[:3000]}\n\n"
    )
    for i, cc in enumerate(competitor_contents[:3]):
        prompt += f"COMPETITOR {i+1}:\n{cc[:2000]}\n\n"

    prompt += (
        "Respond with ONLY JSON:\n"
        '{"target_score": 0-100, "competitor_scores": [0-100, ...], '
        '"gaps": ["gap1", ...], "advantages": ["adv1", ...]}'
    )

    try:
        resp = await client.post(
            f"{INFERENCE_URL}/v1/chat/completions",
            json={
                "model": "deepseek-v4-flash",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 300,
                "temperature": 0.3,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        raw = data.get("choices", [{}])[0].get("message", {}).get("content", "{}")
        return _parse_compare_response(raw)

    except Exception as e:
        log.warning("compare_failed: %s", str(e))
        return {
            "target_score": 0,
            "competitor_scores": [],
            "gaps": ["LLM comparison unavailable"],
            "advantages": [],
        }


def _parse_llm_response(raw: str) -> dict:
    """Extract JSON from LLM response (handles markdown code blocks)."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.warning("failed to parse LLM response: %s", raw[:200])
        return {
            "citation_score": 0,
            "reasoning": "Parse error",
            "strengths": [],
            "gaps": ["Could not parse LLM response"],
        }


def _parse_compare_response(raw: str) -> dict:
    """Extract JSON from LLM comparison response."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1]
        raw = raw.rsplit("```", 1)[0]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log.warning("failed to parse comparison response: %s", raw[:200])
        return {
            "target_score": 0,
            "competitor_scores": [],
            "gaps": [],
            "advantages": [],
        }
