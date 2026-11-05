"""
Search Provider Manager — 13 providers across 8 domains.

Direct API providers (all free, no API keys required):
  web: searxng, yacy, duckduckgo
  encyclopedia: wikipedia
  q_and_a: stackexchange
  academic: arxiv, pubmed, crossref
  code: github
  social_news: hackernews
  social: reddit
  archive: internetarchive
"""

import os
import httpx
import time
import logging
import json
import re
import html
from typing import List, Dict, Optional
import xml.etree.ElementTree as ET

from search_gateway.common.models import SearchProvider, SearchResult, SearchGatewayRequest as SearchRequest
from search_gateway.utils.system_components import MetricsCollector, CircuitBreaker

logger = logging.getLogger("providers.provider_manager")

HEADERS = {"User-Agent": "DeepSearchStack/1.0 (research bot; contact@deepsearchstack.local)"}

# Reddit requires a specific User-Agent format — blocks generic ones with 403
REDDIT_HEADERS = {"User-Agent": "python:deepsearchstack:v1.0 (by /u/deepsearch_bot)"}

# arXiv rate limiting — max 1 request per 3s per their ToS
_ARXIV_LAST_REQUEST = 0.0
_ARXIV_MIN_INTERVAL = 3.0


class SearchProviderManager:
    """Manages connections and requests to 13 free search providers across 8 domains."""

    def __init__(self, metrics: MetricsCollector, circuit_breaker: CircuitBreaker):
        self.metrics = metrics
        self.circuit_breaker = circuit_breaker
        self.providers = {
            # ── Web Search ──────────────────────────────────────────────
            SearchProvider.SEARXNG: {
                "url": os.environ.get("SEARXNG_URL", "http://searxng:8080"),
                "weight": 1.0, "parser": self._parse_searxng,
            },
            SearchProvider.YACY: {
                "url": os.environ.get("YACY_URL", "http://yacy:8090"),
                "weight": 0.8, "parser": self._parse_yacy,
            },
            SearchProvider.DUCKDUCKGO: {
                "url": "https://api.duckduckgo.com/",
                "weight": 1.1, "parser": self._parse_duckduckgo,
            },
            # ── Encyclopedia ────────────────────────────────────────────
            SearchProvider.WIKIPEDIA: {
                "url": "https://en.wikipedia.org/w/api.php",
                "weight": 1.2, "parser": self._parse_wikipedia,
            },
            # ── Q&A ────────────────────────────────────────────────────
            SearchProvider.STACKEXCHANGE: {
                "url": "https://api.stackexchange.com/2.3/search/advanced",
                "weight": 1.2, "parser": self._parse_stackexchange,
            },
            # ── Academic ────────────────────────────────────────────────
            SearchProvider.ARXIV: {
                "url": "https://export.arxiv.org/api/query",
                "weight": 1.2, "parser": self._parse_arxiv,
            },
            SearchProvider.PUBMED: {
                "url": "https://eutils.ncbi.nlm.nih.gov/entrez/eutils",
                "weight": 1.3, "parser": self._parse_pubmed,
            },
            SearchProvider.CROSSREF: {
                "url": "https://api.crossref.org/works",
                "weight": 1.2, "parser": self._parse_crossref,
            },
            # ── Code ────────────────────────────────────────────────────
            SearchProvider.GITHUB: {
                "url": "https://api.github.com/search/repositories",
                "weight": 1.1, "parser": self._parse_github,
            },
            # ── Social / News ───────────────────────────────────────────
            SearchProvider.HACKERNEWS: {
                "url": "https://hn.algolia.com/api/v1/search",
                "weight": 1.1, "parser": self._parse_hackernews,
            },
            SearchProvider.REDDIT: {
                "url": "https://www.reddit.com/search.json",
                "weight": 0.9, "parser": self._parse_reddit,
            },
            # ── Archive ─────────────────────────────────────────────────
            SearchProvider.INTERNET_ARCHIVE: {
                "url": "https://archive.org/advancedsearch.php",
                "weight": 0.9, "parser": self._parse_internetarchive,
            },
            # ── Additional Primary Sources ──────────────────────────────
            SearchProvider.OPENALEX: {
                "url": "https://api.openalex.org/works",
                "weight": 1.25, "parser": self._parse_openalex,
            },
            SearchProvider.MDN: {
                "url": "https://developer.mozilla.org/api/v1/search",
                "weight": 1.2, "parser": self._parse_mdn,
            },
            SearchProvider.ARCHWIKI: {
                "url": "https://wiki.archlinux.org/api.php",
                "weight": 1.15, "parser": self._parse_archwiki,
            },
            SearchProvider.CRATES_IO: {
                "url": "https://crates.io/api/v1/crates",
                "weight": 1.2, "parser": self._parse_crates,
            },
            SearchProvider.NPM: {
                "url": "https://registry.npmjs.org/-/v1/search",
                "weight": 1.15, "parser": self._parse_npm,
            },
            SearchProvider.IETF: {
                "url": "https://datatracker.ietf.org/api/v1/doc/document/",
                "weight": 1.25, "parser": self._parse_ietf,
            },
            SearchProvider.NVD: {
                "url": "https://services.nvd.nist.gov/rest/json/cves/2.0",
                "weight": 1.3, "parser": self._parse_nvd,
            },
            SearchProvider.GITHUB_ISSUES: {
                "url": "https://api.github.com/search/issues",
                "weight": 1.15, "parser": self._parse_github_issues,
            },
            # ── Wikimedia Sister Projects ──────────────────────────────
            SearchProvider.WIKIBOOKS: {
                "url": "https://en.wikibooks.org/w/api.php",
                "weight": 1.2, "parser": self._parse_wikibooks,
            },
            SearchProvider.WIKIVERSITY: {
                "url": "https://en.wikiversity.org/w/api.php",
                "weight": 1.15, "parser": self._parse_wikiversity,
            },
            SearchProvider.WIKISOURCE: {
                "url": "https://en.wikisource.org/w/api.php",
                "weight": 1.15, "parser": self._parse_wikisource,
            },
            SearchProvider.WIKIDATA: {
                "url": "https://www.wikidata.org/w/api.php",
                "weight": 1.1, "parser": self._parse_wikidata,
            },
            # ── Additional Primary Repositories & Open Access ───────────
            SearchProvider.GITLAB: {
                "url": "https://gitlab.com/api/v4/projects",
                "weight": 1.15, "parser": self._parse_gitlab,
            },
            SearchProvider.DOAJ: {
                "url": "https://doaj.org/api/v2/search/articles",
                "weight": 1.25, "parser": self._parse_doaj,
            },
            SearchProvider.PYPI: {
                "url": "https://pypi.org/pypi",
                "weight": 1.2, "parser": self._parse_pypi,
            },
        }

    def get_provider_status(self) -> Dict[str, str]:
        return {name.value: "enabled" for name in self.providers}

    async def query_provider(self, client: httpx.AsyncClient, provider: SearchProvider,
                             query: str, request: SearchRequest) -> Optional[List[SearchResult]]:
        cfg = self.providers.get(provider)
        if not cfg:
            return None
        if await self.circuit_breaker.is_open(provider.value):
            logger.warning("Circuit breaker open: %s", provider.value)
            return None

        try:
            params: dict = {}
            headers = dict(HEADERS)
            url = cfg["url"]

            # ── URL + param construction per provider ──────────────────
            if provider == SearchProvider.SEARXNG:
                url = f"{url}/search"
                params = {"q": query, "format": "json", "language": "en"}
            elif provider == SearchProvider.YACY:
                url = f"{url}/yacysearch.json"
                params = {"query": query, "maximumRecords": 20}
            elif provider in (SearchProvider.WIKIPEDIA, SearchProvider.WIKIBOOKS, SearchProvider.WIKIVERSITY, SearchProvider.WIKISOURCE, SearchProvider.WIKIDATA):
                params = {"action": "query", "list": "search", "srsearch": query,
                          "format": "json", "srlimit": 10}
            elif provider == SearchProvider.DUCKDUCKGO:
                params = {"q": query, "format": "json", "no_html": 1}
            elif provider == SearchProvider.STACKEXCHANGE:
                params = {"order": "desc", "sort": "relevance", "q": query,
                          "site": "stackoverflow", "pagesize": 10}
            elif provider == SearchProvider.ARXIV:
                params = {"search_query": f"all:{query}", "start": 0, "max_results": 10}
                # Respect arXiv rate limit: 1 request per 3 seconds
                # BUGFIX: was UnboundLocalError — module-level _ARXIV_LAST_REQUEST
                # can't be assigned inside a function without `global`. Use the
                # circuit-breaker's throttling instead (already has rate limit
                # machinery) or declare global. We use `global` here to keep
                # the fix local and behavior identical.
                global _ARXIV_LAST_REQUEST
                import asyncio as _asyncio_arxiv
                now = time.monotonic()
                wait = _ARXIV_MIN_INTERVAL - (now - _ARXIV_LAST_REQUEST)
                if wait > 0:
                    await _asyncio_arxiv.sleep(wait)
                _ARXIV_LAST_REQUEST = time.monotonic()
            elif provider == SearchProvider.PUBMED:
                url = f"{url}/esearch.fcgi"
                params = {"db": "pubmed", "term": query, "retmode": "json",
                          "retmax": 10, "sort": "relevance"}
            elif provider == SearchProvider.CROSSREF:
                params = {"query": query, "rows": 10, "sort": "relevance"}
            elif provider == SearchProvider.GITHUB:
                params = {"q": query, "sort": "stars", "per_page": 10, "order": "desc"}
                headers["Accept"] = "application/vnd.github.v3+json"
            elif provider == SearchProvider.HACKERNEWS:
                params = {"query": query, "tags": "story", "hitsPerPage": 10}
            elif provider == SearchProvider.REDDIT:
                params = {"q": query, "limit": 10, "sort": "relevance", "type": "link"}
                headers.update(REDDIT_HEADERS)
            elif provider == SearchProvider.OPENALEX:
                params = {"search": query, "per-page": 10}
            elif provider == SearchProvider.MDN:
                params = {"q": query, "size": 10}
            elif provider == SearchProvider.ARCHWIKI:
                params = {"action": "query", "list": "search", "srsearch": query, "format": "json", "srlimit": 10}
                headers["User-Agent"] = "DeepSearchStack/1.0 (https://github.com/Trafexofive/DeepSearchStack; contact@deepsearch.local)" 
            elif provider == SearchProvider.CRATES_IO:
                # Use primary identifier or unquoted terms for Crates.io
                crates_q = query.split()[0] if len(query.split()) > 1 and not any(ch in query for ch in ":/") else query
                params = {"q": crates_q, "per_page": 10}
                headers["User-Agent"] = "DeepSearchStack/1.0 (https://github.com/Trafexofive/DeepSearchStack)"
            elif provider == SearchProvider.NPM:
                params = {"text": query, "size": 10}
            elif provider == SearchProvider.IETF:
                # IETF matches exact substring; extract primary token (e.g. HTTP/3, QUIC, BGP, TLS)
                primary_token = query.split()[0]
                params = {"title__icontains": primary_token, "format": "json", "limit": 10}
            elif provider == SearchProvider.NVD:
                params = {"keywordSearch": query, "resultsPerPage": 5}
            elif provider == SearchProvider.GITHUB_ISSUES:
                params = {"q": query, "sort": "updated", "per_page": 10, "order": "desc"}
                headers["Accept"] = "application/vnd.github.v3+json"
            elif provider == SearchProvider.GITLAB:
                params = {"search": query, "per_page": 10}
            elif provider == SearchProvider.DOAJ:
                import urllib.parse
                safe_q = urllib.parse.quote(query)
                url = f"{url}/{safe_q}"
                params = {"pageSize": 10}
                headers["User-Agent"] = "DeepSearchStack/1.0 (https://github.com/Trafexofive/DeepSearchStack; contact@deepsearch.local)" 
            elif provider == SearchProvider.PYPI:
                tokens = [t for t in query.lower().split() if len(t) > 1 and not t.startswith("-")]
                pkg_token = tokens[0] if tokens else query.strip().lower()
                url = f"{url}/{pkg_token}/json"
                params = {}
            elif provider == SearchProvider.INTERNET_ARCHIVE:
                params = {"q": f"title:({query}) OR description:({query})",
                          "output": "json", "rows": 10,
                          "fl[]": ["title", "description", "identifier", "mediatype"]}

            response = await client.get(url, params=params, headers=headers,
                                        timeout=request.timeout, follow_redirects=True)
            logger.info("Provider %s → %d", provider.value, response.status_code)

            # ── Proxy-rotator retry for IP-blocked providers ─────────────
            # Reddit (and some others) block server IPs. If we get a
            # 403/429/451 on a provider that's known to IP-block, retry
            # through the proxy-rotator service. PROXY_ROTATOR_URL env
            # points at an HTTP proxy (Tor via Privoxy by default).
            needs_proxy = (
                response.status_code in (403, 429, 451)
                and provider in {SearchProvider.REDDIT}
            )
            if needs_proxy:
                proxy_url = os.environ.get("PROXY_ROTATOR_URL")
                if proxy_url:
                    logger.warning("provider %s status=%d — retrying via proxy %s",
                                   provider.value, response.status_code, proxy_url)
                    try:
                        # httpx 0.28+: pass a single `proxy=` (was `proxies={...}`).
                        async with httpx.AsyncClient(
                            timeout=request.timeout + 10,
                            proxy=proxy_url,
                            follow_redirects=True,
                        ) as pclient:
                            response = await pclient.get(url, params=params, headers=headers)
                            logger.info("Provider %s (via proxy) → %d",
                                        provider.value, response.status_code)
                    except Exception as e:
                        logger.warning("proxy retry failed for %s: %s", provider.value, e)

            response.raise_for_status()

            # ── Parse ──────────────────────────────────────────────────
            if provider == SearchProvider.ARXIV:
                results = cfg["parser"](response.text, cfg["weight"])
            elif provider == SearchProvider.PUBMED:
                results = await self._parse_pubmed(client, response.json(), cfg["weight"])
            else:
                raw = response.json()
                results = cfg["parser"](raw, cfg["weight"])

            await self.circuit_breaker.record_success(provider.value)
            return results

        except Exception as e:
            logger.error("Provider '%s' failed: %s — %s", provider.value, type(e).__name__, str(e))
            await self.circuit_breaker.record_failure(provider.value)
            return None

    # ── Parsers ────────────────────────────────────────────────────────────

    def _parse_searxng(self, data, w):
        return [SearchResult(title=r.get("title", ""), url=r.get("url", ""),
                             description=r.get("content", ""), source="searxng", confidence=w)
                for r in data.get("results", []) if r.get("url")]

    def _parse_yacy(self, data, w):
        items = data.get("channels", [{}])[0].get("items", [])
        return [SearchResult(title=r.get("title", ""), url=r.get("link", ""),
                             description=r.get("description", ""), source="yacy", confidence=w * 0.8)
                for r in items if r.get("link")]

    def _parse_wikipedia(self, data, w):
        return [SearchResult(
            title=r.get("title", ""),
            url=f"https://en.wikipedia.org/wiki/{r.get('title', '').replace(' ', '_')}",
            description=re.sub(r"<.*?>", "", r.get("snippet", "")),
            source="wikipedia", confidence=w * 1.2,
        ) for r in data.get("query", {}).get("search", [])]

    def _parse_duckduckgo(self, data, w):
        if not isinstance(data, dict):
            return []
        results, seen = [], set()
        topics = data.get("RelatedTopics", [])
        for t in topics:
            if "Topics" in t:
                topics.extend(t["Topics"])
                continue
            url = t.get("FirstURL", "")
            text = t.get("Text", "")
            if url and text and "duckduckgo.com/c/" not in url and url not in seen:
                seen.add(url)
                results.append(SearchResult(
                    title=text.split(" - ")[0] if " - " in text else text[:80],
                    url=url, description=text, source="duckduckgo", confidence=w))
        if data.get("AbstractURL") and data.get("AbstractText") and "duckduckgo.com/c/" not in data.get("AbstractURL", ""):
            results.append(SearchResult(
                title=data.get("Heading", "Abstract"), url=data["AbstractURL"],
                description=data["AbstractText"], source="duckduckgo", confidence=w * 1.1))
        return results

    def _parse_stackexchange(self, data, w):
        return [SearchResult(
            title=html.unescape(r.get("title", "")), url=r.get("link", ""),
            description=f"Score: {r.get('score', 0)}, Answers: {r.get('answer_count', 0)}. "
                        f"By: {r.get('owner', {}).get('display_name', 'N/A')}",
            source="stackexchange", confidence=w * 1.2,
        ) for r in data.get("items", [])]

    def _parse_arxiv(self, xml_data, w):
        results = []
        try:
            if not xml_data.strip().startswith("<?xml"):
                return []
            xml_data = re.sub(r' xmlns="[^"]+"', "", xml_data, count=1)
            root = ET.fromstring(xml_data)
            for entry in root.findall("entry"):
                title = (entry.find("title").text or "").strip().replace("\n", " ").replace("  ", " ")
                url = (entry.find("id").text or "").strip()
                summary = (entry.find("summary").text or "").strip().replace("\n", " ")
                results.append(SearchResult(title=title, url=url, description=summary,
                                            source="arxiv", confidence=w * 1.3))
        except ET.ParseError as e:
            logger.error("arXiv parse error: %s", e)
        return results

    # ── NEW: PubMed (two-step: search → fetch summaries) ──────────────────

    async def _parse_pubmed(self, client: httpx.AsyncClient, data: dict, w: float) -> List[SearchResult]:
        ids = data.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        # Fetch summaries
        url = f"{self.providers[SearchProvider.PUBMED]['url']}/esummary.fcgi"
        params = {"db": "pubmed", "id": ",".join(ids[:10]), "retmode": "json"}
        resp = await client.get(url, params=params, headers=HEADERS, timeout=15.0)
        resp.raise_for_status()
        summaries = resp.json().get("result", {})
        results = []
        for pid in ids:
            s = summaries.get(pid, {})
            title = s.get("title", "")
            if not title:
                continue
            url_str = f"https://pubmed.ncbi.nlm.nih.gov/{pid}/"
            desc = s.get("elocationid", "") or s.get("source", "")
            authors = ", ".join([a.get("name", "") for a in s.get("authors", [])[:3]])
            if authors:
                desc = f"{authors}. {desc}"
            results.append(SearchResult(title=title, url=url_str, description=desc,
                                        source="pubmed", confidence=w * 1.3))
        return results

    # ── NEW: Hacker News (Algolia) ────────────────────────────────────────

    def _parse_hackernews(self, data, w):
        return [SearchResult(
            title=r.get("title", ""),
            url=r.get("url", "") or f"https://news.ycombinator.com/item?id={r.get('objectID', '')}",
            description=f"{r.get('points', 0)} points, {r.get('num_comments', 0)} comments. "
                        f"By {r.get('author', 'unknown')}",
            source="hackernews", confidence=w * 1.1,
        ) for r in data.get("hits", []) if r.get("title")]

    # ── NEW: GitHub Repositories ─────────────────────────────────────────

    def _parse_github(self, data, w):
        return [SearchResult(
            title=r.get("full_name", ""),
            url=r.get("html_url", ""),
            description=f"⭐ {r.get('stargazers_count', 0)} · {r.get('description', '') or r.get('language', '')}",
            source="github", confidence=w * 1.1,
        ) for r in data.get("items", []) if r.get("full_name")]

    # ── NEW: Reddit ──────────────────────────────────────────────────────

    def _parse_reddit(self, data, w):
        results = []
        for child in data.get("data", {}).get("children", []):
            d = child.get("data", {})
            if not d.get("title"):
                continue
            results.append(SearchResult(
                title=d["title"],
                url=f"https://www.reddit.com{d.get('permalink', '')}",
                description=f"r/{d.get('subreddit', '')} · {d.get('score', 0)} pts, "
                            f"{d.get('num_comments', 0)} comments",
                source="reddit", confidence=w * 0.9,
            ))
        return results

    # ── NEW: Internet Archive ─────────────────────────────────────────────

    def _parse_internetarchive(self, data, w):
        results = []
        docs = data.get("response", {}).get("docs", [])
        for d in docs:
            identifier = d.get("identifier", "")
            if not identifier:
                continue
            title = d.get("title", identifier)
            desc = d.get("description", "") or f"Media type: {d.get('mediatype', 'unknown')}"
            results.append(SearchResult(
                title=title,
                url=f"https://archive.org/details/{identifier}",
                description=desc[:300],
                source="internetarchive", confidence=w * 0.9,
            ))
        return results

    # ── NEW: Crossref (scholarly works) ───────────────────────────────────

    def _parse_crossref(self, data, w):
        results = []
        for item in data.get("message", {}).get("items", []):
            title = item.get("title", [""])[0] if item.get("title") else ""
            if not title:
                continue
            url = item.get("URL", "") or f"https://doi.org/{item.get('DOI', '')}"
            pub = item.get("publisher", "")
            year = item.get("created", {}).get("date-parts", [[None]])[0][0]
            desc = f"Published by {pub}" + (f" ({year})" if year else "")
            results.append(SearchResult(title=title, url=url, description=desc,
                                        source="crossref", confidence=w * 1.2))
        return results

    # ── Additional Primary Source Parsers ─────────────────────────────

    def _parse_openalex(self, data, w):
        results = []
        for r in data.get("results", []):
            title = r.get("display_name", "")
            if not title:
                continue
            url = r.get("doi") or (r.get("primary_location") or {}).get("landing_page_url")
            if not url:
                url = f"https://openalex.org/{r.get('id', '').split('/')[-1]}"
            desc = f"Year: {r.get('publication_year', 'N/A')} · Citations: {r.get('cited_by_count', 0)}"
            results.append(SearchResult(title=title, url=url, description=desc,
                                        source="openalex", confidence=w * 1.25))
        return results

    def _parse_mdn(self, data, w):
        results = []
        for doc in data.get("documents", []):
            title = doc.get("title", "")
            mdn_url = doc.get("mdn_url", "")
            if not mdn_url:
                continue
            url = f"https://developer.mozilla.org{mdn_url}"
            desc = doc.get("summary", "")
            results.append(SearchResult(title=title, url=url, description=desc,
                                        source="mdn", confidence=w * 1.2))
        return results

    def _parse_archwiki(self, data, w):
        results = []
        for r in data.get("query", {}).get("search", []):
            title = r.get("title", "")
            if not title:
                continue
            url = f"https://wiki.archlinux.org/title/{title.replace(' ', '_')}"
            snippet = r.get("snippet", "").replace("<span class=\"searchmatch\">", "").replace("</span>", "")
            results.append(SearchResult(
                title=f"{title} - ArchWiki", url=url, description=snippet,
                source="archwiki", confidence=w * 1.15
            ))
        return results

    def _parse_crates(self, data, w):
        results = []
        for c in data.get("crates", []):
            name = c.get("name", "")
            if not name:
                continue
            ver = c.get("max_version", "")
            title = f"{name} (v{ver})" if ver else name
            url = f"https://crates.io/crates/{name}"
            desc = c.get("description", "") or f"Rust crate {name}"
            results.append(SearchResult(title=title, url=url, description=desc[:250],
                                        source="crates", confidence=w * 1.2))
        return results

    def _parse_npm(self, data, w):
        results = []
        for obj in data.get("objects", []):
            pkg = obj.get("package", {})
            name = pkg.get("name", "")
            if not name:
                continue
            ver = pkg.get("version", "")
            title = f"{name} (v{ver})" if ver else name
            links = pkg.get("links", {}) or {}
            url = links.get("npm", f"https://www.npmjs.com/package/{name}")
            desc = pkg.get("description", "") or f"NPM package {name}"
            results.append(SearchResult(title=title, url=url, description=desc[:250],
                                        source="npm", confidence=w * 1.15))
        return results

    def _parse_ietf(self, data, w):
        results = []
        for obj in data.get("objects", []):
            title = obj.get("title", "")
            name = obj.get("name", "")
            if not name:
                continue
            url = f"https://datatracker.ietf.org/doc/{name}/"
            desc = obj.get("abstract", "") or f"IETF Internet standard / RFC document {name}"
            results.append(SearchResult(title=title or name, url=url, description=desc[:300],
                                        source="ietf", confidence=w * 1.25))
        return results

    def _parse_nvd(self, data, w):
        results = []
        for v in data.get("vulnerabilities", []):
            cve = v.get("cve", {})
            cve_id = cve.get("id", "")
            if not cve_id:
                continue
            descriptions = cve.get("descriptions", [])
            desc = descriptions[0].get("value", "") if descriptions else ""
            url = f"https://nvd.nist.gov/vuln/detail/{cve_id}"
            results.append(SearchResult(title=f"{cve_id}: {desc[:60]}...", url=url, description=desc[:300],
                                        source="nvd", confidence=w * 1.3))
        return results

    def _parse_github_issues(self, data, w):
        results = []
        for item in data.get("items", []):
            title = item.get("title", "")
            url = item.get("html_url", "")
            if not url:
                continue
            body = (item.get("body", "") or "")[:250].replace("\r\n", " ").replace("\n", " ")
            results.append(SearchResult(title=f"Issue: {title}", url=url, description=body,
                                        source="github_issues", confidence=w * 1.15))
        return results

    # ── Wikimedia Sister Project Parsers ─────────────────────────────

    def _parse_mediawiki_generic(self, data, w, domain, source_name):
        results = []
        for r in data.get("query", {}).get("search", []):
            title = r.get("title", "")
            if not title:
                continue
            url = f"https://{domain}/wiki/{title.replace(' ', '_')}"
            snippet = re.sub(r"<.*?>", "", r.get("snippet", ""))
            results.append(SearchResult(
                title=title, url=url, description=snippet,
                source=source_name, confidence=w
            ))
        return results

    def _parse_wikibooks(self, data, w):
        return self._parse_mediawiki_generic(data, w, "en.wikibooks.org", "wikibooks")

    def _parse_wikiversity(self, data, w):
        return self._parse_mediawiki_generic(data, w, "en.wikiversity.org", "wikiversity")

    def _parse_wikisource(self, data, w):
        return self._parse_mediawiki_generic(data, w, "en.wikisource.org", "wikisource")

    def _parse_wikidata(self, data, w):
        return self._parse_mediawiki_generic(data, w, "www.wikidata.org", "wikidata")

    # ── GitLab, DOAJ & PyPI Parsers ───────────────────────────────────

    def _parse_gitlab(self, data, w):
        results = []
        if isinstance(data, list):
            for p in data:
                name = p.get("name_with_namespace", "")
                url = p.get("web_url", "")
                desc = p.get("description", "") or f"GitLab project {name}"
                results.append(SearchResult(title=name, url=url, description=desc[:250],
                                            source="gitlab", confidence=w * 1.15))
        return results

    def _parse_doaj(self, data, w):
        results = []
        for r in data.get("results", []):
            bibjson = r.get("bibjson", {})
            title = bibjson.get("title", "")
            if not title:
                continue
            links = bibjson.get("link", [])
            url = links[0].get("url", "") if links else ""
            desc = bibjson.get("abstract", "") or f"Published in {bibjson.get('journal', {}).get('title', 'DOAJ')}"
            results.append(SearchResult(title=title, url=url, description=desc[:300],
                                        source="doaj", confidence=w * 1.25))
        return results

    def _parse_pypi(self, data, w):
        results = []
        info = data.get("info", {})
        name = info.get("name", "")
        if name:
            url = info.get("project_url") or info.get("package_url") or f"https://pypi.org/project/{name}/"
            desc = info.get("summary", "") or f"PyPI package {name} v{info.get('version', '')}"
            results.append(SearchResult(
                title=f"{name} (v{info.get('version', '')})",
                url=url, description=desc[:250],
                source="pypi", confidence=w * 1.2
            ))
        return results
