import re
import math
import logging
from typing import List, Dict, Tuple, Optional, Set
from urllib.parse import urlparse
from datetime import datetime

from libs.common.models import SearchResult, SortMethod
from libs.common.text import normalize_url

logger = logging.getLogger("result_ranker")

# Epistemic domain classification patterns
ARTIFACT_PATTERNS = {
    "paper": [
        "arxiv.org", "doi.org", "ncbi.nlm.nih.gov", "semanticscholar.org",
        "biorxiv.org", "medrxiv.org", "nature.com", "sciencedirect.com",
        "ieee.org", "acm.org", "springer.com", "usenix.org"
    ],
    "code": [
        "github.com", "gitlab.com", "bitbucket.org", "crates.io",
        "pypi.org", "pkg.go.dev", "npmjs.com", "sourceforge.net"
    ],
    "spec": [
        "ietf.org", "w3.org", "rfc-editor.org", "iso.org",
        "tc39.es", "ecma-international.org", "man7.org"
    ],
    "qna": [
        "stackoverflow.com", "stackexchange.com", "serverfault.com",
        "askubuntu.com", "quora.com"
    ],
    "discussion": [
        "news.ycombinator.com", "reddit.com", "lobste.rs"
    ],
    "reference": [
        "wikipedia.org", "wikibooks.org", "wiktionary.org",
        "plato.stanford.edu", "britannica.com", "developer.mozilla.org"
    ]
}

# Domain baseline authority weights (0.0 to 1.0)
HIGH_AUTHORITY_DOMAINS = {
    "nvd.nist.gov": 0.98,
    "datatracker.ietf.org": 0.98,
    "rfc-editor.org": 0.98,
    "developer.mozilla.org": 0.95,
    "wikipedia.org": 0.95,
    "usenix.org": 0.95,
    "ietf.org": 0.95,
    "arxiv.org": 0.92,
    "openalex.org": 0.92,
    "wiki.archlinux.org": 0.92,
    "github.com": 0.92,
    "crates.io": 0.90,
    "npmjs.com": 0.88,
    "stackoverflow.com": 0.88,
    "stackexchange.com": 0.85,
    "news.ycombinator.com": 0.85,
}

# Default provider weights for RRF
PROVIDER_WEIGHTS = {
    "nvd": 1.3,
    "pubmed": 1.3,
    "openalex": 1.25,
    "ietf": 1.25,
    "arxiv": 1.25,
    "wikipedia": 1.2,
    "crossref": 1.2,
    "crates": 1.2,
    "mdn": 1.2,
    "stackexchange": 1.2,
    "github": 1.15,
    "github_issues": 1.15,
    "archwiki": 1.15,
    "npm": 1.15,
    "hackernews": 1.1,
    "duckduckgo": 1.1,
    "searxng": 1.0,
    "reddit": 0.9,
    "archive": 0.9,
    "yacy": 0.8,
}

RRF_K = 60  # Industry standard smoothing constant


class ResultRanker:
    """Production-grade Reciprocal Rank Fusion (RRF) & Consensus ranker.

    Fuses multiple independent search provider outputs by:
    1. Canonical URL normalization and deduplication
    2. Multi-engine positional Reciprocal Rank Fusion
    3. Cross-provider consensus boosting (agreement multiplier)
    4. Epistemic artifact classification (paper, code, spec, qna, discussion)
    5. Term coverage scoring against query
    """

    def _extract_domain(self, url: str) -> str:
        try:
            netloc = urlparse(url).netloc.lower()
            if netloc.startswith("www."):
                netloc = netloc[4:]
            return netloc
        except Exception:
            return ""

    def classify_artifact(self, url: str) -> str:
        domain = self._extract_domain(url)
        for artifact_type, patterns in ARTIFACT_PATTERNS.items():
            for pat in patterns:
                if pat in domain:
                    return artifact_type
        if domain.endswith(".edu") or domain.endswith(".gov"):
            return "academic_or_gov"
        return "web"

    def get_domain_authority(self, url: str) -> float:
        domain = self._extract_domain(url)
        if not domain:
            return 0.5
        for auth_domain, score in HIGH_AUTHORITY_DOMAINS.items():
            if domain == auth_domain or domain.endswith("." + auth_domain):
                return score
        if domain.endswith(".gov") or domain.endswith(".edu"):
            return 0.88
        if domain.endswith(".org"):
            return 0.75
        return 0.55

    def _term_coverage(self, query: str, title: str, description: str) -> float:
        """Calculate lexical term coverage of query in title/description."""
        q_tokens = set(re.findall(r"\w+", query.lower()))
        if not q_tokens:
            return 0.5
        doc_tokens = set(re.findall(r"\w+", f"{title} {description}".lower()))
        matched = q_tokens.intersection(doc_tokens)
        return len(matched) / len(q_tokens)

    def fuse_and_rank(
        self,
        query: str,
        provider_results: List[Tuple[str, List[SearchResult]]],
        sort_method: SortMethod = SortMethod.RELEVANCE,
        offset: int = 0,
        max_results: int = 15,
    ) -> List[SearchResult]:
        """Fuse and rank results from multiple search providers using RRF and Consensus."""
        if not provider_results:
            return []

        # Step 1: Group and deduplicate by canonical URL
        # canonical_url -> {
        #   "item": SearchResult,
        #   "sources": set,
        #   "ranks": {provider: rank_idx},
        #   "best_title": str,
        #   "best_desc": str
        # }
        fused: Dict[str, dict] = {}

        for provider, results in provider_results:
            p_weight = PROVIDER_WEIGHTS.get(provider.lower(), 1.0)
            for rank_idx, res in enumerate(results):
                if not res.url:
                    continue
                can_url = normalize_url(res.url)
                if can_url not in fused:
                    fused[can_url] = {
                        "item": res,
                        "sources": set(),
                        "ranks": {},
                        "best_title": res.title or "",
                        "best_desc": res.description or "",
                    }
                entry = fused[can_url]
                entry["sources"].add(provider)
                if provider not in entry["ranks"]:
                    entry["ranks"][provider] = rank_idx
                # Keep the more informative title and snippet
                if len(res.title or "") > len(entry["best_title"]):
                    entry["best_title"] = res.title
                if len(res.description or "") > len(entry["best_desc"]):
                    entry["best_desc"] = res.description

        if not fused:
            return []

        # Step 2: Compute RRF, Consensus, Domain Authority, and Term Overlap
        scored_items: List[SearchResult] = []
        raw_scores: List[float] = []

        for can_url, data in fused.items():
            base_item: SearchResult = data["item"]
            sources = data["sources"]
            ranks = data["ranks"]

            # 2a. Reciprocal Rank Fusion
            rrf_score = 0.0
            for prov, r_idx in ranks.items():
                w = PROVIDER_WEIGHTS.get(prov.lower(), 1.0)
                rrf_score += w * (1.0 / (RRF_K + r_idx + 1))

            # 2b. Consensus Multiplier (Agreement across independent engines)
            num_sources = len(sources)
            consensus_mult = 1.0 + 0.35 * (num_sources - 1)

            # 2c. Domain Authority
            domain_auth = self.get_domain_authority(base_item.url)

            # 2d. Term Coverage
            term_cov = self._term_coverage(query, data["best_title"], data["best_desc"])

            # 2e. Composite Score
            # RRF is the backbone; consensus boosts agreed hits; authority and coverage calibrate.
            composite = rrf_score * consensus_mult * (0.6 + 0.4 * domain_auth) * (0.7 + 0.3 * term_cov)
            raw_scores.append(composite)

            # Hydrate clean fields
            base_item.title = data["best_title"]
            base_item.description = data["best_desc"]
            base_item.domain_authority = round(domain_auth, 3)
            # Store primary source provider or joined sources
            base_item.source = "+".join(sorted(sources))
            base_item.confidence = composite  # will normalize below
            scored_items.append(base_item)

        # Step 3: Score Normalization into [0.05, 0.99]
        if raw_scores:
            max_s = max(raw_scores)
            min_s = min(raw_scores)
            span = max_s - min_s if max_s > min_s else 1.0
            for item in scored_items:
                norm = 0.35 + 0.60 * ((item.confidence - min_s) / span)
                item.confidence = round(norm, 3)

        # Step 4: Sorting
        if sort_method == SortMethod.DATE:
            scored_items.sort(key=lambda x: (x.published_date or datetime.min, x.confidence), reverse=True)
        elif str(sort_method.value if hasattr(sort_method, "value") else sort_method) == "source_quality":
            scored_items.sort(key=lambda x: (x.domain_authority or 0.0, x.confidence), reverse=True)
        else:  # RELEVANCE
            scored_items.sort(key=lambda x: x.confidence, reverse=True)

        # Step 5: Assign rank numbers
        final_list = scored_items[offset:offset + max_results]
        for idx, item in enumerate(final_list):
            item.rank = offset + idx + 1

        return final_list

    # Backwards compatibility alias
    def rank_results(self, query: str, results: List[SearchResult], sort_method: SortMethod = SortMethod.RELEVANCE) -> List[SearchResult]:
        if not results:
            return []
        grouped = {}
        for r in results:
            grouped.setdefault(r.source, []).append(r)
        return self.fuse_and_rank(query, list(grouped.items()), sort_method=sort_method, max_results=len(results))
