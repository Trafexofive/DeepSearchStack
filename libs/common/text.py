"""Shared text utilities.

Boilerplate stripping (DRY): services/web-api and services/crawler
both strip nav chrome / sidebars / footers from crawled markdown. The
two copies had drifted slightly (crawler had 3 extra patterns, e.g.
github's 'Sign in', 'Navigation Menu', 'Toggle navigation'). This
module is the single source of truth.

Used by:
  - services/web-api/main.py
  - services/crawler/main.py
"""

import re as _re
from typing import List

# Union of both services' original patterns. Includes the 3 extra crawler
# patterns (Sign in, Navigation Menu, Toggle navigation) that web-api was
# missing — so both services now strip github's nav chrome consistently.
_BOILERPLATE_PATTERNS: List[_re.Pattern] = [
    _re.compile(r, _re.IGNORECASE) for r in [
        r'^\[Jump to content\]', r'^\[Skip to (content|main|navigation)\]',
        r'^Main menu$', r'^move to sidebar', r'^(Navigation|Contents|Menu)\s*$',
        r'^\[.*?(Privacy|Terms|Cookie|Legal|Accessibility)\]',
        r'^(Cookie|Privacy|Terms|Legal|Accessibility)\b',
        r'^(Theme|Language|Version)\s+(Auto|Light|Dark)',
        r'^(Previous|Next) topic', r'^Keyboard shortcuts$',
        r'^Press .(←|→|S|\?|Esc). to', r'^\[.*?\]\(https?://.*?(privacy|terms|cookie)\)',
        # Crawler-extras (formerly only in crawler, now in both):
        r'^\[ Sign in \]', r'^Sign in$', r'^Navigation Menu$',
        r'^Toggle navigation$', r'^Search or jump to',
    ]
]

_BOILERPLATE_SECTIONS: List[str] = [
    'see also', 'references', 'external links', 'further reading',
    'notes', 'footnotes', 'citations', 'bibliography', 'navigation menu',
]


def strip_boilerplate(markdown: str) -> str:
    """Strip nav chrome, sidebars, footers, and boilerplate sections from crawled markdown.

    Rules (in order):
      1. Drop lines matching any pattern in _BOILERPLATE_PATTERNS.
      2. When a heading matches a known boilerplate section name (case-insensitive,
         e.g. "See also", "References", "Navigation Menu"), skip the entire section
         until a heading of the same or higher level.
    """
    if not markdown:
        return markdown
    lines = markdown.split('\n')
    cleaned: List[str] = []
    skip_section = False
    skip_level = 0
    for line in lines:
        stripped = line.strip()
        heading = _re.match(r'^(#{1,6})\s+', stripped)
        if heading:
            level = len(heading.group(1))
            text = stripped[heading.end():].strip().lower()
            if skip_section and level <= skip_level:
                skip_section = False
            if text in _BOILERPLATE_SECTIONS:
                skip_section = True
                skip_level = level
                continue
        if skip_section:
            continue
        if any(p.match(stripped) for p in _BOILERPLATE_PATTERNS):
            continue
        cleaned.append(line)
    return '\n'.join(cleaned)


def normalize_url(url: str) -> str:
    """Normalize a URL for deduplication.

    Rules:
      - Lowercase scheme + host
      - Strip trailing slash (but keep root '/')
      - Strip default ports (80 for http, 443 for https)
      - Strip common tracking query params (utm_*, ref, fbclid, gclid)
    """
    from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url

    scheme = (parts.scheme or "http").lower()
    netloc = parts.netloc.lower()
    # Strip default ports
    if (scheme == "http" and netloc.endswith(":80")) or (scheme == "https" and netloc.endswith(":443")):
        netloc = netloc.rsplit(":", 1)[0]
    # Strip tracking query params
    tracking = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content", "ref", "fbclid", "gclid"}
    q = [(k, v) for (k, v) in parse_qsl(parts.query, keep_blank_values=True) if k not in tracking]
    query = urlencode(q)
    # Strip trailing slash from path (but keep root)
    path = parts.path.rstrip("/") if parts.path != "/" else "/"
    return urlunsplit((scheme, netloc, path, query, ""))
