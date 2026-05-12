"""
Circuit Breaker - Prevents cascading failures by temporarily disabling failing providers
"""
import asyncio
import time
import logging
from typing import Callable, Any, Type, Optional
from enum import Enum

logger = logging.getLogger(__name__)

class CircuitState(Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failure mode - requests blocked
    HALF_OPEN = "half_open"  # Testing mode - limited requests allowed

class CircuitBreaker:
    """Circuit breaker implementation for provider reliability"""
    
    def __init__(self,
                 failure_threshold: int = 5,
                 recovery_timeout: float = 60,
                 expected_exception: Type[Exception] = Exception,
                 half_open_max_calls: int = 3):
        """
        Initialize circuit breaker
        
        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before attempting recovery
            expected_exception: Exception type that triggers circuit breaker
            half_open_max_calls: Max calls allowed in half-open state
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        self.half_open_max_calls = half_open_max_calls
        
        # State management
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time: Optional[float] = None
        self.last_success_time: Optional[float] = None
        self.half_open_calls = 0
        
        # Metrics
        self.total_calls = 0
        self.total_failures = 0
        self.total_successes = 0
        
    @property
    def is_open(self) -> bool:
        """Check if circuit breaker is open"""
        return self.state == CircuitState.OPEN
        
    @property
    def is_closed(self) -> bool:
        """Check if circuit breaker is closed"""
        return self.state == CircuitState.CLOSED
        
    @property
    def is_half_open(self) -> bool:
        """Check if circuit breaker is half-open"""
        return self.state == CircuitState.HALF_OPEN
        
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset"""
        if self.last_failure_time is None:
            return False
            
        time_since_failure = time.time() - self.last_failure_time
        return time_since_failure >= self.recovery_timeout
        
    def _record_success(self):
        """Record successful call"""
        self.total_calls += 1
        self.total_successes += 1
        self.last_success_time = time.time()
        
        if self.state == CircuitState.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= self.half_open_max_calls:
                self._reset()
        elif self.state == CircuitState.CLOSED:
            # Reset failure count on success
            self.failure_count = 0
            
    def _record_failure(self):
        """Record failed call"""
        self.total_calls += 1
        self.total_failures += 1
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.state == CircuitState.CLOSED:
            if self.failure_count >= self.failure_threshold:
                self._open_circuit()
        elif self.state == CircuitState.HALF_OPEN:
            # Any failure in half-open state opens the circuit
            self._open_circuit()
            
    def _open_circuit(self):
        """Open the circuit breaker"""
        self.state = CircuitState.OPEN
        self.success_count = 0
        self.half_open_calls = 0
        logger.warning(f"Circuit breaker opened after {self.failure_count} failures")
        
    def _reset(self):
        """Reset circuit breaker to closed state"""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.half_open_calls = 0
        logger.info("Circuit breaker reset to closed state")
        
    def _transition_to_half_open(self):
        """Transition to half-open state for testing"""
        self.state = CircuitState.HALF_OPEN
        self.success_count = 0
        self.half_open_calls = 0
        logger.info("Circuit breaker transitioned to half-open state")
        
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function through circuit breaker
        
        Args:
            func: Async function to execute
            *args: Function arguments
            **kwargs: Function keyword arguments
            
        Returns:
            Function result
            
        Raises:
            Exception: If circuit is open or function fails
        """
        # Check circuit state
        if self.state == CircuitState.OPEN:
            if self._should_attempt_reset():
                self._transition_to_half_open()
            else:
                raise Exception("Circuit breaker is OPEN - calls blocked")
                
        elif self.state == CircuitState.HALF_OPEN:
            if self.half_open_calls >= self.half_open_max_calls:
                raise Exception("Circuit breaker is HALF_OPEN - call limit reached")
            self.half_open_calls += 1
            
        # Execute function
        try:
            result = await func(*args, **kwargs)
            self._record_success()
            return result
            
        except self.expected_exception as e:
            self._record_failure()
            raise e
        except Exception as e:
            # Unexpected exceptions don't count as circuit breaker failures
            self.total_calls += 1
            raise e
            
    def get_stats(self) -> dict:
        """Get circuit breaker statistics"""
        return {
            "state": self.state.value,
            "total_calls": self.total_calls,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "failure_count": self.failure_count,
            "success_count": self.success_count,
            "failure_rate": self.total_failures / self.total_calls if self.total_calls > 0 else 0,
            "last_failure_time": self.last_failure_time,
            "last_success_time": self.last_success_time,
            "time_since_last_failure": time.time() - self.last_failure_time if self.last_failure_time else None
        }