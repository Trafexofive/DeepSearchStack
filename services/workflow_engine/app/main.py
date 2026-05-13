"""
workflow_engine — Substrate DAG Executor

Parses .workflow.yml manifests, resolves dependencies, executes steps
via HTTP calls to internal services, and emits progress events.

Execution flow:
  1. Load manifest → parse into WorkflowManifest
  2. Build DAG → topological sort, cycle detection
  3. For each step in order:
     a. Resolve variable references ($params.x, $steps.prev.output)
     b. Dispatch to the appropriate service via HTTP
     c. Emit step.started / step.completed / step.failed events
     d. Pass outputs to downstream steps
"""

import os
import json
import yaml
import logging
import asyncio
import time
from pathlib import Path
from typing import Optional, Any
from collections import deque

import httpx
import networkx as nx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("workflow_engine")

# ─── Service Endpoints ───────────────────────────────────────────────────────

SERVICES = {
    "blog_generator":       os.getenv("BLOG_GENERATOR_URL",       "http://blog_generator:8006"),
    "knowledge_bridge":     os.getenv("KNOWLEDGE_BRIDGE_URL",     "http://knowledge_bridge:8010"),
    "geo_audit":            os.getenv("GEO_AUDIT_URL",            "http://geo_audit:8011"),
    "event_bus":            os.getenv("EVENT_BUS_URL",             "http://event_bus:8003"),
    "crawler":              os.getenv("CRAWLER_URL",              "http://crawler:8000"),
    "sub_mq":               os.getenv("SUB_MQ_URL",               "http://sub_mq:8012"),
}

# ─── Step dispatch table — maps agent+task to service endpoint ───────────────

STEP_DISPATCH = {
    # SEO Content Loop
    ("scribe", "research_topic"):   ("knowledge_bridge", "POST", "/bridge/research"),
    ("scribe", "generate_outline"): ("blog_generator",   "POST", "/generate"),
    ("scribe", "write_mdx"):        ("blog_generator",   "POST", "/generate"),
    ("scribe", "audit_quality"):    ("geo_audit",        "POST", "/audit/content"),
    ("scribe", "publish_to_vault"): ("_internal",        "pass", ""),
    # Recon Sweep
    ("recon", "load_target_list"):  ("_internal",        "pass", ""),
    ("recon", "crawl"):             ("crawler",          "POST", "/crawl"),
    ("recon", "extract"):           ("_internal",        "pass", ""),
    ("recon", "diff"):              ("_internal",        "pass", ""),
    ("recon", "store"):             ("_internal",        "pass", ""),
}

EVENT_BUS_URL = SERVICES["event_bus"] + "/api/publish"


# ─── Data Models ─────────────────────────────────────────────────────────────

class WorkflowStep(BaseModel):
    id: str
    agent: str
    task: str
    inputs: dict = {}
    tools: list[str] = []
    relics: list[str] = []
    depends_on: list[str] = []
    description: str = ""
    output: Optional[str] = None
    retry: int = 0


class WorkflowManifest(BaseModel):
    name: str
    version: str
    description: str = ""
    trigger: dict = {}
    steps: list[WorkflowStep]
    on_success: dict = {}
    on_failure: dict = {}


class TriggerRequest(BaseModel):
    workflow: str
    params: dict = {}


class StepResult(BaseModel):
    step_id: str
    status: str  # started | completed | failed
    output: Any = None
    error: str = ""
    duration_ms: int = 0


# ─── Variable Resolver ───────────────────────────────────────────────────────

def resolve_vars(template: Any, params: dict, step_outputs: dict[str, Any]) -> Any:
    """Recursively resolve $params.x and $steps.id.output references."""
    if isinstance(template, str):
        # Handle simple $params.x references
        if template.startswith("$params."):
            key = template[len("$params."):]
            return params.get(key, template)
        if template.startswith("$steps."):
            # $steps.research.output → step_outputs["research"]
            rest = template[len("$steps."):]
            parts = rest.split(".", 1)
            step_id = parts[0]
            val = step_outputs.get(step_id)
            if len(parts) > 1 and isinstance(val, dict):
                return val.get(parts[1], template)
            return val if val is not None else template
        # Handle nested $params.x within longer strings
        if "$params." in template:
            for key, val in params.items():
                template = template.replace(f"$params.{key}", str(val))
        if "$steps." in template:
            for sid, val in step_outputs.items():
                if isinstance(val, dict):
                    for k, v in val.items():
                        template = template.replace(f"$steps.{sid}.{k}", str(v))
                template = template.replace(f"$steps.{sid}.output", str(val) if not isinstance(val, dict) else json.dumps(val))
        return template
    elif isinstance(template, dict):
        return {k: resolve_vars(v, params, step_outputs) for k, v in template.items()}
    elif isinstance(template, list):
        return [resolve_vars(v, params, step_outputs) for v in template]
    return template


# ─── Event Emitter ───────────────────────────────────────────────────────────

async def emit_event(channel: str, data: dict, source: str = "workflow_engine"):
    """Fire-and-forget event publish to event_bus."""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            await client.post(EVENT_BUS_URL, json={
                "channel": channel,
                "data": data,
                "source": source,
            })
    except Exception:
        logger.debug(f"Event emit failed (non-blocking): {channel}")


# ─── Workflow Engine Core ────────────────────────────────────────────────────

class WorkflowEngine:
    def __init__(self, manifests_dir: str = "manifests/workflows"):
        self.manifests_dir = Path(manifests_dir)

    def load_manifest(self, name: str) -> Optional[WorkflowManifest]:
        path = self.manifests_dir / f"{name}.workflow.yml"
        if not path.exists():
            path = self.manifests_dir / f"{name}.yml"
        if not path.exists():
            logger.error(f"Workflow manifest not found: {name}")
            return None
        with open(path) as f:
            data = yaml.safe_load(f)
        manifest = WorkflowManifest(**data)
        logger.info(f"Loaded workflow: {manifest.name} v{manifest.version}")
        return manifest

    def build_dag(self, manifest: WorkflowManifest) -> nx.DiGraph:
        """Build a NetworkX DAG from workflow steps. Raises on cycles."""
        G = nx.DiGraph()
        step_ids = {s.id for s in manifest.steps}
        for step in manifest.steps:
            G.add_node(step.id, step=step)
            for dep in step.depends_on:
                if dep not in step_ids:
                    raise ValueError(f"Step '{step.id}' depends on unknown step '{dep}'")
                G.add_edge(dep, step.id)
        if not nx.is_directed_acyclic_graph(G):
            cycles = list(nx.simple_cycles(G))
            raise ValueError(f"Workflow contains cycles: {cycles}")
        return G

    async def execute(self, manifest: WorkflowManifest, params: dict) -> dict:
        """Execute a workflow DAG step by step, topologically sorted."""
        G = self.build_dag(manifest)
        order = list(nx.topological_sort(G))

        logger.info(f"Executing workflow '{manifest.name}' — {len(order)} steps: {' → '.join(order)}")
        await emit_event("workflow.started", {
            "workflow": manifest.name,
            "steps": order,
            "params": params,
        })

        step_outputs: dict[str, Any] = {}
        step_results: list[StepResult] = []

        for step_id in order:
            step = G.nodes[step_id]["step"]
            t0 = time.monotonic()

            await emit_event("workflow.step.started", {
                "workflow": manifest.name,
                "step": step_id,
                "agent": step.agent,
                "task": step.task,
            })

            try:
                result = await self._dispatch_step(step, params, step_outputs)
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                step_outputs[step_id] = result

                sr = StepResult(step_id=step_id, status="completed", output=result, duration_ms=elapsed_ms)
                step_results.append(sr)
                logger.info(f"  ✓ {step_id} ({step.agent}/{step.task}) — {elapsed_ms}ms")

                await emit_event("workflow.step.completed", {
                    "workflow": manifest.name,
                    "step": step_id,
                    "agent": step.agent,
                    "task": step.task,
                    "duration_ms": elapsed_ms,
                })

            except Exception as e:
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                error_msg = str(e)
                sr = StepResult(step_id=step_id, status="failed", error=error_msg, duration_ms=elapsed_ms)
                step_results.append(sr)
                logger.error(f"  ✗ {step_id} failed: {error_msg}")

                await emit_event("workflow.step.failed", {
                    "workflow": manifest.name,
                    "step": step_id,
                    "agent": step.agent,
                    "task": step.task,
                    "error": error_msg,
                    "duration_ms": elapsed_ms,
                })

                # Check if downstream steps depend on this one
                downstream = [n for n in nx.descendants(G, step_id) if n in order]
                if downstream:
                    for ds in downstream[order.index(step_id)+1:]:
                        if ds in downstream:
                            sr = StepResult(step_id=ds, status="skipped", error=f"Upstream step '{step_id}' failed")
                            step_results.append(sr)
                            await emit_event("workflow.step.skipped", {
                                "workflow": manifest.name, "step": ds,
                                "reason": f"Upstream step '{step_id}' failed",
                            })
                    logger.warning(f"  Skipping downstream steps due to {step_id} failure: {downstream}")
                    break  # Stop execution chain

        # Final status
        all_ok = all(sr.status == "completed" for sr in step_results)
        if all_ok:
            await emit_event("workflow.completed", {
                "workflow": manifest.name,
                "steps_executed": len(step_results),
                "outputs": {sr.step_id: sr.output for sr in step_results},
            })
        else:
            failures = [sr.step_id for sr in step_results if sr.status == "failed"]
            await emit_event("workflow.failed", {
                "workflow": manifest.name,
                "failed_steps": failures,
            })

        return {
            "workflow": manifest.name,
            "status": "completed" if all_ok else "failed",
            "steps": [sr.model_dump() for sr in step_results],
        }

    async def _dispatch_step(self, step: WorkflowStep, params: dict, step_outputs: dict) -> Any:
        """Dispatch a single step to the appropriate service."""
        inputs = resolve_vars(step.inputs, params, step_outputs)
        logger.debug(f"  Dispatch: {step.agent}/{step.task} inputs={json.dumps(inputs, default=str)[:200]}")

        dispatch_key = (step.agent, step.task)
        if dispatch_key not in STEP_DISPATCH:
            raise ValueError(f"No dispatch mapping for {step.agent}/{step.task}")

        service, method, endpoint = STEP_DISPATCH[dispatch_key]

        if service == "_internal":
            # Internal steps that we handle directly
            return await self._internal_step(step, inputs)

        url = f"{SERVICES[service]}{endpoint}"
        return await self._http_call(service, url, method, inputs)

    async def _internal_step(self, step: WorkflowStep, inputs: dict) -> Any:
        """Handle internal/workflow steps that don't call a service."""
        if step.task == "publish_to_vault":
            # For now: return the content as the publish result
            content = inputs.get("content", "")
            return {"published": True, "content_length": len(str(content)), "content": content}
        elif step.task == "load_target_list":
            # Return override targets or placeholder list
            targets = inputs.get("override", [])
            return {"targets": targets if targets else ["placeholder"]}
        elif step.task in ("extract", "diff", "store"):
            # Stub — return input as output for downstream steps
            return {"status": "stub", "task": step.task, "inputs": inputs}
        raise ValueError(f"Unknown internal task: {step.task}")

    async def _http_call(self, service: str, url: str, method: str, payload: dict) -> dict:
        """Make an HTTP call to an internal service."""
        async with httpx.AsyncClient(timeout=120.0) as client:
            try:
                if method == "POST":
                    resp = await client.post(url, json=payload)
                elif method == "GET":
                    resp = await client.get(url, params=payload)
                else:
                    raise ValueError(f"Unsupported HTTP method: {method}")

                resp.raise_for_status()

                ct = resp.headers.get("content-type", "")
                if "application/json" in ct:
                    return resp.json()
                return {"status": resp.status_code, "body": resp.text}
            except httpx.ConnectError:
                raise Exception(f"Service '{service}' unreachable at {url}")
            except httpx.HTTPStatusError as e:
                raise Exception(f"Service '{service}' returned {e.response.status_code}: {e.response.text[:200]}")


# ─── API ─────────────────────────────────────────────────────────────────────

engine = WorkflowEngine()

app = FastAPI(title="Substrate Workflow Engine", version="0.2.0")


@app.get("/health")
async def health():
    # List available workflow manifests
    manifests = []
    if engine.manifests_dir.exists():
        for wf_file in engine.manifests_dir.glob("*.workflow.yml"):
            manifests.append(wf_file.stem.replace(".workflow", ""))
    return {"status": "ok", "loaded_workflows": manifests}


@app.on_event("startup")
async def startup():
    logger.info("Workflow engine starting — pre-loading manifests...")
    if engine.manifests_dir.exists():
        for wf_file in engine.manifests_dir.glob("*.workflow.yml"):
            name = wf_file.stem.replace(".workflow", "")
            engine.load_manifest(name)
            logger.info(f"  Loaded: {name}")


@app.post("/api/execute")
async def execute_workflow(req: TriggerRequest):
    manifest = engine.load_manifest(req.workflow)
    if not manifest:
        raise HTTPException(status_code=404, detail=f"Workflow '{req.workflow}' not found")

    try:
        result = await engine.execute(manifest, req.params)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception(f"Workflow execution failed: {req.workflow}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/workflows")
async def list_workflows():
    """List available workflow manifests."""
    manifests = []
    if engine.manifests_dir.exists():
        for wf_file in engine.manifests_dir.glob("*.workflow.yml"):
            m = engine.load_manifest(wf_file.stem.replace(".workflow", ""))
            if m:
                manifests.append({
                    "name": m.name,
                    "version": m.version,
                    "description": m.description,
                    "steps": len(m.steps),
                })
    return {"workflows": manifests}


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    import uvicorn
    port = int(os.getenv("WORKFLOW_ENGINE_PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
