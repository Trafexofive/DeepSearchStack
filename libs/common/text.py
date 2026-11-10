"""Shared text utilities.

Boilerplate stripping (DRY): services/web-api and services/crawler
both strip nav chrome / sidebars / footers from crawled markdown. The
two copies had drifted slightly (crawler had 3 extra patterns, e.g.
github's 'Sign in', 'Navigation Menu', 'Toggle navigation'). This
module is the single source of truth.

Used by:
  - services/web-api/main.py
  - services/crawler/main.py
  - services/browser-renderer/main.py
"""

import json as _json
import re as _re
from typing import List, Optional


# ─── JSON-LD article body extraction (paywall bypass) ────────────────────
# Most major news outlets (NYT, BBC, WSJ, FT, The Guardian, Bloomberg) embed
# the full article body in a <script type="application/ld+json"> block in
# the page <head> — for Google News + AMP compatibility. That block is
# usually populated BEFORE the JS paywall fires. Grabbing it gives us the
# real article body even when the visible DOM shows "Subscribe to read".

_LD_JSON_RE = _re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    _re.S | _re.I,
)

_LD_ARTICLE_TYPES = {
    "NewsArticle", "Article", "BlogPosting", "OpinionNewsArticle",
    "ReportageNewsArticle", "AnalysisNewsArticle", "BackgroundNewsArticle",
    "Report", "ScholarlyArticle",
}


def extract_jsonld_article(html: str) -> dict:
    """Walk JSON-LD blocks; if any describes an Article, return its body
    + metadata. Returns {} when no article-shaped block found.

    Returns:
      {"content": str, "title": str|None, "author": str|None,
       "published": str|None, "language": str|None}
    """
    if not html:
        return {}

    def _normalize_author(a) -> Optional[str]:
        if isinstance(a, str):
            return a
        if isinstance(a, dict):
            return a.get("name") or None
        if isinstance(a, list) and a:
            names = [_normalize_author(x) for x in a]
            names = [n for n in names if n]
            return ", ".join(names) if names else None
        return None

    def _is_article(node) -> bool:
        if not isinstance(node, dict):
            return False
        t = node.get("@type")
        if isinstance(t, list):
            return any(x in _LD_ARTICLE_TYPES for x in t)
        return t in _LD_ARTICLE_TYPES

    def _walk(node):
        if isinstance(node, dict):
            if _is_article(node):
                yield node
            # @graph wraps a list of objects
            for v in node.values():
                yield from _walk(v)
        elif isinstance(node, list):
            for v in node:
                yield from _walk(v)

    best: Optional[dict] = None
    best_len = 0
    for m in _LD_JSON_RE.finditer(html):
        raw = m.group(1).strip()
        if not raw:
            continue
        # Some sites wrap with HTML comments or CDATA — strip them.
        raw = _re.sub(r"^<!--\s*|\s*-->$", "", raw)
        try:
            data = _json.loads(raw)
        except Exception:
            # Try lenient — some sites have trailing commas or unescaped newlines
            try:
                data = _json.loads(_re.sub(r",\s*([\]}])", r"\1", raw))
            except Exception:
                continue
        for art in _walk(data):
            body = (art.get("articleBody")
                    or art.get("description")
                    or art.get("text") or "")
            if isinstance(body, list):
                body = " ".join(str(x) for x in body)
            body = (body or "").strip()
            if len(body) > best_len:
                best_len = len(body)
                best = art

    if not best or best_len < 200:
        return {}

    body = (best.get("articleBody") or best.get("description") or best.get("text") or "")
    if isinstance(body, list):
        body = " ".join(str(x) for x in body)
    return {
        "content": (body or "").strip(),
        "title": best.get("headline") or best.get("name"),
        "author": _normalize_author(best.get("author")),
        "published": (best.get("datePublished")
                      or best.get("dateModified")
                      or best.get("uploadDate")),
        "language": best.get("inLanguage"),
    }


# ─── Real article extraction (trafilatura) ────────────────────────────────
#
# Trafilatura performs structural article-body extraction: drops nav,
# footer, sidebar, comments, ads, share widgets — keeps the actual article
# text. It's the engine used by Common Crawl and Internet Archive. We use
# it as the PRIMARY extractor; the regex `strip_boilerplate` below is a
# post-pass for residual nav lines that slip through.

try:
    import trafilatura as _trafilatura  # type: ignore
    from trafilatura.settings import use_config as _traf_use_config  # type: ignore
    _TRAF_CONFIG = _traf_use_config()
    _TRAF_CONFIG.set("DEFAULT", "MIN_OUTPUT_SIZE", "100")
    _TRAF_CONFIG.set("DEFAULT", "MIN_EXTRACTED_SIZE", "100")
    _TRAFILATURA = True
except ImportError:  # service didn't install it; caller falls back to regex pass
    _trafilatura = None
    _TRAF_CONFIG = None
    _TRAFILATURA = False


def extract_article(
    html: Optional[str],
    url: Optional[str] = None,
    output_format: str = "markdown",
) -> dict:
    """Extract the main article body + metadata from raw HTML.

    Returns a dict:
      {
        "content":  cleaned article text (markdown or plain),
        "title":    extracted page title or None,
        "author":   extracted author or None,
        "published": extracted publication date (ISO) or None,
        "language": detected language code or None,
        "extractor": "trafilatura" | "fallback",
      }
    """
    if not html:
        return {"content": "", "title": None, "author": None, "published": None,
                "language": None, "extractor": "empty"}

    traf_result: Optional[dict] = None
    if _TRAFILATURA:
        try:
            text = _trafilatura.extract(
                html,
                url=url,
                output_format=output_format,
                include_comments=False,
                include_tables=True,
                include_links=False,
                include_formatting=True,
                deduplicate=True,
                favor_recall=False,
                config=_TRAF_CONFIG,
            )
            meta = _trafilatura.extract_metadata(html, default_url=url)
            traf_result = {
                "content": text or "",
                "title": getattr(meta, "title", None) if meta else None,
                "author": getattr(meta, "author", None) if meta else None,
                "published": getattr(meta, "date", None) if meta else None,
                "language": getattr(meta, "language", None) if meta else None,
                "extractor": "trafilatura",
            }
        except Exception:
            traf_result = None

    # JSON-LD article fallback. Use it when trafilatura returns thin/no body
    # but the page embeds an article block — typical of paywalled news sites.
    jsonld = extract_jsonld_article(html)
    traf_len = len((traf_result or {}).get("content") or "")
    jsonld_len = len(jsonld.get("content") or "")
    if jsonld and jsonld_len > traf_len and jsonld_len > 400:
        # JSON-LD won. Merge with trafilatura metadata as fill-ins.
        merged_title = jsonld.get("title") or (traf_result or {}).get("title")
        merged_author = jsonld.get("author") or (traf_result or {}).get("author")
        merged_published = jsonld.get("published") or (traf_result or {}).get("published")
        merged_lang = jsonld.get("language") or (traf_result or {}).get("language")
        return {
            "content": jsonld.get("content") or "",
            "title": merged_title,
            "author": merged_author,
            "published": merged_published,
            "language": merged_lang,
            "extractor": "jsonld",
        }
    if traf_result is not None:
        return traf_result

    # Fallback: bs4-strip — used only when trafilatura isn't installed.
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "nav", "footer",
                         "header", "aside", "form", "button"]):
            tag.decompose()
        text = _re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True))
        title_tag = soup.find("title")
        return {
            "content": text,
            "title": title_tag.get_text(strip=True) if title_tag else None,
            "author": None, "published": None, "language": None,
            "extractor": "fallback",
        }
    except Exception:
        return {"content": _re.sub(r"<[^>]+>", " ", html), "title": None,
                "author": None, "published": None, "language": None,
                "extractor": "regex"}

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


_LEAD_NAV_LINK = _re.compile(r'^\s*[*\-]\s*\[[^\]]+\]\(\s*https?://[^)\s]+(\s+"[^"]*")?\s*\)\s*$')


def _strip_lead_nav(lines: List[str]) -> List[str]:
    """Drop a run of bullet-link lines at the head of the document.

    Many doc sites (postgres, kubernetes, mdn) inject the site nav as a
    bullet list of links right above the real content. The shared
    `_BOILERPLATE_PATTERNS` table can't catch these because the link text
    varies. Heuristic: walk from the top, eating blank lines + bullet-link
    lines, but stop at the first real prose/heading line. Limit scan window
    to 80 lines so legitimate link-lists deep in the body are preserved.
    """
    if not lines:
        return lines
    nav_streak = 0
    i = 0
    cap = min(len(lines), 80)
    while i < cap:
        s = lines[i].strip()
        if not s:
            i += 1
            continue
        if _LEAD_NAV_LINK.match(s):
            nav_streak += 1
            i += 1
            continue
        break
    # Only strip if we saw at least 3 nav-link lines in a row (otherwise
    # this is just a normal page that happens to start with one link).
    if nav_streak >= 3:
        return lines[i:]
    return lines


def strip_boilerplate(markdown: str) -> str:
    """Strip nav chrome, sidebars, footers, and boilerplate sections from crawled markdown.

    Rules (in order):
      1. Drop lead nav bullet-link runs (>= 3 consecutive site-nav links).
      2. Drop lines matching any pattern in _BOILERPLATE_PATTERNS.
      3. When a heading matches a known boilerplate section name (case-insensitive,
         e.g. "See also", "References", "Navigation Menu"), skip the entire section
         until a heading of the same or higher level.
    """
    if not markdown:
        return markdown
    lines = markdown.split('\n')
    lines = _strip_lead_nav(lines)
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


# ─── Universal markdown cleanup ────────────────────────────────────────
# Applied AFTER strip_boilerplate. Targets the residual garbage that lands
# in every result regardless of source:
#   - Image markdown (![...](url)) — pure visual noise in a text archive
#   - Empty link shells [](url) — crawl4ai emits these for icons
#   - Long URL-only lines — usually share/track buttons
#   - Tracking pixels / data URIs
#   - Runs of `*` or `-` separators
#   - Repeated paragraphs (within the same document)
#   - Multiple blank lines collapsed

_IMG_RE = _re.compile(r'!\[[^\]]*\]\([^)]*\)')
_EMPTY_LINK_RE = _re.compile(r'\[\s*\]\([^)]*\)')
_DATA_URI_RE = _re.compile(r'data:[^)\s]+')
_TRAILING_WS = _re.compile(r'[ \t]+$', _re.M)
_MULTI_BLANK = _re.compile(r'\n{3,}')
_SEP_LINE = _re.compile(r'^[\*\-_=]{3,}\s*$')
_URL_ONLY = _re.compile(r'^\s*\[[^\]]*\]\(https?://[^)]+\)\s*$')


def clean_markdown(markdown: str, *, dedupe_paragraphs: bool = True) -> str:
    """Universal post-strip cleanup. Hits noise that survives boilerplate-stripping.

    - Drops image markdown (!\[...](...)) — keeps alt-text inline if present.
    - Drops empty-text links [](url) that wrap icons.
    - Removes data: URIs.
    - Dedupes paragraphs within the same document (intra-doc dedup).
    - Collapses 3+ blank lines to 2 and trims trailing whitespace.
    """
    if not markdown:
        return markdown

    # 1. Keep image alt-text but drop the URL+brackets:  ![alt](u) → alt
    md = _IMG_RE.sub(lambda m: _re.sub(r'!\[([^\]]*)\]\([^)]*\)', r'\1', m.group(0)), markdown)
    # 2. Drop empty-text links
    md = _EMPTY_LINK_RE.sub('', md)
    # 3. Strip data: URIs
    md = _DATA_URI_RE.sub('', md)
    # 4. Trim trailing whitespace
    md = _TRAILING_WS.sub('', md)

    # 5. Line-level cleanup: drop separators, URL-only lines (usually share buttons)
    out_lines: List[str] = []
    for line in md.split('\n'):
        stripped = line.strip()
        if _SEP_LINE.match(stripped):
            continue
        # Drop lines that are JUST a single bracketed link (button rows)
        if _URL_ONLY.match(line):
            continue
        out_lines.append(line)
    md = '\n'.join(out_lines)

    # 6. Intra-doc paragraph dedup. Many extractors emit the same headline 3+
    # times (header, breadcrumb, "you might also like"). Keep first occurrence.
    if dedupe_paragraphs:
        paragraphs = _re.split(r'\n{2,}', md)
        seen: set[str] = set()
        out: List[str] = []
        for p in paragraphs:
            key = _re.sub(r'\s+', ' ', p).strip().lower()
            # Skip very short paragraphs from dedup (e.g. dates, single words)
            if len(key) < 30:
                out.append(p)
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append(p)
        md = '\n\n'.join(out)

    # 7. Collapse 3+ blank lines
    md = _MULTI_BLANK.sub('\n\n', md).strip()
    return md


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


# ── 64-bit Locality Sensitive Hashing (SimHash) for Near-Dedup ──────────────

def compute_simhash(text: str) -> int:
    """Compute a 64-bit SimHash fingerprint of the text.
    Sub-millisecond, pure Python, zero external dependencies.
    """
    import re
    import hashlib
    
    tokens = re.findall(r"\w+", text.lower())
    if not tokens:
        return 0
        
    v = [0] * 64
    for token in tokens:
        # 64-bit hash of token
        h = int(hashlib.md5(token.encode("utf-8")).hexdigest()[:16], 16)
        for i in range(64):
            bit = (h >> i) & 1
            v[i] += 1 if bit else -1
            
    fingerprint = 0
    for i in range(64):
        if v[i] > 0:
            fingerprint |= (1 << i)
    return fingerprint

def hamming_distance(hash1: int, hash2: int) -> int:
    """Compute bitwise Hamming distance between two 64-bit fingerprints."""
    x = (hash1 ^ hash2) & 0xFFFFFFFFFFFFFFFF
    # Brian Kernighan bit-count
    count = 0
    while x:
        x &= x - 1
        count += 1
    return count
