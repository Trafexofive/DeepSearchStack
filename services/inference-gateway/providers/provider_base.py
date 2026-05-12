"""Base provider interface with rate limiting and retry logic."""

import abc
import time
import asyncio
import httpx
from typing import List, Dict, Any, AsyncGenerator
import tenacity

from models.requests import ChatCompletionRequest
from models.responses import ChatCompletionResponse


class AsyncRateLimiter:
    """Token-bucket style rate limiter for API calls."""

    def __init__(self, max_requests: int = 40, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.timestamps: List[float] = []
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            now = time.time()
            cutoff = now - self.window_seconds
            self.timestamps = [t for t in self.timestamps if t > cutoff]

            if len(self.timestamps) >= self.max_requests:
                sleep_time = self.timestamps[0] + self.window_seconds - now + 0.01
                if sleep_time > 0:
                    await asyncio.sleep(sleep_time)
                now = time.time()
                cutoff = now - self.window_seconds
                self.timestamps = [t for t in self.timestamps if t > cutoff]

            self.timestamps.append(now)


def is_retryable_error(e: Exception) -> bool:
    """Determine if an error is worth retrying (429/5xx/timeout)."""
    if isinstance(e, httpx.HTTPStatusError):
        return e.response.status_code in {429, 500, 502, 503, 504}
    if isinstance(e, httpx.RequestError):
        return True
    return False


class BaseProvider(abc.ABC):
    """Abstract base for LLM providers with retry and rate limiting."""

    def __init__(self, api_key: str, base_url: str, max_rpm: int = 40, timeout: float = 300.0):
        self.api_key = api_key
        self.base_url = base_url
        self.rate_limiter = AsyncRateLimiter(max_requests=max_rpm, window_seconds=60)
        self.timeout = timeout
        self._client = httpx.AsyncClient(timeout=self.timeout)

    @property
    @abc.abstractmethod
    def default_headers(self) -> Dict[str, str]:
        pass

    async def close(self):
        await self._client.aclose()

    @tenacity.retry(
        wait=tenacity.wait_exponential(multiplier=1, min=2, max=30),
        stop=tenacity.stop_after_attempt(20),
        retry=tenacity.retry_if_exception(is_retryable_error),
        reraise=True,
    )
    async def _post(self, payload: Dict[str, Any]) -> httpx.Response:
        await self.rate_limiter.acquire()
        response = await self._client.post(
            self.base_url, headers=self.default_headers, json=payload
        )
        response.raise_for_status()
        return response

    @abc.abstractmethod
    async def chat(self, request: ChatCompletionRequest) -> ChatCompletionResponse:
        pass

    @abc.abstractmethod
    async def chat_stream(self, request: ChatCompletionRequest) -> AsyncGenerator[str, None]:
        pass
