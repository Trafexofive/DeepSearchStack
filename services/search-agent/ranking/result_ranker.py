
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from typing import List
from urllib.parse import urlparse
import logging

from common.models import SearchResult, SortMethod

logger = logging.getLogger(__name__)

class ResultRanker:
    """Advanced ranking system for search results"""
    
    def __init__(self):
        self.vectorizer = TfidfVectorizer(stop_words='english')
        self.domain_authority = {
            "wikipedia.org": 0.95,
            "github.com": 0.9,
            "arxiv.org": 0.85,
            "scholar.google.com": 0.9,
            "medium.com": 0.7,
            "stackexchange.com": 0.85,
            "stackoverflow.com": 0.88,
        }
        
    def _extract_domain(self, url):
        try:
            return urlparse(url).netloc.lower()
        except: return ""
            
    def _calculate_relevance_score(self, query, results):
        if not results: return []
        corpus = [f"{r.title} {r.description}" for r in results]
        corpus.insert(0, query)
        try:
            tfidf_matrix = self.vectorizer.fit_transform(corpus)
            cosine_similarities = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:]).flatten()
            for idx, score in enumerate(cosine_similarities):
                results[idx].confidence = float(score)
        except Exception as e:
            logger.warning(f"Error calculating relevance scores: {e}")
        return results
        
    def _apply_domain_authority(self, results):
        for result in results:
            domain = self._extract_domain(result.url)
            base_domain = '.'.join(domain.split('.')[-2:]) if domain.count('.') > 1 else domain
            authority = self.domain_authority.get(domain) or self.domain_authority.get(base_domain, 0.5)
            result.domain_authority = authority
            result.confidence = 0.7 * result.confidence + 0.3 * authority
        return results
        
    def rank_results(self, query: str, results: List[SearchResult], sort_method: SortMethod = SortMethod.RELEVANCE) -> List[SearchResult]:
        """Rank search results based on the specified method"""
        if not results: return []
        results = self._calculate_relevance_score(query, results)
        results = self._apply_domain_authority(results)
        
        if sort_method == SortMethod.RELEVANCE:
            results.sort(key=lambda x: x.confidence, reverse=True)
        elif sort_method == SortMethod.DATE:
            results.sort(key=lambda x: (x.published_date or "", x.confidence), reverse=True)
        elif sort_method == SortMethod.SOURCE_QUALITY:
            results.sort(key=lambda x: (x.domain_authority or 0, x.confidence), reverse=True)
        
        for i, result in enumerate(results):
            result.rank = i + 1
        return results
