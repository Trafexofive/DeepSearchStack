"""Scraping stage — parallel content extraction via crawler service."""
import asyncio
import logging
import re
from typing import List, Optional

from models import SearchResult, ScrapedContent
from config import config

logger = logging.getLogger("deepsearch.scraper")

# ── Boilerplate stripping ────────────────────────────────────────────────

# Lines matching these patterns are stripped entirely
_BOILERPLATE_LINE_PATTERNS = [
    re.compile(r, re.IGNORECASE) for r in [
        r'^\[Jump to content\]',
        r'^\[Skip to (content|main|navigation)\]',
        r'^Main menu$',
        r'^move to sidebar (hide|show)$',
        r'^(Navigation|Contents|Menu)\s*$',
        r'^\[.*?(Privacy Policy|Terms of Service|Cookie Policy|Cookie Statement)\]',
        r'^(Cookie|Privacy|Terms|Legal|Accessibility)\b',
        r'^\*\*Sponsored by:\*\*',
        r'^(Theme|Language|Version)\s+(Auto|Light|Dark)',
        r'^(English|Spanish|French|German|Italian|Japanese|Korean|Chinese|Russian|Arabic|Portuguese|Polish|Turkish|Romanian|Greek|Dutch|Swedish|Norwegian|Danish|Finnish|Hungarian|Czech|Slovak|Ukrainian|Hebrew|Thai|Vietnamese|Indonesian|Malay|Hindi|Bengali|Tamil|Telugu|Marathi|Urdu|Persian)\s*[\|\\|]',
        r'^(Previous|Next) topic',
        r'^\[.*?\]\(https?://.*?(privacy|terms|cookie|legal|accessibility)\)',
    ]
]

# Sections starting with these headings are stripped until next heading of equal/higher level
_BOILERPLATE_SECTIONS = [
    'see also', 'references', 'external links', 'further reading',
    'notes', 'footnotes', 'citations', 'bibliography',
    'navigation menu', 'related articles',
]


def _strip_boilerplate(markdown: str) -> str:
    """Strip navigation chrome, sidebars, footers, and boilerplate from crawled markdown.

    Returns cleaned markdown. Never returns empty string if input was non-empty.
    """
    if not markdown:
        return markdown

    lines = markdown.split('\n')
    cleaned = []
    skip_until_next_heading = False
    skip_heading_level = 0
    skip_child_lines = 0  # count of child lines to skip after a stripped section header

    for line in lines:
        stripped = line.strip()

        # Track heading level
        heading_match = re.match(r'^(#{1,6})\s+', stripped)
        if heading_match:
            level = len(heading_match.group(1))
            heading_text = stripped[heading_match.end():].strip().lower()
            skip_child_lines = 0  # heading resets child-line skip

            # End skip section if we hit a heading of equal or higher level
            if skip_until_next_heading and level <= skip_heading_level:
                skip_until_next_heading = False

            # Check if this heading starts a boilerplate section
            if heading_text in _BOILERPLATE_SECTIONS:
                skip_until_next_heading = True
                skip_heading_level = level
                continue

        if skip_until_next_heading:
            continue

        # Skip child lines after a stripped section header (indented or bullet list items)
        if skip_child_lines > 0:
            if stripped and (stripped[0] in (' ', '\t', '*', '-', '+') or re.match(r'^\d+\.', stripped)):
                skip_child_lines -= 1
                continue
            else:
                skip_child_lines = 0  # blank line or non-child — stop skipping

        if not stripped:
            skip_child_lines = 0  # blank line resets child-line skip
            cleaned.append(line)
            continue

        # Skip boilerplate lines
        if any(p.search(stripped) for p in _BOILERPLATE_LINE_PATTERNS):
            skip_child_lines = 10  # skip up to 10 child bullet/indented lines
            continue

        cleaned.append(line)

    result = '\n'.join(cleaned).strip()

    # Remove excessive blank lines
    result = re.sub(r'\n{3,}', '\n\n', result)

    return result if result else markdown  # never return empty



async def execute(
    client,
    search_results: List[SearchResult],
    crawler_url: str,
    max_urls: int = 50,
) -> List[ScrapedContent]:
    """Scrape content from search result URLs in parallel with controlled concurrency."""
    urls_to_scrape = [r.url for r in search_results[:max_urls]]
    concurrency = config.scraping_config.get("concurrency", 10)
    semaphore = asyncio.Semaphore(concurrency)

    async def scrape_one(url: str, title: str) -> Optional[ScrapedContent]:
        async with semaphore:
            try:
                response = await client.post(
                    f"{crawler_url}/crawl",
                    json={
                        "url": url,
                        "extraction_strategy": config.scraping_config.get("extraction_strategy", "markdown"),
                    },
                    timeout=config.scraping_config.get("timeout", 15.0),
                )
                response.raise_for_status()
                data = response.json()
                raw_md = data.get("markdown", data.get("content", ""))
                cleaned_md = _strip_boilerplate(raw_md)
                return ScrapedContent(
                    url=url,
                    title=title,
                    content=cleaned_md,
                    markdown=cleaned_md,
                    success=data.get("success", False),
                    word_count=data.get("word_count", len(cleaned_md.split())),
                    error_message=data.get("error_message"),
                )
            except Exception as e:
                logger.warning(f"Scrape failed for {url}: {e}")
                return ScrapedContent(url=url, title=title, content="", success=False, error_message=str(e))

    tasks = [scrape_one(r.url, r.title) for r in search_results[:max_urls]]
    results = await asyncio.gather(*tasks)

    min_length = config.scraping_config.get("min_content_length", 100)
    return [r for r in results if r and r.success and len(r.content) >= min_length]
