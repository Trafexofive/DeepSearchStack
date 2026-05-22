"""Humanizer core — two-pass LLM text humanization.

Pass 1: Rewrite with humanization system prompt.
Pass 2: Detect & fix remaining AI patterns in Pass 1 output.
Returns a confidence score with each result.

Mission-agnostic: no domain knowledge, only style transformation rules.
"""

import os
import re
import time
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional

import httpx

from app.logger import setup_logger

logger = setup_logger("humanizer")

INFERENCE_URL = os.getenv("INFERENCE_URL", "http://inference_gateway:8005/v1/chat/completions")
DEFAULT_MODEL = os.getenv("HUMANIZER_MODEL", "nvidia_nim:zhipuai/glm-4-9b-chat")
MAX_INPUT_LENGTH = int(os.getenv("HUMANIZER_MAX_INPUT", "16384"))
CONFIG_DIR = Path(os.getenv("HUMANIZER_CONFIG_DIR", "/app/config"))


# ═══════════════════════════════════════════════════════════════════════════════
# Anti-pattern loader — configurable via config/anti-patterns.txt
# ═══════════════════════════════════════════════════════════════════════════════

_DEFAULT_ANTI_PATTERNS = [
    "delve into", "delve deeper", "deep dive",
    "it is important to note", "it's important to note",
    "it is worth noting", "it's worth noting",
    "it is crucial to", "it's crucial to",
    "it is essential to", "it's essential to",
    "in conclusion,", "to summarize,",
    "firstly,", "secondly,", "thirdly,", "lastly,",
    "in today's", "in the world of", "in the realm of",
    "as we navigate", "as we journey",
    "game-changer", "game changer", "revolutionary",
    "unleash", "unlock the power", "harness the power",
    "transformative", "paradigm shift",
    "moreover,", "furthermore,", "in addition,",
    "not only", "but also",
    "it should be noted that", "needless to say,",
    "I understand your", "I hear you",
    "that's a great question", "great question",
    "I hope this", "hope this helps",
    "feel free to", "don't hesitate to",
    "Here are", "Here is", "Here's a",
    "Let me break", "Let me explain",
    "Let's explore", "Let's dive",
    "please do not hesitate", "we kindly request",
    "it is recommended that", "one must consider",
    "it can be argued that",
]

_anti_patterns: Optional[list[str]] = None
_anti_patterns_mtime: float = 0.0


def load_anti_patterns() -> list[str]:
    """Load anti-patterns from config file, fall back to defaults."""
    global _anti_patterns, _anti_patterns_mtime

    config_path = CONFIG_DIR / "anti-patterns.txt"
    if not config_path.exists():
        return list(_DEFAULT_ANTI_PATTERNS)

    # Reload only if file changed (hot-reload support)
    try:
        mtime = config_path.stat().st_mtime
        if _anti_patterns is not None and mtime == _anti_patterns_mtime:
            return _anti_patterns
    except OSError:
        return list(_DEFAULT_ANTI_PATTERNS)

    patterns: list[str] = []
    try:
        for line in config_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            patterns.append(line)
    except Exception as e:
        logger.warning("Failed to load anti-patterns config: %s — using defaults", e)
        return list(_DEFAULT_ANTI_PATTERNS)

    if not patterns:
        logger.warning("Empty anti-patterns config — using defaults")
        return list(_DEFAULT_ANTI_PATTERNS)

    _anti_patterns = patterns
    _anti_patterns_mtime = mtime
    logger.info("Loaded %d anti-patterns from %s", len(patterns), config_path)
    return patterns


def get_anti_patterns() -> list[str]:
    """Get current anti-pattern list (cached, hot-reloadable)."""
    return load_anti_patterns()


def build_anti_pattern_block() -> str:
    """Build the formatted anti-pattern block for prompts."""
    return "\n".join(f"- {p}" for p in get_anti_patterns())


# ═══════════════════════════════════════════════════════════════════════════════
# System prompts — cached to avoid rebuilding anti-pattern block
# ═══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT_PASS1 = """You are a text humanizer. Rewrite the input to sound like it was written by a real human, not AI.

Rules:
- Vary sentence length. Mix short punchy sentences with longer flowing ones.
- Use contractions naturally (don't, can't, it's, they're).
- Include occasional sentence fragments where natural.
- Use everyday vocabulary. Avoid corporate-speak and academic padding.
- Inject subtle personality — dry humor, mild opinion, or casual asides.
- NEVER use structured lists, bullet points, or numbered steps. Write in prose.
- NEVER use these phrases or patterns:
{anti_patterns}
- Preserve ALL facts, names, numbers, and technical details from the original.
- Do NOT change the core meaning or add new information.

Output ONLY the rewritten text. No preamble, no explanations, no "Here's the humanized version:"."""

SYSTEM_PROMPT_PASS2 = """You are a text humanizer doing a second pass. The text below has already been humanized once, but may still have AI-like patterns.

Your job: make it sound even MORE human. Read it and fix anything that still sounds robotic.

Specific fixes to apply:
- Break up any remaining perfectly balanced paragraph structures. Humans write unevenly.
- If any sentence starts with "However,", "Therefore,", "Additionally," — rewrite it.
- If the rhythm sounds too polished or symmetrical, roughen it up.
- Add one small imperfection: a run-on sentence, a fragment, or a slightly awkward transition.
- Remove any remaining phrases from this blocklist:
{anti_patterns}

Rules:
- Keep it subtle. Don't overdo it. The text should still be coherent and readable.
- Preserve all facts, names, numbers, and technical accuracy.
- Do NOT change the core meaning or add new information.

Output ONLY the rewritten text. No preamble, no explanations."""

STYLE_MODIFIERS: dict[str, str] = {
    "casual": "\nAdditional style: Write casually — like texting a friend. Use slang where natural. Keep it loose.",
    "professional": "\nAdditional style: Professional but not corporate. Confident, direct, no fluff. Like a senior engineer explaining something.",
    "neutral": "",
    "blunt": "\nAdditional style: Blunt. No pleasantries. Get straight to the point. Short sentences preferred.",
    "conversational": "\nAdditional style: Conversational — like you're talking over coffee. Rhetorical questions welcome.",
}


@lru_cache(maxsize=32)
def _cached_pass1_prompt(style: str, intensity_key: str, patterns_hash: str) -> str:
    """Build and cache Pass 1 prompt. patterns_hash ensures cache invalidation on config change."""
    anti_block = build_anti_pattern_block()
    prompt = SYSTEM_PROMPT_PASS1.format(anti_patterns=anti_block)

    modifier = STYLE_MODIFIERS.get(style, "")
    if modifier:
        prompt += modifier

    intensity = float(intensity_key)
    if intensity > 0.7:
        prompt += "\nIntensity: HIGH. Be aggressive with the humanization. More fragments, more personality, more edge."
    elif intensity > 0.4:
        prompt += "\nIntensity: MODERATE. Noticeably human but keep it clean."

    return prompt


@lru_cache(maxsize=8)
def _cached_pass2_prompt(patterns_hash: str) -> str:
    """Build and cache Pass 2 prompt."""
    anti_block = build_anti_pattern_block()
    return SYSTEM_PROMPT_PASS2.format(anti_patterns=anti_block)


def _patterns_fingerprint() -> str:
    """Short fingerprint of current anti-patterns for cache key."""
    patterns = get_anti_patterns()
    return str(hash(tuple(patterns)))


def build_pass1_prompt(style: str, intensity: float) -> str:
    """Build Pass 1 system prompt (cached)."""
    # Bucket intensity to avoid cache explosion: 0.0, 0.2, 0.4, 0.6, 0.8, 1.0
    bucketed = round(intensity * 5) / 5
    return _cached_pass1_prompt(style, str(bucketed), _patterns_fingerprint())


def build_pass2_prompt() -> str:
    """Build Pass 2 system prompt (cached)."""
    return _cached_pass2_prompt(_patterns_fingerprint())


# ═══════════════════════════════════════════════════════════════════════════════
# Metrics tracker — thread-safe token cost tracking
# ═══════════════════════════════════════════════════════════════════════════════

class MetricsTracker:
    """Thread-safe cumulative metrics for the humanizer service."""

    def __init__(self):
        self._lock = threading.Lock()
        self.total_requests: int = 0
        self.total_tokens: int = 0
        self.pass1_tokens: int = 0
        self.pass2_tokens: int = 0
        self.pass2_applied_count: int = 0
        self.errors: int = 0
        self.total_latency_ms: float = 0.0
        self.start_time: float = time.time()

    def record(self, result: "HumanizeResult", latency_ms: float) -> None:
        with self._lock:
            self.total_requests += 1
            self.total_tokens += result.total_tokens
            self.pass1_tokens += result.pass1_tokens
            self.pass2_tokens += result.pass2_tokens
            if result.pass2_applied:
                self.pass2_applied_count += 1
            self.total_latency_ms += latency_ms

    def record_error(self) -> None:
        with self._lock:
            self.errors += 1

    def snapshot(self) -> dict:
        with self._lock:
            uptime = time.time() - self.start_time
            avg_latency = self.total_latency_ms / max(self.total_requests, 1)
            return {
                "uptime_seconds": round(uptime, 1),
                "total_requests": self.total_requests,
                "total_errors": self.errors,
                "total_tokens": self.total_tokens,
                "pass1_tokens": self.pass1_tokens,
                "pass2_tokens": self.pass2_tokens,
                "pass2_rate": round(self.pass2_applied_count / max(self.total_requests, 1), 3),
                "avg_latency_ms": round(avg_latency, 1),
                "avg_tokens_per_request": round(self.total_tokens / max(self.total_requests, 1), 1),
            }


metrics = MetricsTracker()


# ═══════════════════════════════════════════════════════════════════════════════
# Inference client
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class HumanizeResult:
    text: str = ""
    model: str = ""
    pass1_tokens: int = 0
    pass2_tokens: int = 0
    total_tokens: int = 0
    pass2_applied: bool = False
    confidence: float = 0.5


async def _call_inference(
    system_prompt: str,
    user_text: str,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.8,
    max_tokens: int = 2048,
) -> tuple[str, int]:
    """Call inference-gateway and return (content, token_count)."""
    async with httpx.AsyncClient(timeout=120.0) as client:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        # Resolve provider from model (format: "provider:model_id")
        headers = {}
        if ":" in model:
            provider, actual_model = model.split(":", 1)
            headers["x-provider"] = provider
            payload["model"] = actual_model

        resp = await client.post(INFERENCE_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

        content = data.get("content", "")
        tokens = data.get("usage", {}).get("total_tokens", 0)
        return content, tokens


def _text_difference_ratio(a: str, b: str) -> float:
    """Rough ratio of character-level difference between two strings."""
    if not a or not b:
        return 1.0
    shorter = min(len(a), len(b))
    if shorter == 0:
        return 1.0
    diffs = sum(1 for i in range(shorter) if a[i] != b[i])
    length_diff = abs(len(a) - len(b))
    return (diffs + length_diff) / max(len(a), len(b))


def _compute_confidence(text: str, pass2_applied: bool, change_ratio: float) -> float:
    """Compute a 0-1 humanization confidence score.

    Factors:
    - Anti-pattern hit count in final text (lower = better)
    - Sentence length variance (higher = more human)
    - Whether Pass 2 was applied (applied = needed more work)
    - Change ratio from Pass 1→Pass 2
    """
    anti_patterns = get_anti_patterns()
    text_lower = text.lower()

    # Count anti-pattern hits
    hits = 0
    for pattern in anti_patterns:
        hits += text_lower.count(pattern.lower())

    # Normalize by text length: hits per 100 chars
    hit_density = hits / max(len(text), 1) * 100

    # Sentence length variance (simple heuristic)
    sentences = re.split(r'[.!?]+', text)
    lengths = [len(s.strip().split()) for s in sentences if s.strip()]
    if len(lengths) >= 2:
        avg_len = sum(lengths) / len(lengths)
        variance = sum((l - avg_len) ** 2 for l in lengths) / len(lengths)
        # High variance = more human-like rhythm
        variance_score = min(variance / 50.0, 1.0)  # cap at 1.0
    else:
        variance_score = 0.3  # single sentence — neutral

    # Base score starts at 0.7, subtract for pattern hits, add for variance
    base = 0.7 - (hit_density * 0.05)  # each hit/100chars costs 0.05
    base += variance_score * 0.2

    # Pass 2 penalty: if pass2 was applied, the text needed more work
    if pass2_applied:
        base -= change_ratio * 0.15  # more change = more AI-like before

    return max(0.0, min(1.0, base))


async def humanize(
    text: str,
    style: str = "neutral",
    intensity: float = 0.5,
    model: str = DEFAULT_MODEL,
) -> HumanizeResult:
    """Two-pass humanization with confidence scoring.

    Pass 1: Rewrite with humanization prompt.
    Pass 2: Detect & fix remaining AI patterns.
    If Pass 2 output is very similar to Pass 1 (<5% change), keep Pass 1.
    """
    t0 = time.monotonic()
    result = HumanizeResult(model=model)

    # ── Pass 1: Initial humanization ─────────────────────────────────────
    prompt_p1 = build_pass1_prompt(style, intensity)
    logger.info("Pass 1: humanizing %d chars with style=%s intensity=%.1f", len(text), style, intensity)

    p1_text, p1_tokens = await _call_inference(
        system_prompt=prompt_p1,
        user_text=text,
        model=model,
        temperature=0.8,
        max_tokens=max(2048, len(text)),
    )
    result.pass1_tokens = p1_tokens

    if not p1_text.strip():
        logger.warning("Pass 1 returned empty — falling back to original")
        result.text = text
        result.total_tokens = p1_tokens
        result.confidence = 0.0
        metrics.record(result, (time.monotonic() - t0) * 1000)
        return result

    # ── Pass 2: Anti-pattern scrub ───────────────────────────────────────
    prompt_p2 = build_pass2_prompt()
    logger.info("Pass 2: scrubbing %d chars", len(p1_text))

    p2_text, p2_tokens = await _call_inference(
        system_prompt=prompt_p2,
        user_text=p1_text,
        model=model,
        temperature=0.6,
        max_tokens=max(2048, len(p1_text)),
    )
    result.pass2_tokens = p2_tokens
    result.total_tokens = p1_tokens + p2_tokens

    if not p2_text.strip():
        logger.warning("Pass 2 returned empty — using Pass 1 output")
        result.text = p1_text
        result.confidence = _compute_confidence(p1_text, False, 0.0)
        metrics.record(result, (time.monotonic() - t0) * 1000)
        return result

    # ── Decide: use Pass 2 if it meaningfully changed the text ───────────
    change_ratio = _text_difference_ratio(p1_text, p2_text)
    if change_ratio > 0.05:
        result.text = p2_text
        result.pass2_applied = True
        logger.info("Pass 2 applied (%.1f%% change)", change_ratio * 100)
    else:
        result.text = p1_text
        logger.info("Pass 2 skipped (<5%% change — Pass 1 was good enough)")

    result.confidence = _compute_confidence(result.text, result.pass2_applied, change_ratio)
    metrics.record(result, (time.monotonic() - t0) * 1000)
    return result
