"""
Substrate Python SDK — language-agnostic HTTP client kit.

Each service has a thin typed client. All clients share a base
http session with retry, auth, and structured logging.

Usage:
    from substrate import Substrate

    sub = Substrate("http://localhost:80")
    blog = sub.blog
    result = await blog.generate("What is WebAssembly?")
    print(result.content)

Requirements:
    pip install httpx pydantic
"""

from substrate.client import SubstrateClient, Substrate
from substrate.blog import BlogClient, GenerateRequest, GenerateResponse
from substrate.workflow import WorkflowClient, TriggerRequest
from substrate.ingest import IngestClient
from substrate.inference import InferenceClient
from substrate.audit import AuditClient
from substrate.bridge import BridgeClient
from substrate.queue import QueueClient
from substrate.events import EventBusClient

__version__ = "0.1.0"
__all__ = [
    "Substrate",
    "SubstrateClient",
    # Service clients
    "BlogClient",
    "WorkflowClient",
    "IngestClient",
    "InferenceClient",
    "AuditClient",
    "BridgeClient",
    "QueueClient",
    "EventBusClient",
    # Models
    "GenerateRequest",
    "GenerateResponse",
    "TriggerRequest",
]
