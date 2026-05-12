"""Blog generation prompts. Style-specific system and user prompts."""
from typing import List


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


STYLE_HINTS = {
    "technical": "Use precise technical language. Include code examples if relevant. Target: senior engineers.",
    "tutorial": "Step-by-step walkthrough. Start with prerequisites. Include working code snippets. Target: developers learning a new tool.",
    "thought": "Exploratory, opinionated. Discuss trade-offs and design decisions. Target: experienced practitioners.",
}


def base_prompt(topic: str, style: str) -> str:
    """Prompt for simple (non-researched) blog generation."""
    hint = STYLE_HINTS.get(style, STYLE_HINTS["technical"])
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


def researched_prompt(topic: str, style: str, sources: List[dict], research_answer: str) -> str:
    """Prompt for researched blog generation with real sources."""
    hint = STYLE_HINTS.get(style, STYLE_HINTS["technical"])

    # Source citations block
    sources_block = ""
    if sources:
        sources_block = "\n\n## Research Sources\nUse these sources to add factual depth and citations. Reference them with [1], [2] etc.:\n"
        for i, s in enumerate(sources[:10], 1):
            title = s.get("title", "Untitled")
            url = s.get("url", "")
            snippet = s.get("snippet", "")
            sources_block += f"\n[{i}] {title}\n    URL: {url}\n    Snippet: {snippet[:300]}\n"

    research_context = f"\n\n## Research Summary\n{research_answer[:2000]}" if research_answer else ""

    return f"""Write a blog post about: {topic}

Style: {hint}

Structure:
1. Compelling title (H1)
2. One-paragraph summary
3. Motivation / why this matters
4. Core content (2-4 sections with H2 headings) — use research sources for facts
5. Key takeaways (bullet points)
6. Sources / References section at the end (cite sources with [1], [2] format)

Total length: 800-1500 words.

CRITICAL: Use the research sources provided below. Cite them inline where used.
Do NOT fabricate sources or URLs. If a claim comes from a source, cite it.
{sources_block}{research_context}"""
