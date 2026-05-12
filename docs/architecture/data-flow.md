# Data Flow — Blog Generation (Working)

```mermaid
sequenceDiagram
    participant C as Client (curl/pi)
    participant BG as blog_generator :8006
    participant IG as inference_gateway :8005
    participant DS as DeepSeek API
    participant DB as tracker.db (SQLite)

    C->>BG: POST /generate {topic, style}
    BG->>BG: Assign request ID (rid)
    BG->>BG: Log: "Generate request: topic=X"
    BG->>IG: POST /v1/chat/completions {model, messages}
    IG->>DS: POST api.deepseek.com/v1/chat/completions
    DS-->>IG: {content, usage: {tokens}}
    IG-->>BG: {content, usage, raw_response}
    BG->>DB: INSERT generation record (tokens, cost, duration)
    BG->>BG: Log: "Blog generated: id=Y tokens=Z cost=$W"
    BG-->>C: {id, topic, model, content, usage, cost_usd, duration_ms}
```

## Target Data Flow — Full Workflow (Phase 2+)

```mermaid
sequenceDiagram
    participant C as Client
    participant AG as api_gateway :8000
    participant WE as workflow_engine :8001
    participant IG as inference_gateway :8005
    participant BG as blog_generator :8006
    participant EB as event_bus :8003

    C->>AG: POST /api/workflows/trigger {workflow: "seo_content_loop"}
    AG->>WE: Forward trigger
    WE->>WE: Parse seo_content_loop.workflow.yml → DAG
    WE->>IG: Step 1: web research
    IG-->>WE: research results
    WE->>BG: Step 2: generate blog post
    BG->>IG: Chat completion
    IG-->>BG: content
    BG-->>WE: generated post
    WE->>EB: emit "workflow.step.complete"
    EB-->>C: WebSocket push (real-time update)
    WE->>WE: Step 3: review → publish
    WE->>EB: emit "workflow.complete"
    EB-->>C: WebSocket push (done)
```

## Provider Resolution Flow

```mermaid
flowchart TD
    A[POST /v1/chat/completions] --> B{model starts with<br>'virtual/'?}
    B -->|yes| C[Cascade through<br>fallback chain]
    B -->|no| D{x-provider header set?}
    D -->|yes| E[Route to specified provider]
    D -->|no| F[Look up model in catalog]
    F --> G{Found?}
    G -->|yes| H[Route to owning provider]
    G -->|no| I[Route to first available provider]
    
    C --> J{Provider 1 available?}
    J -->|yes| K[Try provider 1]
    J -->|no| L{Provider 2 available?}
    K --> M{Success?}
    M -->|yes| N[Return response]
    M -->|no (429/5xx)| L
    L -->|yes| O[Try provider 2]
    L -->|no| P[Return 429 - all exhausted]
    O --> Q{Success?}
    Q -->|yes| N
    Q -->|no| P
```
