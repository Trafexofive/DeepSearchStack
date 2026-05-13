"""
Base HTTP client for Substrate services.

All service clients extend SubstrateClient, which provides:
  - Async HTTP with httpx
  - Automatic retry on 502/503/504
  - JWT auth header injection (when configured)
  - Structured request logging
"""

import logging
from typing import Optional

import httpx

log = logging.getLogger("substrate.client")


class SubstrateClient:
    """Base client — one per service."""

    def __init__(
        self,
        base_url: str = "http://localhost:80",
        api_key: Optional[str] = None,
        timeout: float = 120.0,
        max_retries: int = 2,
    ):
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._max_retries = max_retries
        self._http: Optional[httpx.AsyncClient] = None

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=self._timeout,
                headers=self._auth_headers(),
            )
        return self._http

    def _auth_headers(self) -> dict:
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        """Make an HTTP request with retry on upstream errors."""
        url = f"{self.base_url}{path}"
        last_exc = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = await self.http.request(method, url, **kwargs)
                if resp.status_code < 500:
                    return resp
                if attempt < self._max_retries:
                    log.warning("upstream_error_retry", url=url, status=resp.status_code, attempt=attempt + 1)
            except httpx.ConnectError as e:
                last_exc = e
                if attempt < self._max_retries:
                    log.warning("connect_error_retry", url=url, attempt=attempt + 1)
            except httpx.TimeoutException as e:
                last_exc = e
                if attempt < self._max_retries:
                    log.warning("timeout_retry", url=url, attempt=attempt + 1)
        if last_exc:
            raise last_exc
        return resp

    async def close(self):
        if self._http:
            await self._http.aclose()
            self._http = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.close()


class Substrate:
    """Top-level entry point — holds all service clients."""

    def __init__(
        self,
        base_url: str = "http://localhost:80",
        api_key: Optional[str] = None,
        timeout: float = 120.0,
    ):
        from substrate.blog import BlogClient
        from substrate.workflow import WorkflowClient
        from substrate.ingest import IngestClient
        from substrate.inference import InferenceClient
        from substrate.audit import AuditClient
        from substrate.bridge import BridgeClient
        from substrate.queue import QueueClient
        from substrate.events import EventBusClient

        self.blog = BlogClient(base_url, api_key, timeout)
        self.workflow = WorkflowClient(base_url, api_key, timeout)
        self.ingest = IngestClient(base_url, api_key, timeout)
        self.inference = InferenceClient(base_url, api_key, timeout)
        self.audit = AuditClient(base_url, api_key, timeout)
        self.bridge = BridgeClient(base_url, api_key, timeout)
        self.queue = QueueClient(base_url, api_key, timeout)
        self.events = EventBusClient(base_url, api_key, timeout)

    async def health(self) -> dict:
        """Aggregate health of all services."""
        resp = await self.blog.http.get(f"{self.blog.base_url}/health")
        resp.raise_for_status()
        return resp.json()

    async def close(self):
        for client in [self.blog, self.workflow, self.ingest, self.inference,
                        self.audit, self.bridge, self.queue, self.events]:
            await client.close()
