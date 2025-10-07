"""
Metrics Service - Comprehensive monitoring and analytics for LLM Gateway
"""
import asyncio
import time
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from collections import defaultdict, deque
import statistics

logger = logging.getLogger(__name__)

class MetricsService:
    """Comprehensive metrics collection and analysis"""
    
    def __init__(self, retention_hours: int = 24):
        self.retention_hours = retention_hours
        self.start_time = time.time()
        
        # Request metrics
        self.request_history: deque = deque(maxlen=10000)  # Last 10k requests
        self.provider_metrics: Dict[str, Dict] = defaultdict(lambda: {
            'total_requests': 0,
            'successful_requests': 0,
            'failed_requests': 0,
            'total_time': 0.0,
            'response_times': deque(maxlen=1000),  # Last 1000 response times
            'error_types': defaultdict(int),
            'throughput_history': deque(maxlen=1440),  # 24h of minutes
        })
        
        # Gateway-level metrics
        self.gateway_metrics = {
            'total_requests': 0,
            'total_errors': 0,
            'uptime_start': datetime.utcnow(),
            'cache_hits': 0,
            'cache_misses': 0,
            'rate_limit_hits': 0,
            'circuit_breaker_triggers': 0
        }
        
        # Real-time counters
        self.current_minute_requests = 0
        self.last_minute_reset = time.time()
        
        # Background task for cleanup
        self._cleanup_task: Optional[asyncio.Task] = None
        
    async def start(self):
        """Start metrics service"""
        logger.info("Starting Metrics Service...")
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        
    async def stop(self):
        """Stop metrics service"""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
                
    async def record_request(self,
                           provider: str,
                           response_time: float,
                           success: bool,
                           error_type: Optional[str] = None,
                           tokens_used: Optional[int] = None,
                           model: Optional[str] = None):
        """Record a request with full metrics"""
        
        timestamp = time.time()
        
        # Update gateway metrics
        self.gateway_metrics['total_requests'] += 1
        if not success:
            self.gateway_metrics['total_errors'] += 1
            
        # Update provider metrics
        provider_data = self.provider_metrics[provider]
        provider_data['total_requests'] += 1
        provider_data['total_time'] += response_time
        provider_data['response_times'].append(response_time)
        
        if success:
            provider_data['successful_requests'] += 1
        else:
            provider_data['failed_requests'] += 1
            if error_type:
                provider_data['error_types'][error_type] += 1
                
        # Store detailed request record
        request_record = {
            'timestamp': timestamp,
            'provider': provider,
            'response_time': response_time,
            'success': success,
            'error_type': error_type,
            'tokens_used': tokens_used,
            'model': model
        }
        self.request_history.append(request_record)
        
        # Update throughput tracking
        current_time = time.time()
        if current_time - self.last_minute_reset >= 60:
            # Store requests per minute
            provider_data['throughput_history'].append({
                'timestamp': current_time,
                'requests': self.current_minute_requests
            })
            self.current_minute_requests = 0
            self.last_minute_reset = current_time
            
        self.current_minute_requests += 1
        
    def get_provider_stats(self, provider: str, window_minutes: int = 60) -> Dict[str, Any]:
        """Get comprehensive stats for a provider"""
        if provider not in self.provider_metrics:
            return {}
            
        data = self.provider_metrics[provider]
        cutoff_time = time.time() - (window_minutes * 60)
        
        # Filter recent requests
        recent_requests = [
            r for r in self.request_history 
            if r['provider'] == provider and r['timestamp'] > cutoff_time
        ]
        
        # Calculate metrics
        total_requests = len(recent_requests)
        successful_requests = sum(1 for r in recent_requests if r['success'])
        response_times = [r['response_time'] for r in recent_requests]
        
        stats = {
            'provider': provider,
            'window_minutes': window_minutes,
            'total_requests': total_requests,
            'successful_requests': successful_requests,
            'failed_requests': total_requests - successful_requests,
            'success_rate': successful_requests / total_requests if total_requests > 0 else 0,
            'error_rate': (total_requests - successful_requests) / total_requests if total_requests > 0 else 0,
        }
        
        # Response time statistics
        if response_times:
            stats.update({
                'avg_response_time': statistics.mean(response_times),
                'min_response_time': min(response_times),
                'max_response_time': max(response_times),
                'p50_response_time': statistics.median(response_times),
                'p95_response_time': self._percentile(response_times, 0.95),
                'p99_response_time': self._percentile(response_times, 0.99),
            })
        else:
            stats.update({
                'avg_response_time': 0,
                'min_response_time': 0,
                'max_response_time': 0,
                'p50_response_time': 0,
                'p95_response_time': 0,
                'p99_response_time': 0,
            })
            
        # Throughput
        requests_per_minute = total_requests / window_minutes if window_minutes > 0 else 0
        stats['requests_per_minute'] = requests_per_minute
        stats['requests_per_second'] = requests_per_minute / 60
        
        # Error breakdown
        error_counts = defaultdict(int)
        for req in recent_requests:
            if not req['success'] and req['error_type']:
                error_counts[req['error_type']] += 1
        stats['error_breakdown'] = dict(error_counts)
        
        return stats
        
    def get_gateway_stats(self, window_minutes: int = 60) -> Dict[str, Any]:
        """Get gateway-wide statistics"""
        cutoff_time = time.time() - (window_minutes * 60)
        
        # Filter recent requests
        recent_requests = [
            r for r in self.request_history 
            if r['timestamp'] > cutoff_time
        ]
        
        total_requests = len(recent_requests)
        successful_requests = sum(1 for r in recent_requests if r['success'])
        response_times = [r['response_time'] for r in recent_requests]
        
        # Basic stats
        stats = {
            'uptime_seconds': time.time() - self.start_time,
            'window_minutes': window_minutes,
            'total_requests': total_requests,
            'successful_requests': successful_requests,
            'failed_requests': total_requests - successful_requests,
            'success_rate': successful_requests / total_requests if total_requests > 0 else 0,
            'error_rate': (total_requests - successful_requests) / total_requests if total_requests > 0 else 0,
        }
        
        # Response time stats
        if response_times:
            stats.update({
                'avg_response_time': statistics.mean(response_times),
                'p50_response_time': statistics.median(response_times),
                'p95_response_time': self._percentile(response_times, 0.95),
                'p99_response_time': self._percentile(response_times, 0.99),
            })
        else:
            stats.update({
                'avg_response_time': 0,
                'p50_response_time': 0,
                'p95_response_time': 0,
                'p99_response_time': 0,
            })
            
        # Throughput
        requests_per_minute = total_requests / window_minutes if window_minutes > 0 else 0
        stats['requests_per_minute'] = requests_per_minute
        stats['requests_per_second'] = requests_per_minute / 60
        
        # Provider breakdown
        provider_counts = defaultdict(int)
        for req in recent_requests:
            provider_counts[req['provider']] += 1
        stats['provider_distribution'] = dict(provider_counts)
        
        # Include gateway metrics
        stats.update({
            'cache_hits': self.gateway_metrics['cache_hits'],
            'cache_misses': self.gateway_metrics['cache_misses'],
            'cache_hit_rate': self._safe_divide(
                self.gateway_metrics['cache_hits'],
                self.gateway_metrics['cache_hits'] + self.gateway_metrics['cache_misses']
            ),
            'rate_limit_hits': self.gateway_metrics['rate_limit_hits'],
            'circuit_breaker_triggers': self.gateway_metrics['circuit_breaker_triggers']
        })
        
        return stats
        
    def get_all_provider_stats(self, window_minutes: int = 60) -> Dict[str, Dict[str, Any]]:
        """Get stats for all providers"""
        return {
            provider: self.get_provider_stats(provider, window_minutes)
            for provider in self.provider_metrics.keys()
        }
        
    def record_cache_hit(self):
        """Record cache hit"""
        self.gateway_metrics['cache_hits'] += 1
        
    def record_cache_miss(self):
        """Record cache miss"""
        self.gateway_metrics['cache_misses'] += 1
        
    def record_rate_limit_hit(self):
        """Record rate limit hit"""
        self.gateway_metrics['rate_limit_hits'] += 1
        
    def record_circuit_breaker_trigger(self):
        """Record circuit breaker trigger"""
        self.gateway_metrics['circuit_breaker_triggers'] += 1
        
    async def _cleanup_loop(self):
        """Background task to cleanup old metrics"""
        while True:
            try:
                await asyncio.sleep(3600)  # Run every hour
                await self._cleanup_old_data()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Metrics cleanup error: {e}")
                
    async def _cleanup_old_data(self):
        """Remove old metrics data"""
        cutoff_time = time.time() - (self.retention_hours * 3600)
        
        # Clean request history
        while self.request_history and self.request_history[0]['timestamp'] < cutoff_time:
            self.request_history.popleft()
            
        # Clean provider throughput history
        for provider_data in self.provider_metrics.values():
            throughput = provider_data['throughput_history']
            while throughput and throughput[0]['timestamp'] < cutoff_time:
                throughput.popleft()
                
    def _percentile(self, data: List[float], percentile: float) -> float:
        """Calculate percentile of data"""
        if not data:
            return 0.0
        sorted_data = sorted(data)
        index = int(len(sorted_data) * percentile)
        return sorted_data[min(index, len(sorted_data) - 1)]
        
    def _safe_divide(self, numerator: float, denominator: float) -> float:
        """Safe division avoiding divide by zero"""
        return numerator / denominator if denominator > 0 else 0.0