# Workflow Engine (port 8001)

> **Status**: ✅ Working · **Dependencies**: All internal services (dispatches to them)

## Purpose
DAG-based workflow executor. Parses `.workflow.yml` manifests, resolves dependencies via topological sort, dispatches steps to internal services via HTTP, and emits progress events to the event bus.

## Execution Flow
1. Load manifest → parse into `WorkflowManifest`
2. Build DAG → topological sort, cycle detection (networkx)
3. For each step in order:
   - Resolve variable references (`$params.x`, `$steps.prev.output`)
   - Dispatch to the appropriate service via HTTP
   - Emit `step.started` / `step.completed` / `step.failed` events
   - Pass outputs to downstream steps

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | `{"status":"ok","workflows":N}` |
| POST | `/execute` | Execute a workflow manifest |
| GET | `/workflows` | List available workflow manifests |
| GET | `/workflows/{id}/status` | Current execution status |

## Variable Resolution
```
$params.topic           → workflow-level parameter
$steps.research.output  → output from "research" step
$input                  → raw workflow input
```

## Step Dispatch Table
| Agent | Task | Target |
|---|---|---|
| researcher | search | deepsearch:8001 |
| crawler | extract | crawler:8000 |
| writer | generate | blog_generator:8006 |
| auditor | score | geo_audit:8011 |
| bridge | research | knowledge_bridge:8010 |

## E2E Test: `seo_content_loop`
```bash
# Full 5-step pipeline (~76s)
curl -s -X POST http://localhost:8001/execute \
  -H "Content-Type: application/json" \
  -d '{
    "workflow": "seo_content_loop",
    "params": {"topic": "Rust async patterns", "target_audience": "systems programmers"}
  }' | python3 -m json.tool
```

Steps: research → extract → generate → audit → refine (loop until score ≥ threshold).

## Docker
```bash
make up core/workflow_engine
```
