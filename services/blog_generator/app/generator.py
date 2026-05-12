"""Blog post generator — calls inference-gateway with structured prompts."""

import httpx
import logging
import time
import uuid
from app.tracker import GenerationRecord, record_generation, calc_cost
from app.logger import RequestLogger

log = logging.getLogger("blog_generator.generator")

INFERENCE_URL = "http://inference_gateway:8005/v1/chat/completions"
# Fallback for local dev outside Docker
INFERENCE_URL_FALLBACK = "http://localhost:8005/v1/chat/completions"

BLOG_SYSTEM_PROMPT = """You are a professional technical blog writer. Write clear, engaging, well-structured content.

Output format:
- Use Markdown with proper headings (##, ###)
- Include a compelling title as an H1
- Add a brief summary/abstract after the title
- Use code blocks with language tags where appropriate
- Keep paragraphs focused (2-4 sentences)
- End with a key takeaways section

Avoid:
- Fluff, filler, or marketing-speak
- Overly long introductions
- Unsubstantiated claims"""


async def generate_blog_post(
    topic: str,
    model: str = "deepseek-chat",
    style: str = "technical",
    max_tokens: int = 2048,
    temperature: float = 0.7,
    rid: str = "",
) -> dict:
    """Generate a blog post by calling the inference gateway."""
    rlog = RequestLogger(log, rid)
    gen_id = uuid.uuid4().hex[:12]
    start = time.monotonic()

    prompt = _build_prompt(topic, style)
    rlog.info(f"Generating blog post: {gen_id} topic={topic} model={model}")

    rec = GenerationRecord(
        id=gen_id, rid=rid, model=model, provider="deepseek",
        topic=topic, prompt_tokens=0, completion_tokens=0,
        total_tokens=0, cost_usd=0.0, duration_ms=0, status="pending",
    )

    # Try Docker-internal URL first, fall back to localhost
    url = INFERENCE_URL
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json={
                "model": model,
                "messages": [
                    {"role": "system", "content": BLOG_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            })
            resp.raise_for_status()
            data = resp.json()
    except httpx.ConnectError:
        rlog.warning(f"Inference gateway unreachable at {url}, trying localhost")
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(INFERENCE_URL_FALLBACK, json={
                "model": model,
                "messages": [
                    {"role": "system", "content": BLOG_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            })
            resp.raise_for_status()
            data = resp.json()

    elapsed_ms = int((time.monotonic() - start) * 1000)
    usage = data.get("usage", {})
    actual_model = data.get("raw_response", {}).get("model", model)
    content = data.get("content", "")

    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    total_tokens = usage.get("total_tokens", 0)
    cost = calc_cost(actual_model, prompt_tokens, completion_tokens)

    rec.model = actual_model
    rec.prompt_tokens = prompt_tokens
    rec.completion_tokens = completion_tokens
    rec.total_tokens = total_tokens
    rec.cost_usd = cost
    rec.duration_ms = elapsed_ms
    rec.status = "success"
    record_generation(rec)

    rlog.info(
        f"Blog generated: {gen_id} model={actual_model} "
        f"tokens={total_tokens} cost=${cost:.6f} duration={elapsed_ms}ms"
    )

    return {
        "id": gen_id,
        "topic": topic,
        "model": actual_model,
        "content": content,
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        },
        "cost_usd": round(cost, 6),
        "duration_ms": elapsed_ms,
    }


def _build_prompt(topic: str, style: str) -> str:
    style_hints = {
        "technical": "Use precise technical language. Include code examples if relevant. Target: senior engineers.",
        "tutorial": "Step-by-step walkthrough. Start with prerequisites. Include working code snippets. Target: developers learning a new tool.",
        "thought": "Exploratory, opinionated. Discuss trade-offs and design decisions. Target: experienced practitioners.",
    }
    hint = style_hints.get(style, style_hints["technical"])

    return f"""Write a blog post about: {topic}

Style: {hint}

Structure:
1. Compelling title (H1)
2. One-paragraph summary
3. Motivation / why this matters
4. Core content (2-4 sections with H2 headings)
5. Key takeaways (bullet points)
6. Further reading / next steps (optional)

Total length: 800-1500 words."""
