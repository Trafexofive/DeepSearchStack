"""
Provider Manager - Advanced provider management with load balancing, health monitoring, and circuit breakers
"""
import asyncio
import time
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from collections import defaultdict
import random

from ..provider_base import LLMProvider, CompletionRequest, CompletionResponse
from ..models.requests import RoutingStrategy
from ..models.responses import ProviderStatus
from .circuit_breaker import CircuitBreaker
from .metrics_service import MetricsService

logger = logging.getLogger(__name__)

class ProviderManager:
    """Advanced provider management with intelligent routing and health monitoring"""
    
    def __init__(self, metrics_service: Optional['MetricsService'] = None):
        self.providers: Dict[str, LLMProvider] = {}
        self.provider_stats: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            'requests': 0,
            'errors': 0,
            'total_time': 0.0,
            'last_success': None,
            'last_error': None,
            'error_streak': 0,
            'avg_latency': 0.0,
            'active_requests': 0
        })
        self.circuit_breakers: Dict[str, CircuitBreaker] = {}
        self.metrics_service = metrics_service
        self.startup_time = time.time()
        self.round_robin_index = 0
        
        # Health monitoring
        self._health_check_task = None
        self._health_check_interval = 30  # seconds
        
    async def start(self):
        """Start the provider manager"""
        logger.info("Starting Provider Manager...")
        
        # Initialize circuit breakers for all providers
        for name in self.providers.keys():
            self.circuit_breakers[name] = CircuitBreaker(
                failure_threshold=5,
                recovery_timeout=60,
                expected_exception=Exception
            )
        
        # Start health monitoring
        self._health_check_task = asyncio.create_task(self._health_monitor_loop())
        
    async def stop(self):
        """Stop the provider manager"""
        if self._health_check_task:
            self._health_check_task.cancel()
            try:
                await self._health_check_task
            except asyncio.CancelledError:
                pass
                
    def register_provider(self, name: str, provider: LLMProvider):
        """Register a new provider"""
        self.providers[name] = provider
        self.circuit_breakers[name] = CircuitBreaker(
            failure_threshold=5,
            recovery_timeout=60,
            expected_exception=Exception
        )
        logger.info(f"Registered provider: {name}")
        
    async def get_available_providers(self) -> List[str]:
        """Get list of currently available providers"""
        available = []
        for name, provider in self.providers.items():
            if (await provider.is_available() and 
                not self.circuit_breakers[name].is_open):
                available.append(name)
        return available
        
    async def select_provider(self, 
                            strategy: RoutingStrategy,
                            preferred_provider: Optional[str] = None,
                            exclude: List[str] = None) -> Optional[str]:
        """Smart provider selection based on strategy"""
        
        available = await self.get_available_providers()
        if exclude:
            available = [p for p in available if p not in exclude]
            
        if not available:
            return None
            
        # Use preferred provider if available
        if preferred_provider and preferred_provider in available:
            return preferred_provider
            
        if strategy == RoutingStrategy.RANDOM:
            return random.choice(available)
            
        elif strategy == RoutingStrategy.ROUND_ROBIN:
            self.round_robin_index = (self.round_robin_index + 1) % len(available)
            return available[self.round_robin_index]
            
        elif strategy == RoutingStrategy.LEAST_LATENCY:
            # Select provider with lowest average latency
            best_provider = min(available, key=lambda p: self.provider_stats[p]['avg_latency'])
            return best_provider
            
        elif strategy == RoutingStrategy.LOWEST_COST:
            # Implement cost-based routing (placeholder for now)
            cost_order = ['ollama', 'groq', 'gemini']  # Approximate cost order
            for provider in cost_order:
                if provider in available:
                    return provider
            return available[0]
            
        elif strategy == RoutingStrategy.HIGHEST_QUALITY:
            # Implement quality-based routing (placeholder for now)
            quality_order = ['gemini', 'groq', 'ollama']  # Approximate quality order
            for provider in quality_order:
                if provider in available:
                    return provider
            return available[0]
            
        elif strategy == RoutingStrategy.FAILOVER:
            # Use primary provider or failover
            primary_order = ['gemini', 'groq', 'ollama']
            for provider in primary_order:
                if provider in available:
                    return provider
            return available[0] if available else None
            
        return random.choice(available)
        
    async def execute_completion(self,
                               provider_name: str,
                               request: CompletionRequest,
                               fallback: bool = True) -> CompletionResponse:
        """Execute completion with error handling and fallback"""
        
        start_time = time.time()
        self.provider_stats[provider_name]['active_requests'] += 1
        
        try:
            # Check circuit breaker
            circuit_breaker = self.circuit_breakers[provider_name]
            if circuit_breaker.is_open:
                raise Exception(f"Circuit breaker open for provider {provider_name}")
                
            # Execute through circuit breaker
            async def _execute():
                provider = self.providers[provider_name]
                return await provider.get_completion(request)
                
            response = await circuit_breaker.call(_execute)
            
            # Update success metrics
            elapsed = time.time() - start_time
            stats = self.provider_stats[provider_name]
            stats['requests'] += 1
            stats['total_time'] += elapsed
            stats['last_success'] = datetime.utcnow()
            stats['error_streak'] = 0
            stats['avg_latency'] = stats['total_time'] / stats['requests']
            
            if self.metrics_service:
                await self.metrics_service.record_request(provider_name, elapsed, True)
                
            return response
            
        except Exception as e:
            # Update error metrics
            elapsed = time.time() - start_time
            stats = self.provider_stats[provider_name]
            stats['errors'] += 1
            stats['last_error'] = str(e)
            stats['error_streak'] += 1
            
            if self.metrics_service:
                await self.metrics_service.record_request(provider_name, elapsed, False)
                
            logger.error(f"Provider {provider_name} failed: {e}")
            
            # Try fallback if enabled
            if fallback and stats['error_streak'] < 3:
                available = await self.get_available_providers()
                fallback_providers = [p for p in available if p != provider_name]
                
                if fallback_providers:
                    logger.info(f"Attempting fallback to {fallback_providers[0]}")
                    return await self.execute_completion(fallback_providers[0], request, False)
                    
            raise e
            
        finally:
            self.provider_stats[provider_name]['active_requests'] -= 1
            
    async def get_provider_status(self, provider_name: str) -> ProviderStatus:
        """Get detailed status for a provider"""
        if provider_name not in self.providers:
            raise ValueError(f"Provider {provider_name} not found")
            
        provider = self.providers[provider_name]
        stats = self.provider_stats[provider_name]
        circuit_breaker = self.circuit_breakers[provider_name]
        
        # Calculate error rate
        total_requests = stats['requests'] + stats['errors']
        error_rate = stats['errors'] / total_requests if total_requests > 0 else 0.0
        
        return ProviderStatus(
            available=await provider.is_available(),
            healthy=stats['error_streak'] < 3,
            latency_ms=stats['avg_latency'] * 1000,
            error_rate=error_rate,
            last_success=stats['last_success'],
            last_error=stats['last_error'],
            circuit_breaker_open=circuit_breaker.is_open,
            active_requests=stats['active_requests']
        )
        
    async def _health_monitor_loop(self):
        """Background task to monitor provider health"""
        while True:
            try:
                await asyncio.sleep(self._health_check_interval)
                
                for name, provider in self.providers.items():
                    try:
                        # Simple health check
                        available = await provider.is_available()
                        if not available:
                            logger.warning(f"Provider {name} reported unavailable")
                            
                    except Exception as e:
                        logger.error(f"Health check failed for {name}: {e}")
                        
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health monitor error: {e}")
                await asyncio.sleep(5)  # Brief pause before retry