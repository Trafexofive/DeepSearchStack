"""
Scorer — rule-based content quality and GEO/AI-SEO signal analysis.

Scoring dimensions:
  - heading_structure: H1→H2→H3 hierarchy quality
  - definition_density: terms explicitly defined per word
  - fact_density: factual claims per paragraph
  - readability: Flesch/Kincaid estimate
  - keyword_coverage: primary keyword + LSI presence
  - citation_readiness: sources cited, data attributed
  - content_length: minimum viable length
"""

import re
from typing import Optional


def score_heading_structure(content: str) -> dict:
    """Score heading hierarchy — should be H1 > H2 > H3 with no gaps."""
    headings = re.findall(r'^(#{1,6})\s+', content, re.MULTILINE)
    if not headings:
        return {"score": 0, "detail": "No headings found", "issues": ["No heading structure"]}

    depths = [len(h) for h in headings]
    max_depth = max(depths)
    min_depth = min(depths)

    issues = []
    if depths[0] != 1:
        issues.append("First heading should be H1")
    for i in range(1, len(depths)):
        if depths[i] > depths[i-1] + 1:
            issues.append(f"Jump from H{depths[i-1]} to H{depths[i]} at heading {i+1}")

    has_h1 = 1 in depths
    has_h2 = 2 in depths
    has_h3 = 3 in depths

    score = 100
    if not has_h1: score -= 30
    if not has_h2: score -= 20
    if not has_h3: score -= 10
    score -= len(issues) * 10
    score = max(0, min(100, score))

    return {
        "score": score,
        "detail": f"Hierarchy: H1={int(has_h1)} H2={int(has_h2)} H3={int(has_h3)}, max_depth={max_depth}",
        "issues": issues,
    }


def score_definition_density(content: str) -> dict:
    """Estimate how many terms are explicitly defined."""
    words = content.split()
    total_words = len(words)
    if total_words < 50:
        return {"score": 0, "detail": "Too short to score"}

    # Patterns that indicate definitions
    def_patterns = [
        r'\bis\s+a\b', r'\bare\s+known\s+as\b', r'\brefers?\s+to\b',
        r'\bdefined\s+as\b', r'\bmeans?\b', r'\bdenotes?\b',
        r'\bknown\s+as\b', r'\btypically\b', r'\bin\s+other\s+words\b',
    ]
    def_count = sum(len(re.findall(p, content, re.IGNORECASE)) for p in def_patterns)

    density = def_count / max(1, total_words / 100)  # per 100 words

    score = min(100, int(density * 25))
    return {
        "score": score,
        "detail": f"{def_count} definitions in {total_words} words ({density:.1f}/100w)",
        "issues": [] if score >= 20 else ["Low definition density — add explicit term definitions"],
    }


def score_fact_density(content: str) -> dict:
    """Estimate factual claims per paragraph."""
    paragraphs = [p for p in content.split("\n\n") if len(p.strip()) > 20]
    if not paragraphs:
        return {"score": 0, "detail": "No substantial paragraphs"}

    # Patterns indicating factual claims
    fact_patterns = [
        r'\b\d+%?\b', r'\baccording\s+to\b', r'\bresearch\s+(shows|indicates|suggests)\b',
        r'\bstudy\b', r'\bdata\b', r'\bstatistics?\b', r'\bsurvey\b',
        r'\breport(?:ed|s)?\b', r'\bsource[sd]?\b', r'\bfound\s+that\b',
        r'\bestimate[sd]?\b', r'\baverage\b', r'\bmedian\b',
    ]

    par_with_facts = 0
    total_facts = 0
    for p in paragraphs:
        p_facts = sum(len(re.findall(pt, p, re.IGNORECASE)) for pt in fact_patterns)
        total_facts += p_facts
        if p_facts > 0:
            par_with_facts += 1

    ratio = par_with_facts / len(paragraphs) if paragraphs else 0
    score = min(100, int(ratio * 100))

    return {
        "score": score,
        "detail": f"{total_facts} factual signals in {len(paragraphs)} paragraphs ({ratio:.0%} have facts)",
        "issues": [] if score >= 30 else ["Low fact density — cite sources and data"],
    }


def score_readability(content: str) -> dict:
    """Estimate readability (simplified Flesch)."""
    words = content.split()
    total_words = len(words)
    if total_words < 30:
        return {"score": 50, "detail": "Too short for reliable scoring"}

    sentences = re.split(r'[.!?]+', content)
    sentences = [s for s in sentences if len(s.strip()) > 0]
    total_sentences = len(sentences) if sentences else 1
    syllables = sum(_count_syllables(w) for w in words)

    avg_words_per_sent = total_words / total_sentences
    avg_syllables_per_word = syllables / total_words

    # Simplified Flesch-like score
    flesch = 206.835 - 1.015 * avg_words_per_sent - 84.6 * avg_syllables_per_word
    score = max(0, min(100, int(flesch)))

    grade = (
        "very easy" if score >= 90 else
        "easy" if score >= 70 else
        "standard" if score >= 50 else
        "difficult" if score >= 30 else
        "very difficult"
    )

    return {
        "score": score,
        "detail": f"Flesch ~{score}/100 ({grade}), avg {avg_words_per_sent:.0f} w/sent",
        "issues": [] if score >= 40 else ["Very difficult readability — simplify sentences"],
    }


def score_keyword_coverage(content: str, keyword: str = "") -> dict:
    """Check keyword presence in headings, first 100 words, and body."""
    if not keyword:
        return {"score": 50, "detail": "No keyword provided", "issues": []}

    kw_lower = keyword.lower()
    words = content.lower().split()
    headings = re.findall(r'^#{1,6}\s+(.+)', content, re.MULTILINE)

    in_first_100 = kw_lower in " ".join(words[:100])
    in_h1 = any(keyword.lower() in h.lower() for h in headings if h.startswith("# "))
    in_h2 = any(keyword.lower() in h.lower() for h in headings if h.startswith("## "))
    in_title = kw_lower in words[:10]
    density = words.count(kw_lower) / max(1, len(words)) * 100

    score = 0
    issues = []
    if in_title: score += 25
    if in_h1: score += 20
    if in_first_100: score += 20
    if in_h2: score += 15
    if density > 0.1: score += 20

    if not in_h1:
        issues.append("Keyword not in H1 heading")
    if not in_first_100:
        issues.append("Keyword not in first 100 words")
    if density < 0.05:
        issues.append("Very low keyword density")

    return {
        "score": min(100, score),
        "detail": f"Density: {density:.2f}%{' ✓' if in_h1 else ''}{' ✓' if in_first_100 else ''}",
        "issues": issues,
    }


def score_citation_readiness(content: str) -> dict:
    """Check for source citations, links, attributed data."""
    has_links = bool(re.search(r'\[([^\]]+)\]\(([^)]+)\)', content))
    has_attribution = bool(re.search(r'\b(source|via|credit|adapted from|cited)\b', content, re.IGNORECASE))
    has_footnotes = bool(re.search(r'\[\^?\d+\]', content))
    has_blockquote = bool(re.search(r'^>\s+', content, re.MULTILINE))

    signals = sum([has_links, has_attribution, has_footnotes, has_blockquote])
    score = signals * 25

    return {
        "score": min(100, score),
        "detail": f"Signals: links={'✓' if has_links else '✗'} attribution={'✓' if has_attribution else '✗'} footnotes={'✓' if has_footnotes else '✗'} quotes={'✓' if has_blockquote else '✗'}",
        "issues": [] if score >= 50 else ["Low citation readiness — add links and attributions"],
    }


def score_content_length(content: str) -> dict:
    """Minimum viable content length (target: 800+ words for AI-citation readiness)."""
    words = len(content.split())
    chars = len(content)

    if words >= 2000: score = 100
    elif words >= 1500: score = 85
    elif words >= 1000: score = 70
    elif words >= 800: score = 55
    elif words >= 500: score = 35
    elif words >= 300: score = 20
    else: score = 0

    issues = [] if words >= 800 else [f"Only {words} words — aim for 800+ for AI citation visibility"]

    return {
        "score": score,
        "detail": f"{words} words, {chars} chars",
        "issues": issues,
    }


def _count_syllables(word: str) -> int:
    """Simple syllable counter."""
    word = word.lower().strip(".,!?;:")
    if not word:
        return 0
    vowels = "aeiouy"
    count = 0
    prev_vowel = False
    for ch in word:
        is_vowel = ch in vowels
        if is_vowel and not prev_vowel:
            count += 1
        prev_vowel = is_vowel
    if word.endswith("e"):
        count = max(1, count - 1)
    return max(1, count)


def score_all(content: str, keyword: str = "") -> dict:
    """Run all scoring dimensions and return composite."""
    results = {
        "heading_structure": score_heading_structure(content),
        "definition_density": score_definition_density(content),
        "fact_density": score_fact_density(content),
        "readability": score_readability(content),
        "keyword_coverage": score_keyword_coverage(content, keyword),
        "citation_readiness": score_citation_readiness(content),
        "content_length": score_content_length(content),
    }

    all_issues = []
    for dim, result in results.items():
        all_issues.extend(result.get("issues", []))

    scores = {k: v["score"] for k, v in results.items()}
    composite = int(sum(scores.values()) / len(scores)) if scores else 0

    return {
        "composite_score": composite,
        "dimensions": results,
        "total_issues": len(all_issues),
        "issues": all_issues,
    }
