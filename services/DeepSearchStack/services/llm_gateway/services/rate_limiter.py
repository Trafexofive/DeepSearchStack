"""
Rate Limiter - Token bucket and sliding window rate limiting
"""
import time
import asyncio
import logging
from typing import Dict, Optional, Tuple
from collections import defaultdict, deque

logger = logging.getLogger(__name__)

class TokenBucket:
    """Token bucket for rate limiting"""
    
    def __init__(self, capacity: int, refill_rate: float):
        """
        Initialize token bucket
        
        Args:
            capacity: Maximum tokens in bucket
            refill_rate: Tokens added per second
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.tokens = capacity
        self.last_refill = time.time()
        
    def consume(self, tokens: int = 1) -> bool:
        """
        Try to consume tokens from bucket
        
        Args:
            tokens: Number of tokens to consume
            
        Returns:
            True if tokens were consumed, False if insufficient tokens
        """
        self._refill()
        
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False
        
    def _refill(self):
        """Refill tokens based on elapsed time"""
        now = time.time()
        elapsed = now - self.last_refill
        
        tokens_to_add = elapsed * self.refill_rate
        self.tokens = min(self.capacity, self.tokens + tokens_to_add)
        self.last_refill = now

class SlidingWindow:
    """Sliding window rate limiter"""
    
    def __init__(self, window_size: int, max_requests: int):
        """
        Initialize sliding window
        
        Args:
            window_size: Window size in seconds
            max_requests: Maximum requests per window
        """
        self.window_size = window_size
        self.max_requests = max_requests
        self.requests: deque = deque()
        
    def is_allowed(self) -> bool:
        """Check if request is allowed"""
        now = time.time()
        
        # Remove old requests outside window
        cutoff = now - self.window_size
        while self.requests and self.requests[0] <= cutoff:
            self.requests.popleft()
            
        # Check if under limit
        if len(self.requests) < self.max_requests:
            self.requests.append(now)
            return True
        
        return False

class RateLimiter:
    """Advanced rate limiter with multiple strategies"""
    
    def __init__(self):
        # Per-user rate limits (token buckets)
        self.user_buckets: Dict[str, TokenBucket] = {}
        
        # Global rate limits (sliding windows)
        self.global_windows: Dict[str, SlidingWindow] = {
            'requests_per_minute': SlidingWindow(60, 1000),  # 1000 req/min globally
            'requests_per_second': SlidingWindow(1, 50),     # 50 req/sec globally
        }
        
        # Per-provider rate limits
        self.provider_windows: Dict[str, Dict[str, SlidingWindow]] = defaultdict(lambda: {
            'requests_per_minute': SlidingWindow(60, 200),   # 200 req/min per provider
            'requests_per_second': SlidingWindow(1, 10),     # 10 req/sec per provider
        })
        
        # Configuration
        self.user_config = {
            'default': {'capacity': 100, 'refill_rate': 1.0},    # 1 token/sec, 100 max
            'premium': {'capacity': 500, 'refill_rate': 5.0},    # 5 tokens/sec, 500 max
            'enterprise': {'capacity': 1000, 'refill_rate': 10.0} # 10 tokens/sec, 1000 max
        }
        
        # Cleanup task
        self._cleanup_task: Optional[asyncio.Task] = None
        
    async def start(self):
        """Start rate limiter service"""
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        
    async def stop(self):
        """Stop rate limiter service"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            
    async def is_allowed(self, 
                        user_id: str,
                        provider: Optional[str] = None,
                        user_tier: str = 'default') -> bool:
        """
        Check if request is allowed for user
        
        Args:
            user_id: User identifier
            provider: Provider name (optional)
            user_tier: User tier for rate limits
            
        Returns:
            True if allowed, False if rate limited
        """
        
        # Check global limits first
        for limit_name, window in self.global_windows.items():
            if not window.is_allowed():
                logger.warning(f"Global rate limit hit: {limit_name}")
                return False
                
        # Check provider limits
        if provider:
            provider_limits = self.provider_windows[provider]
            for limit_name, window in provider_limits.items():
                if not window.is_allowed():
                    logger.warning(f"Provider {provider} rate limit hit: {limit_name}")
                    return False
                    
        # Check user-specific limits
        user_bucket = self._get_user_bucket(user_id, user_tier)
        if not user_bucket.consume():
            logger.warning(f"User {user_id} rate limit hit")
            return False
            
        return True
        
    def _get_user_bucket(self, user_id: str, user_tier: str) -> TokenBucket:
        """Get or create token bucket for user"""
        if user_id not in self.user_buckets:
            config = self.user_config.get(user_tier, self.user_config['default'])
            self.user_buckets[user_id] = TokenBucket(
                capacity=config['capacity'],
                refill_rate=config['refill_rate']
            )
        return self.user_buckets[user_id]
        
    async def get_rate_limit_status(self, user_id: str, user_tier: str = 'default') -> Dict:
        """Get rate limit status for user"""
        bucket = self._get_user_bucket(user_id, user_tier)
        bucket._refill()  # Ensure current token count
        
        return {
            'user_id': user_id,
            'user_tier': user_tier,
            'tokens_remaining': int(bucket.tokens),
            'tokens_capacity': bucket.capacity,
            'refill_rate_per_second': bucket.refill_rate,
            'estimated_refill_time': (bucket.capacity - bucket.tokens) / bucket.refill_rate if bucket.refill_rate > 0 else 0
        }
        
    async def get_global_status(self) -> Dict:
        """Get global rate limiter status"""
        status = {
            'active_users': len(self.user_buckets),
            'global_limits': {},
            'provider_limits': {}
        }
        
        # Global limits info
        for name, window in self.global_windows.items():
            status['global_limits'][name] = {
                'window_size': window.window_size,
                'max_requests': window.max_requests,
                'current_requests': len(window.requests)
            }
            
        # Provider limits info  
        for provider, limits in self.provider_windows.items():
            status['provider_limits'][provider] = {}
            for name, window in limits.items():
                status['provider_limits'][provider][name] = {
                    'window_size': window.window_size,
                    'max_requests': window.max_requests,
                    'current_requests': len(window.requests)
                }
                
        return status
        
    def update_user_tier(self, user_id: str, new_tier: str):
        """Update user's rate limit tier"""
        if new_tier not in self.user_config:
            raise ValueError(f"Unknown user tier: {new_tier}")
            
        # Remove existing bucket to force recreation with new limits
        if user_id in self.user_buckets:
            del self.user_buckets[user_id]
            
        logger.info(f"Updated user {user_id} to tier {new_tier}")
        
    def add_provider_limits(self, provider: str, requests_per_minute: int, requests_per_second: int):
        """Add custom rate limits for a provider"""
        self.provider_windows[provider] = {
            'requests_per_minute': SlidingWindow(60, requests_per_minute),
            'requests_per_second': SlidingWindow(1, requests_per_second)
        }
        logger.info(f"Added custom rate limits for provider {provider}")
        
    async def _cleanup_loop(self):
        """Background cleanup task"""
        while True:
            try:
                await asyncio.sleep(300)  # Run every 5 minutes
                await self._cleanup_old_buckets()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Rate limiter cleanup error: {e}")
                
    async def _cleanup_old_buckets(self):
        """Remove unused user buckets"""
        cutoff_time = time.time() - 3600  # 1 hour
        
        inactive_users = []
        for user_id, bucket in self.user_buckets.items():
            # If bucket hasn't been refilled recently, user is inactive
            if bucket.last_refill < cutoff_time and bucket.tokens >= bucket.capacity * 0.9:
                inactive_users.append(user_id)
                
        for user_id in inactive_users:
            del self.user_buckets[user_id]
            
        if inactive_users:
            logger.info(f"Cleaned up {len(inactive_users)} inactive user rate limit buckets")