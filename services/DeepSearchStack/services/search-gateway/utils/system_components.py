import time
import redis.asyncio as redis
import logging
from typing import Dict, Any, Optional, List

# MODIFIED: Corrected relative import path
from search_gateway.common.models import SearchProvider

logger = logging.getLogger(__name__)

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

class CircuitBreaker:
    """Implements circuit breaker pattern for external service calls"""
    
    def __init__(self, redis_client: redis.Redis):
        self.redis = redis_client
        self.failure_threshold = 3 # Stricter threshold
        self.reset_timeout = 60  # 1 minute
        
    async def is_open(self, service: str) -> bool:
        """Check if circuit is open (service considered down)"""
        try:
            failures = await self.redis.get(f"circuit:{service}:failures")
            if failures and int(failures) >= self.failure_threshold:
                return True
        except Exception as e:
            logger.warning(f"Redis error checking circuit breaker for {service}: {e}")
        return False
        
    async def record_failure(self, service: str):
        """Record a failure for the service"""
        try:
            await self.redis.incr(f"circuit:{service}:failures")
            await self.redis.expire(f"circuit:{service}:failures", self.reset_timeout)
        except Exception as e:
            logger.warning(f"Redis error recording failure for {service}: {e}")
        
    async def record_success(self, service: str):
        """Record a successful call - reset failure counter"""
        try:
            await self.redis.delete(f"circuit:{service}:failures")
        except Exception as e:
            logger.warning(f"Redis error recording success for {service}: {e}")
