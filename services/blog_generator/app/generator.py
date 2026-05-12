"""Blog generator — composes prompts + research + inference-gateway calls."""
import httpx
import logging
import time
import uuid
from app.tracker import GenerationRecord, record_generation, calc_cost
from app.logger import RequestLogger
from app.prompts import BLOG_SYSTEM_PROMPT, base_prompt, researched_prompt
from app.research import research_topic

log = logging.getLogger("blog_generator.generator")

INFERENCE_URL = "http://inference_gateway:8005/v1/chat/completions"
INFERENCE_URL_FALLBACK = "http://localhost:8005/v1/chat/completions"


async def _call_inference(messages: list, model: str, max_tokens: int, temperature: float, rlog) -> dict:
    """Call inference-gateway, fallback to localhost."""
    for url in [INFERENCE_URL, INFERENCE_URL_FALLBACK]:
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(url, json={
                    "model": model,
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                })
                resp.raise_for_status()
                return resp.json()
        except httpx.ConnectError:
            rlog.warning(f"Inference gateway unreachable at {url}, trying fallback")
    raise Exception("Inference gateway unreachable on all URLs")


def _record(gen_id: str, rid: str, model: str, topic: str, data: dict, elapsed_ms: int) -> dict:
    """Record generation in SQLite tracker, return response dict."""
    usage = data.get("usage", {})
    actual_model = data.get("raw_response", {}).get("model", model)
    content = data.get("content", "")

    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    total_tokens = usage.get("total_tokens", 0)
    cost = calc_cost(actual_model, prompt_tokens, completion_tokens)

    rec = GenerationRecord(
        id=gen_id, rid=rid, model=actual_model, provider="deepseek",
        topic=topic, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
        total_tokens=total_tokens, cost_usd=cost, duration_ms=elapsed_ms, status="success",
    )
    record_generation(rec)
    return {
        "id": gen_id, "topic": topic, "model": actual_model, "content": content,
        "sources": [], "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens, "total_tokens": total_tokens},
        "cost_usd": round(cost, 6), "duration_ms": elapsed_ms,
    }


# ─── Public API ──────────────────────────────────────────────────────────────

async def generate_blog_post(
    topic: str, model: str = "deepseek-chat", style: str = "technical",
    max_tokens: int = 2048, temperature: float = 0.7, rid: str = "",
) -> dict:
    """Generate a blog post on a topic (no research)."""
    rlog = RequestLogger(log, rid)
    gen_id = uuid.uuid4().hex[:12]
    start = time.monotonic()

    prompt = base_prompt(topic, style)
    messages = [
        {"role": "system", "content": BLOG_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    rlog.info(f"Generate: {gen_id} topic={topic} model={model}")
    data = await _call_inference(messages, model, max_tokens, temperature, rlog)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    result = _record(gen_id, rid, model, topic, data, elapsed_ms)

    rlog.info(f"Blog generated: {gen_id} model={result['model']} tokens={result['usage']['total_tokens']} cost=${result['cost_usd']:.6f} duration={elapsed_ms}ms")
    return result


async def generate_researched_blog(
    topic: str, model: str = "deepseek-chat", style: str = "technical",
    max_tokens: int = 2048, temperature: float = 0.7, rid: str = "",
) -> dict:
    """Research via DeepSearch, then generate a blog with real sources."""
    rlog = RequestLogger(log, rid)
    gen_id = uuid.uuid4().hex[:12]
    start = time.monotonic()

    # Research
    rlog.info(f"Researching: {topic[:80]}")
    try:
        research = await research_topic(topic)
        sources = research.get("sources", [])
        research_answer = research.get("answer", "")
        rlog.info(f"Research: {len(sources)} sources, {len(research_answer)} chars")
    except Exception as e:
        rlog.warning(f"Research failed: {e}")
        sources = []
        research_answer = ""

    # Generate
    prompt = researched_prompt(topic, style, sources, research_answer)
    messages = [
        {"role": "system", "content": BLOG_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    rlog.info(f"Researched generate: {gen_id} topic={topic} model={model}")
    data = await _call_inference(messages, model, max_tokens, temperature, rlog)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    result = _record(gen_id, rid, model, topic, data, elapsed_ms)

    # Attach sources
    result["sources"] = [{"title": s.get("title", ""), "url": s.get("url", "")} for s in sources]

    rlog.info(
        f"Researched blog: {gen_id} model={result['model']} sources={len(sources)} "
        f"tokens={result['usage']['total_tokens']} cost=${result['cost_usd']:.6f} duration={elapsed_ms}ms"
    )
    return result
