"""Domain-specific extractors — bypass the generic crawl pipeline for sites
where we have a structured-data shortcut that beats HTML rendering on quality.

Why:
  Sites like Reddit, YouTube, Twitter/X, Hacker News, arXiv all have APIs or
  JSON endpoints that return clean structured content directly. The generic
  crawl ladder (crawl4ai → playwright → OCR → wayback) on these gives you
  page chrome (avatars, navigation, "Tap to unmute") with the real content
  hidden behind JS or login walls. The shortcuts here turn 0w-of-noise into
  thousands-of-words-of-signal.

Each extractor:
  • takes a URL + an httpx.AsyncClient
  • returns a dict (matching CrawlResponse fields) on success
  • returns None if the URL doesn't match its pattern (no-op fallback)
  • raises on hard failures — caller decides whether to swallow + fall back

The dispatcher `try_domain_extract(url, client)` picks the first matching
extractor and runs it; returns None when no extractor applies or the chosen
one returned None.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import re
import time
from typing import Optional
from urllib.parse import urlparse, parse_qs, quote

import httpx

log = logging.getLogger("crawler.domain_extractors")


# ─── Reddit ────────────────────────────────────────────────────────────
# Any reddit URL gains `.json?raw_json=1` and returns clean JSON of the
# post + full comment tree. No auth needed, but Reddit rate-limits Tor exits
# and some datacenter IPs — falls through to generic crawl on 403.

_REDDIT_RE = re.compile(r"^https?://(?:www\.|old\.|new\.|np\.)?reddit\.com/", re.I)

# Real Firefox UA — Reddit's WAF blocks custom UAs (even compliant ones) but
# accepts vanilla browser fingerprints. Tested 2026-06.
_REDDIT_UAS = [
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.5; rv:128.0) Gecko/20100101 Firefox/128.0",
]

async def _reddit(url: str, client: httpx.AsyncClient) -> Optional[dict]:
    if not _REDDIT_RE.match(url):
        return None
    import os, random
    # Strip query/fragment; force .json
    parsed = urlparse(url)
    path = parsed.path
    if path.endswith("/"):
        path = path[:-1]
    if not path.endswith(".json"):
        path = path + ".json"

    headers = {
        "User-Agent": random.choice(_REDDIT_UAS),
        "Accept": "application/json,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    # Try www → old → proxy. old.reddit.com sometimes accepts when www blocks.
    candidates = [
        f"https://www.reddit.com{path}?raw_json=1&limit=100",
        f"https://old.reddit.com{path}?raw_json=1&limit=100",
    ]
    r = None
    last_status = None
    for u in candidates:
        try:
            r = await client.get(u, headers=headers, timeout=20.0,
                                 follow_redirects=True)
        except Exception as e:
            log.info("reddit_fetch_err url=%s err=%s", u[:120], e)
            r = None
            continue
        last_status = r.status_code
        if r.status_code == 200:
            break
        r = None

    # Final fallback: try via proxy-rotator if configured.
    if r is None:
        proxy_url = os.environ.get("PROXY_ROTATOR_URL") or os.environ.get("HTTP_PROXY")
        if proxy_url:
            try:
                async with httpx.AsyncClient(
                    proxy=proxy_url, follow_redirects=True, timeout=25.0
                ) as pc:
                    r = await pc.get(candidates[0], headers=headers)
                    last_status = r.status_code
                    if r.status_code != 200:
                        r = None
            except Exception as e:
                log.info("reddit_proxy_err url=%s err=%s", url[:120], e)

    if r is None:
        log.info("reddit_blocked url=%s last_status=%s", url[:120], last_status)
        return None
    try:
        data = r.json()
    except Exception:
        return None

    parts: list[str] = []
    title = None
    author = None
    published = None

    # Listing endpoints (subreddit front pages) return a single object.
    # Comment threads return a 2-element list [post_listing, comments_listing].
    if isinstance(data, list) and len(data) == 2:
        post_children = data[0].get("data", {}).get("children", [])
        comment_children = data[1].get("data", {}).get("children", [])
        # Header from the post
        if post_children:
            post = post_children[0].get("data", {})
            title = post.get("title")
            author = post.get("author")
            published = (
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(post["created_utc"]))
                if post.get("created_utc") else None
            )
            parts.append(f"# {title or '(untitled)'}")
            parts.append(f"*r/{post.get('subreddit', '?')} · u/{author or '?'} · "
                         f"↑{post.get('score', 0)} · {post.get('num_comments', 0)} comments*")
            if post.get("selftext"):
                parts.append("")
                parts.append(post["selftext"])
            elif post.get("url_overridden_by_dest"):
                parts.append(f"\n[Link]({post['url_overridden_by_dest']})")
            parts.append("\n---\n## Comments")

        # Comments — walk the tree (depth-first) with indent
        def _walk(children, depth=0):
            for ch in children:
                d = ch.get("data", {})
                if ch.get("kind") != "t1":
                    continue
                body = d.get("body") or ""
                if not body or body in {"[deleted]", "[removed]"}:
                    continue
                indent = "    " * depth
                au = d.get("author") or "?"
                score = d.get("score", 0)
                parts.append(f"\n{indent}**{au}** (↑{score}):")
                for line in body.splitlines():
                    parts.append(f"{indent}{line}")
                replies = d.get("replies")
                if isinstance(replies, dict):
                    _walk(replies.get("data", {}).get("children", []), depth + 1)
        _walk(comment_children)
    elif isinstance(data, dict) and data.get("kind") == "Listing":
        # Subreddit front page — list of posts
        parts.append(f"# Reddit: {parsed.path.strip('/').replace('/', ' / ') or 'front'}")
        for ch in data.get("data", {}).get("children", []):
            p = ch.get("data", {})
            if p.get("title"):
                parts.append(f"\n## [{p['title']}](https://www.reddit.com{p.get('permalink', '')})")
                parts.append(f"*u/{p.get('author', '?')} · ↑{p.get('score', 0)} · "
                             f"{p.get('num_comments', 0)} comments · r/{p.get('subreddit', '?')}*")
                if p.get("selftext"):
                    parts.append("")
                    parts.append(p["selftext"][:1000])
    else:
        return None

    md = "\n".join(parts)
    wc = len(md.split())
    if wc < 10:
        return None
    return {
        "title": title,
        "author": author,
        "published": published,
        "markdown": md,
        "content": md,
        "word_count": wc,
        "extraction_method": "reddit-json",
    }


# ─── YouTube ───────────────────────────────────────────────────────────
# Video page renders give us "Tap to unmute" and chrome — what we actually
# want is the description + transcript. youtube-transcript-api scrapes the
# captions endpoint directly (no API key needed), and oembed gives metadata.

_YT_RE = re.compile(
    r"^https?://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)([\w\-]{11})",
    re.I,
)

async def _youtube(url: str, client: httpx.AsyncClient) -> Optional[dict]:
    m = _YT_RE.match(url)
    if not m:
        return None
    video_id = m.group(1)

    # Metadata via oembed (no auth)
    meta_title = None
    meta_author = None
    try:
        r = await client.get(
            f"https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json",
            timeout=10.0,
        )
        if r.status_code == 200:
            meta = r.json()
            meta_title = meta.get("title")
            meta_author = meta.get("author_name")
    except Exception:
        pass

    # Transcript via yt-dlp (server-IP friendly, robust). The youtube-transcript-api
    # library uses the timedtext endpoint which routinely 429s from datacenter IPs;
    # yt-dlp emulates the full Innertube client and avoids that block. Returns the
    # subtitle text for the chosen language with formatting stripped.
    transcript_text = ""
    description_text = ""
    try:
        def _fetch_yt_dlp() -> tuple[str, str, Optional[str], Optional[str]]:
            try:
                from yt_dlp import YoutubeDL  # type: ignore
            except Exception:
                return "", "", None, None
            opts = {
                "quiet": True,
                "no_warnings": True,
                "skip_download": True,
                "writeautomaticsub": True,
                "writesubtitles": True,
                "subtitleslangs": ["en", "en-US", "en-GB", "en.*"],
                "subtitlesformat": "json3",
                "extract_flat": False,
            }
            try:
                with YoutubeDL(opts) as y:
                    info = y.extract_info(
                        f"https://www.youtube.com/watch?v={video_id}",
                        download=False,
                    )
            except Exception as e:
                log.info("yt_dlp_err video=%s err=%s", video_id, e)
                return "", "", None, None

            title = info.get("title")
            uploader = info.get("uploader") or info.get("channel")
            desc = info.get("description") or ""

            # Subs land under 'subtitles' (manual) or 'automatic_captions'
            def _pick(d):
                if not isinstance(d, dict):
                    return None
                for lang in ("en", "en-US", "en-GB"):
                    if lang in d and d[lang]:
                        return d[lang]
                # any 'en.*'
                for k in d:
                    if k.startswith("en") and d[k]:
                        return d[k]
                return None

            cand = _pick(info.get("subtitles")) or _pick(info.get("automatic_captions"))
            transcript = ""
            if cand:
                # Pick a JSON3 fmt if present (richest); else the first
                fmt = next((f for f in cand if f.get("ext") == "json3"), cand[0])
                sub_url = fmt.get("url")
                if sub_url:
                    import urllib.request
                    try:
                        with urllib.request.urlopen(sub_url, timeout=10) as r:
                            raw = r.read().decode("utf-8", errors="replace")
                        if fmt.get("ext") == "json3":
                            data = json.loads(raw)
                            events = data.get("events") or []
                            parts = []
                            for e in events:
                                for seg in (e.get("segs") or []):
                                    t = seg.get("utf8")
                                    if t:
                                        parts.append(t)
                            transcript = " ".join(parts)
                        else:
                            # VTT / SRT — strip cue lines (HH:MM... and indices)
                            cleaned = []
                            for line in raw.splitlines():
                                line = line.strip()
                                if not line:
                                    continue
                                if "-->" in line or line.isdigit() or line.startswith("WEBVTT"):
                                    continue
                                cleaned.append(line)
                            transcript = " ".join(cleaned)
                    except Exception as e:
                        log.info("yt_sub_fetch_err video=%s err=%s", video_id, e)
            # Normalize whitespace
            transcript = re.sub(r"\s+", " ", transcript).strip()
            desc = desc.strip()
            return transcript, desc, title, uploader

        transcript_text, description_text, dl_title, dl_author = await asyncio.to_thread(
            _fetch_yt_dlp
        )
        # yt-dlp's metadata is often more accurate than oembed.
        if dl_title:
            meta_title = dl_title
        if dl_author:
            meta_author = dl_author
    except Exception as e:
        log.info("yt_transcript_err video=%s err=%s", video_id, e)

    if not transcript_text and not description_text and not meta_title:
        return None

    parts: list[str] = []
    if meta_title:
        parts.append(f"# {meta_title}")
    if meta_author:
        parts.append(f"*by {meta_author} · youtube.com/watch?v={video_id}*\n")
    if description_text:
        parts.append("## Description\n")
        parts.append(description_text)
    if transcript_text:
        parts.append("\n## Transcript\n")
        parts.append(transcript_text)
    md = "\n".join(parts)
    wc = len(md.split())
    if wc < 10:
        return None
    return {
        "title": meta_title,
        "author": meta_author,
        "markdown": md,
        "content": md,
        "word_count": wc,
        "extraction_method": "youtube-transcript" if transcript_text else "youtube-metadata",
    }


# ─── Hacker News ───────────────────────────────────────────────────────
# Algolia exposes the full story+comments tree as one JSON call.

_HN_ITEM_RE = re.compile(
    r"^https?://news\.ycombinator\.com/item\?id=(\d+)", re.I,
)
_HN_FB_RE = re.compile(
    r"^https?://hacker-news\.firebaseio\.com/v0/item/(\d+)\.json", re.I,
)

async def _hn(url: str, client: httpx.AsyncClient) -> Optional[dict]:
    m = _HN_ITEM_RE.match(url) or _HN_FB_RE.match(url)
    if not m:
        return None
    item_id = m.group(1)
    try:
        r = await client.get(
            f"https://hn.algolia.com/api/v1/items/{item_id}", timeout=20.0,
        )
    except Exception:
        return None
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except Exception:
        return None

    parts: list[str] = []
    title = data.get("title")
    if title:
        parts.append(f"# {title}")
    if data.get("url"):
        parts.append(f"[{data['url']}]({data['url']})\n")
    if data.get("text"):
        # algolia returns text as HTML — strip basic tags
        parts.append(re.sub(r"<[^>]+>", "", html.unescape(data["text"])))
    author = data.get("author")
    if data.get("created_at"):
        parts.append(f"\n*by {author} · {data['created_at']}*")
    parts.append("\n---\n## Comments\n")

    def _walk_hn(node, depth=0):
        text = node.get("text")
        if text:
            indent = "    " * depth
            who = node.get("author") or "?"
            cleaned = re.sub(r"<[^>]+>", "", html.unescape(text))
            parts.append(f"\n{indent}**{who}**:")
            for line in cleaned.splitlines():
                parts.append(f"{indent}{line}")
        for child in (node.get("children") or []):
            _walk_hn(child, depth + 1)

    for child in (data.get("children") or []):
        _walk_hn(child, 0)

    md = "\n".join(parts)
    wc = len(md.split())
    if wc < 10:
        return None
    return {
        "title": title,
        "author": author,
        "markdown": md,
        "content": md,
        "word_count": wc,
        "extraction_method": "hn-algolia",
    }


# ─── arXiv ─────────────────────────────────────────────────────────────
# /abs/ pages have lots of chrome. The export.arxiv.org API returns clean
# Atom XML with abstract, authors, categories. PDF URLs fall through to the
# PDF extractor (handled elsewhere) — we just upgrade /abs/ pages here.

_ARXIV_ABS_RE = re.compile(
    r"^https?://arxiv\.org/abs/([\w\.\-/]+)(?:v\d+)?(?:[\?#].*)?$", re.I,
)

async def _arxiv(url: str, client: httpx.AsyncClient) -> Optional[dict]:
    m = _ARXIV_ABS_RE.match(url)
    if not m:
        return None
    paper_id = m.group(1)
    try:
        r = await client.get(
            f"https://export.arxiv.org/api/query?id_list={paper_id}", timeout=15.0,
        )
    except Exception:
        return None
    if r.status_code != 200:
        return None
    text = r.text
    # Tiny atom parser — avoid pulling lxml just for one feed
    def _tag(name: str) -> Optional[str]:
        mt = re.search(rf"<{name}[^>]*>(.*?)</{name}>", text, re.S)
        return mt.group(1).strip() if mt else None

    title = _tag("title")
    summary = _tag("summary")
    if title:
        # Strip the wrapper "ArXiv Query: search_query=..." entry — that's
        # the first <title>. Take the second (per-entry) one.
        titles = re.findall(r"<entry>.*?<title[^>]*>(.*?)</title>", text, re.S)
        if titles:
            title = titles[0].strip()
    authors = re.findall(r"<author>\s*<name>(.*?)</name>", text, re.S)
    published = _tag("published")
    pdf_url = f"https://arxiv.org/pdf/{paper_id}.pdf"

    if not summary:
        return None
    md_parts = [f"# {title or paper_id}"]
    if authors:
        md_parts.append("*Authors: " + ", ".join(a.strip() for a in authors) + "*")
    if published:
        md_parts.append(f"*Published: {published}*")
    md_parts.append(f"\n[PDF]({pdf_url}) · [arXiv:{paper_id}](https://arxiv.org/abs/{paper_id})\n")
    md_parts.append("## Abstract\n")
    md_parts.append(html.unescape(summary))
    md = "\n".join(md_parts)
    return {
        "title": title,
        "author": ", ".join(a.strip() for a in authors) if authors else None,
        "published": published,
        "markdown": md,
        "content": md,
        "word_count": len(md.split()),
        "extraction_method": "arxiv-api",
    }


# ─── Twitter / X via syndication ───────────────────────────────────────
# Public profiles + tweets are reachable through syndication.twitter.com
# without login. Higher rate-limits than the regular API. Not perfect for
# replies but works for tip-of-iceberg feeds.

_TWITTER_PROFILE_RE = re.compile(
    r"^https?://(?:www\.|mobile\.)?(?:twitter\.com|x\.com)/(\w{1,15})/?(?:[\?#].*)?$",
    re.I,
)
_TWITTER_STATUS_RE = re.compile(
    r"^https?://(?:www\.|mobile\.)?(?:twitter\.com|x\.com)/\w+/status/(\d+)",
    re.I,
)

_RESERVED_TWITTER_PATHS = {
    "home", "explore", "notifications", "messages", "search", "i", "intent",
    "compose", "settings", "login", "signup", "tos", "privacy",
}

async def _twitter(url: str, client: httpx.AsyncClient) -> Optional[dict]:
    # Single tweet
    ms = _TWITTER_STATUS_RE.match(url)
    if ms:
        tweet_id = ms.group(1)
        try:
            r = await client.get(
                f"https://cdn.syndication.twimg.com/tweet-result?id={tweet_id}&token=a",
                timeout=15.0,
            )
        except Exception:
            return None
        if r.status_code != 200:
            return None
        try:
            d = r.json()
        except Exception:
            return None
        text = d.get("text") or ""
        if not text:
            return None
        u = d.get("user", {}) or {}
        title = f"@{u.get('screen_name', '?')}: {text[:60]}"
        md = (
            f"# Tweet by @{u.get('screen_name', '?')} ({u.get('name', '?')})\n"
            f"*{d.get('created_at', '')}*\n\n{text}\n"
        )
        return {
            "title": title,
            "author": u.get("screen_name"),
            "published": d.get("created_at"),
            "markdown": md,
            "content": md,
            "word_count": len(md.split()),
            "extraction_method": "twitter-syndication",
        }

    # Profile
    mp = _TWITTER_PROFILE_RE.match(url)
    if not mp:
        return None
    screen_name = mp.group(1)
    if screen_name.lower() in _RESERVED_TWITTER_PATHS:
        return None
    try:
        r = await client.get(
            f"https://syndication.twitter.com/srv/timeline-profile/screen-name/{screen_name}",
            timeout=20.0,
            headers={"User-Agent": "Mozilla/5.0"},
        )
    except Exception:
        return None
    if r.status_code != 200:
        return None
    # The page embeds an inline __INITIAL_STATE__ JSON blob with tweets
    body = r.text
    m_state = re.search(
        r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
        body,
        re.S,
    )
    if not m_state:
        return None
    try:
        state = json.loads(m_state.group(1))
    except Exception:
        return None
    timeline = (
        state.get("props", {})
        .get("pageProps", {})
        .get("timeline", {})
        .get("entries", [])
    )
    if not timeline:
        return None
    parts = [f"# @{screen_name}"]
    bio_user = None
    for e in timeline:
        content = e.get("content", {}) or {}
        item = content.get("tweet") or content.get("user")
        if not item:
            continue
        if "full_text" in item:
            user = item.get("user", {}) or {}
            handle = user.get("screen_name") or screen_name
            text = item.get("full_text") or ""
            created = item.get("created_at", "")
            parts.append(f"\n---\n**@{handle}** *{created}*\n\n{text}")
        elif "description" in item and not bio_user:
            bio_user = item
            parts.insert(1, f"*{item.get('description', '')}*")
    if len(parts) < 2:
        return None
    md = "\n".join(parts)
    return {
        "title": f"@{screen_name}",
        "author": screen_name,
        "markdown": md,
        "content": md,
        "word_count": len(md.split()),
        "extraction_method": "twitter-syndication",
    }


# ─── GitHub issues / PRs ───────────────────────────────────────────────
# REST API gives structured issue+comments. Unauthenticated calls get
# 60/hour, so use the token if it's set (GITHUB_TOKEN env).
_GH_ISSUE_RE = re.compile(
    r"^https?://github\.com/([\w\.\-]+)/([\w\.\-]+)/(issues|pull)/(\d+)",
    re.I,
)

async def _github(url: str, client: httpx.AsyncClient) -> Optional[dict]:
    import os
    m = _GH_ISSUE_RE.match(url)
    if not m:
        return None
    owner, repo, kind, num = m.groups()
    headers = {"Accept": "application/vnd.github+json"}
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        headers["Authorization"] = f"Bearer {tok}"

    # Issues and pulls use the same /issues path for the head; comments live
    # at /issues/N/comments regardless.
    base = f"https://api.github.com/repos/{owner}/{repo}/issues/{num}"
    try:
        r = await client.get(base, headers=headers, timeout=15.0)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    try:
        head = r.json()
    except Exception:
        return None
    body_parts = [
        f"# [{kind.upper()}] {head.get('title') or '(untitled)'}",
        f"*{owner}/{repo}#{num} · by {(head.get('user') or {}).get('login', '?')} · "
        f"state: {head.get('state', '?')} · {head.get('created_at', '')}*",
        "",
        head.get("body") or "(no description)",
    ]
    # Comments
    try:
        rc = await client.get(f"{base}/comments?per_page=100",
                              headers=headers, timeout=15.0)
        if rc.status_code == 200:
            for c in rc.json():
                who = (c.get("user") or {}).get("login", "?")
                when = c.get("created_at", "")
                body_parts.append(f"\n---\n**@{who}** *{when}*\n\n{c.get('body') or ''}")
    except Exception:
        pass

    md = "\n".join(body_parts)
    return {
        "title": head.get("title"),
        "author": (head.get("user") or {}).get("login"),
        "published": head.get("created_at"),
        "markdown": md,
        "content": md,
        "word_count": len(md.split()),
        "extraction_method": "github-api",
    }


# ─── Dispatcher ────────────────────────────────────────────────────────
_EXTRACTORS = [
    ("reddit",  _reddit),
    ("youtube", _youtube),
    ("hn",      _hn),
    ("arxiv",   _arxiv),
    ("twitter", _twitter),
    ("github",  _github),
]


async def try_domain_extract(url: str, client: Optional[httpx.AsyncClient] = None) -> Optional[dict]:
    """Run domain extractors in order. Return the first non-None result.
    Returns None if no extractor matched or the matching one fell through.
    """
    if client is None:
        async with httpx.AsyncClient(follow_redirects=True) as c:
            return await try_domain_extract(url, c)
    for name, fn in _EXTRACTORS:
        try:
            res = await fn(url, client)
        except Exception as e:
            log.warning("domain_extract_err name=%s url=%s err=%s",
                        name, url[:120], e)
            continue
        if res is not None:
            log.info("domain_extract_ok name=%s url=%s words=%d",
                     name, url[:120], res.get("word_count", 0))
            return res
    return None
