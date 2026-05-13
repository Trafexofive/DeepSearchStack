# Service SDKs & Language-Agnostic Architecture

> Status: v0.1.0 · Dependencies: api_gateway

## Philosophy

Substrate services are **language-agnostic microservices**. Every service communicates
via HTTP/JSON at the boundary. Internal implementation language is an implementation
detail — Python, Rust, Go, C++, TypeScript are all first-class.

This means:
- **No shared code between services.** Each service is independently buildable.
- **No RPC framework.** Plain HTTP + JSON. An nginx edge gateway routes everything.
- **No shared type definitions.** Each service owns its schema. SDKs wrap this.
- **SDKs are thin HTTP wrappers.** They handle serialization, retry, auth — nothing more.

## SDK Directory

```
sdk/
├── python/substrate/   # Python async SDK (httpx + pydantic)
│   ├── __init__.py
│   ├── client.py       # Base client: retry, auth, logging
│   ├── blog.py         # BlogGeneratorClient
│   ├── workflow.py     # WorkflowClient
│   ├── ingest.py       # IngestClient
│   ├── inference.py    # InferenceClient
│   ├── audit.py        # AuditClient
│   ├── bridge.py       # BridgeClient
│   ├── queue.py        # QueueClient
│   └── events.py       # EventBusClient
├── cpp/substrate.hpp   # C++17 header-only (libcurl)
├── go/                 # Go SDK (planned)
├── rust/               # Rust SDK (planned)
└── ts/                 # TypeScript SDK (planned)
```

## Python SDK

```python
from substrate import Substrate

sub = Substrate("http://localhost:80")

# Health
health = await sub.health()
print(health["status"])  # "ok"

# Blog generation
result = await sub.blog.generate("What is WebAssembly?")
print(f"Generated {result.id}: {len(result.content)} chars, ${result.cost_usd:.4f}")

# Workflow execution (blocks until done, 60-120s)
wf = await sub.workflow.seo_content_loop(
    topic="Rust async executors",
    keyword="rust async runtime",
    tone="technical",
)
for step in wf.steps:
    print(f"  {step.step_id}: {step.status} ({step.duration_ms}ms)")

# Feed ingestion
stats = await sub.ingest.stats()
print(f"Ingested {stats['entries_detected']} entries, {stats['posts_generated']} posts")
```

## C++ SDK

```cpp
#include "substrate.hpp"
using namespace substrate;

int main() {
    BlogClient blog("http://localhost:80");
    auto result = blog.generate("What is WebAssembly?");
    std::cout << result.content << "\n";

    WorkflowClient wf("http://localhost:80");
    auto wf_result = wf.seo_content_loop("Rust async executors");
    std::cout << wf_result << "\n";
}
```

Build: `g++ -std=c++17 -lcurl your_app.cpp`

## Adding a New SDK Language

1. Map the HTTP routes from `docs/architecture/port-map.md`
2. Wrap each service endpoint in a typed method
3. Handle auth (Bearer token in Authorization header)
4. Add retry on 502/503/504
5. Add to this doc

## Service Communication Rules

| Rule | Detail |
|---|---|
| HTTP only | No gRPC, no message queues at the boundary. Internal event_bus uses Redis. |
| JSON payloads | Pydantic/FastAPI auto-validates. Clients send JSON. |
| Health endpoint | Every service exposes `GET /health` |
| Docker DNS | Services resolve each other by name: `http://blog_generator:8006` |
| Port registry | See `docs/architecture/port-map.md` |
| Timeouts | 120s default. Long-running workflows return async IDs (planned). |
| Auth | JWT Bearer tokens (planned). Service-to-service via API keys (planned). |
