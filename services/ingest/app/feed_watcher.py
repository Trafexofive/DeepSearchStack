"""RSS/Atom feed poller — detects new entries."""

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import List, Optional
from xml.etree import ElementTree as ET

import httpx
from dateutil import parser as dateparser

log = logging.getLogger("ingest.feed_watcher")


class FeedWatcher:
    """Polls RSS/Atom feeds and returns new entries."""

    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    _ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "rss": "",
        "dc": "http://purl.org/dc/elements/1.1/",
        "content": "http://purl.org/rss/1.0/modules/content/",
    }

    async def poll(self, feed_url: str) -> List[dict]:
        """Fetch and parse feed, return list of entry dicts."""
        resp = await self.client.get(feed_url, follow_redirects=True, timeout=30.0)
        resp.raise_for_status()
        feed_xml = resp.text

        root = ET.fromstring(feed_xml)
        entries = []

        # RSS 2.0
        for item in root.iter("item"):
            entries.append(self._parse_rss(item))

        # Atom
        for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
            entries.append(self._parse_atom(entry))

        # Sort by date descending
        entries.sort(key=lambda e: e.get("published", ""), reverse=True)
        return entries

    def _parse_rss(self, item) -> dict:
        def t(tag):
            el = item.find(tag)
            return el.text.strip() if el is not None and el.text else ""

        published = t("pubDate")
        if published:
            try:
                published = dateparser.parse(published).isoformat()
            except Exception:
                published = datetime.now(timezone.utc).isoformat()

        guid = t("guid") or t("link") or hashlib.sha256((t("title") + t("link")).encode()).hexdigest()

        return {
            "title": t("title"),
            "link": t("link"),
            "description": t("description"),
            "guid": guid,
            "published": published,
            "source": "rss",
        }

    def _parse_atom(self, entry) -> dict:
        def t(tag):
            el = entry.find(f"{{{self._ns['atom']}}}{tag}")
            return el.text.strip() if el is not None and el.text else ""

        # Atom links are in <link href="..."/>
        link_el = entry.find("{http://www.w3.org/2005/Atom}link")
        link = link_el.get("href", "") if link_el is not None else ""

        updated = t("updated") or t("published")
        if updated:
            try:
                updated = dateparser.parse(updated).isoformat()
            except Exception:
                updated = datetime.now(timezone.utc).isoformat()

        entry_id = t("id") or link or hashlib.sha256((t("title") + link).encode()).hexdigest()

        summary = t("summary")
        if not summary:
            content_el = entry.find("{http://www.w3.org/2005/Atom}content")
            summary = content_el.text.strip() if content_el is not None and content_el.text else ""

        return {
            "title": t("title"),
            "link": link,
            "description": summary,
            "guid": entry_id,
            "published": updated,
            "source": "atom",
        }
