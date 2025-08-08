import time
import redis.asyncio as redis
import logging
import hashlib
from typing import Dict, Any, Optional, List
from urllib.parse import urlparse

from common.models import SearchProvider, GatewayResponse, ResponseFormat, StreamingChunk

logger = logging.getLogger(__name__)

# --- Service Components ---

class MetricsCollector:
    """Collects and reports metrics about search performance"""
    
    def __init__(self):
        self.request_count = 0
        self.error_count = 0
        self.provider_latencies = {provider.value: [] for provider in SearchProvider}
        self.provider_success = {provider.value: 0 for provider in SearchProvider}
        self.provider_failure = {provider.value: 0 for provider in SearchProvider}
        self.start_time = time.time()
        
    def record_request(self):
        self.request_count += 1
        
    def record_error(self):
        self.error_count += 1
        
    def record_provider_latency(self, provider: str, latency: float, success: bool):
        if provider in self.provider_latencies:
            self.provider_latencies[provider].append(latency)
            if success:
                self.provider_success[provider] += 1
            else:
                self.provider_failure[provider] += 1
    
    def get_stats(self):
        uptime = time.time() - self.start_time
        avg_latencies = {
            p: sum(lats)/len(lats) if lats else 0 
            for p, lats in self.provider_latencies.items()
        }
        return {
            "uptime_seconds": uptime,
            "request_count": self.request_count,
            "error_rate": self.error_count / max(1, self.request_count),
            "provider_avg_latency_ms": {p: lat*1000 for p, lat in avg_latencies.items()},
            "provider_success_rates": {
                p: self.provider_success[p] / max(1, self.provider_success[p] + self.provider_failure[p])
                for p in SearchProvider
            }
        }

class RateLimiter:
    """Rate limiter for API endpoints"""
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.default_limit = 100  # requests per minute
        self.window = 60  # seconds
        
    async def is_rate_limited(self, identifier: str, limit: int = None) -> bool:
        """Check if the identifier has exceeded its rate limit"""
        limit = limit or self.default_limit
        current = await self.redis.incr(f"ratelimit:{identifier}")
        
        if current == 1:
            await self.redis.expire(f"ratelimit:{identifier}", self.window)
            
        return current > limit
        
    async def get_remaining(self, identifier: str, limit: int = None) -> int:
        """Get remaining requests allowed in the current window"""
        limit = limit or self.default_limit
        current = await self.redis.get(f"ratelimit:{identifier}")
        if not current:
            return limit
        return max(0, limit - int(current))

class CacheManager:
    """Manages caching of search results"""
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.default_ttl = 3600 # 1 hour
        
    async def get_cached_response(self, request_hash: str) -> Optional[GatewayResponse]:
        """Retrieve cached response if available"""
        try:
            cached = await self.redis.get(f"search_cache:{request_hash}")
            if cached:
                return GatewayResponse.parse_raw(cached)
        except Exception as e:
            logger.warning(f"Cache retrieval error: {e}")
        return None
        
    async def cache_response(self, request_hash: str, response: GatewayResponse, ttl: int = None):
        """Cache a search response"""
        try:
            ttl = ttl or self.default_ttl
            await self.redis.setex(
                f"search_cache:{request_hash}", 
                ttl, 
                response.json()
            )
        except Exception as e:
            logger.warning(f"Cache storage error: {e}")

class QueryUnderstandingEngine:
    """Analyzes and extracts meaning from user queries"""
    
    def __init__(self):
        # In a real implementation, use NER from spaCy/NLTK/etc.
        pass
    
    def analyze_query(self, query: str) -> Dict[str, Any]:
        """Analyze query to identify key entities, intent and context"""
        words = query.lower().split()
        temporal_indicators = ["today", "yesterday", "current", "latest", "recent", "2023", "2024", "2025"]
        time_sensitive = any(word in words for word in temporal_indicators)
        question_words = ["what", "who", "when", "where", "why", "how"]
        is_question = any(query.lower().startswith(word) for word in question_words) or "?" in query
        
        return {
            "intent": "question" if is_question else "search",
            "time_sensitive": time_sensitive,
            "query_length": len(words),
            "original_query": query
        }

class ContentFormatter:
    """Formats search responses based on requested format"""
    
    def format_response(self, response: GatewayResponse, format_type: ResponseFormat) -> str:
        """Format the search response according to the specified format"""
        if format_type == ResponseFormat.MARKDOWN:
            sources_md = "\n\n### Sources\n\n"
            for idx, source in enumerate(response.sources):
                sources_md += f"{idx+1}. [{source.title}]({source.url}) - {source.source}\n"
            return f"## Search Results\n\n{response.answer}\n{sources_md}"
        elif format_type == ResponseFormat.CONCISE:
            return response.answer.split("\n\n")[0]
        elif format_type == ResponseFormat.DETAILED:
            detailed = f"{response.answer}\n\nDetailed Sources:\n\n"
            for idx, source in enumerate(response.sources):
                detailed += f"[{idx+1}] {source.title}\n"
                detailed += f"    URL: {source.url}\n"
                detailed += f"    Source: {source.source}\n"
                detailed += f"    Description: {source.description[:150]}...\n\n"
            detailed += f"\nQuery executed at {response.query_time} in {response.execution_time:.2f} seconds."
            return detailed
        return response.answer # Default to standard

class CircuitBreaker:
    """Implements circuit breaker pattern for external service calls"""
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.failure_threshold = 5
        self.reset_timeout = 30  # seconds
        
    async def is_open(self, service: str) -> bool:
        """Check if circuit is open (service considered down)"""
        failures = await self.redis.get(f"circuit:{service}:failures")
        if failures and int(failures) >= self.failure_threshold:
            last_failure = await self.redis.get(f"circuit:{service}:last_failure")
            if not last_failure or (time.time() - float(last_failure)) > self.reset_timeout:
                return False # Half-open state
            return True
        return False
        
    async def record_failure(self, service: str):
        """Record a failure for the service"""
        await self.redis.incr(f"circuit:{service}:failures")
        await self.redis.set(f"circuit:{service}:last_failure", time.time())
        await self.redis.expire(f"circuit:{service}:failures", self.reset_timeout * 2)
        
    async def record_success(self, service: str):
        """Record a successful call - reset failure counter"""
        await self.redis.delete(f"circuit:{service}:failures")
        await self.redis.delete(f"circuit:{service}:last_failure")