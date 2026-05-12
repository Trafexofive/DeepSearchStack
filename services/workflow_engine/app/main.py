"""
workflow_engine — Substrate DAG Executor

Parses .workflow.yml manifests into directed acyclic graphs,
resolves dependencies, and executes steps via agent dispatchers.
"""

import os
import yaml
import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("workflow_engine")


# ─── Data Models ─────────────────────────────────────────────────────────────

class WorkflowStep(BaseModel):
    id: str
    agent: str
    task: str
    inputs: dict = {}
    tools: list[str] = []
    relics: list[str] = []
    depends_on: list[str] = []
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


# ─── Engine Core ─────────────────────────────────────────────────────────────

class WorkflowEngine:
    """Parses workflow manifests and manages execution DAGs."""

    def __init__(self, manifests_dir: str = "manifests/workflows"):
        self.manifests_dir = Path(manifests_dir)
        self._workflows: dict[str, WorkflowManifest] = {}

    def load_manifest(self, name: str) -> Optional[WorkflowManifest]:
        """Load and parse a .workflow.yml file."""
        path = self.manifests_dir / f"{name}.workflow.yml"
        if not path.exists():
            # Try with .yml extension
            path = self.manifests_dir / f"{name}.yml"
        if not path.exists():
            logger.error(f"Workflow manifest not found: {name}")
            return None

        with open(path) as f:
            data = yaml.safe_load(f)

        manifest = WorkflowManifest(**data)
        self._workflows[name] = manifest
        logger.info(f"Loaded workflow: {manifest.name} (v{manifest.version})")
        return manifest

    def validate_dag(self, manifest: WorkflowManifest) -> bool:
        """Validate that steps form a valid DAG (no cycles)."""
        step_ids = {s.id for s in manifest.steps}
        for step in manifest.steps:
            for dep in step.depends_on:
                if dep not in step_ids:
                    logger.error(f"Step '{step.id}' depends on unknown step '{dep}'")
                    return False
        # TODO: full cycle detection via DFS
        return True

    async def execute(self, manifest: WorkflowManifest, params: dict = None):
        """
        Execute a workflow DAG.
        For now: log the execution plan.
        """
        logger.info(f"Executing workflow: {manifest.name}")
        logger.info(f"Steps: {[s.id for s in manifest.steps]}")
        logger.info(f"Params: {params}")

        if not self.validate_dag(manifest):
            raise ValueError("Invalid DAG in workflow manifest")

        # TODO: topological sort, parallel step execution,
        #       agent dispatch, retry logic, event bus notifications

        return {
            "status": "completed",
            "workflow": manifest.name,
            "steps_executed": len(manifest.steps),
        }


# ─── API ─────────────────────────────────────────────────────────────────────

engine = WorkflowEngine()

app = FastAPI(title="Substrate Workflow Engine", version="0.1.0")


@app.get("/health")
async def health():
    return {"status": "ok", "loaded_workflows": list(engine._workflows.keys())}


@app.post("/api/execute")
async def execute_workflow(req: TriggerRequest):
    manifest = engine.load_manifest(req.workflow)
    if not manifest:
        return {"error": f"Workflow '{req.workflow}' not found"}, 404

    try:
        result = await engine.execute(manifest, req.params)
        return result
    except ValueError as e:
        return {"error": str(e)}, 400


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    import uvicorn

    # Pre-load all workflows on startup
    logger.info("Pre-loading workflow manifests...")
    workflows_dir = Path("manifests/workflows")
    if workflows_dir.exists():
        for wf_file in workflows_dir.glob("*.workflow.yml"):
            engine.load_manifest(wf_file.stem.replace(".workflow", ""))

    port = int(os.getenv("WORKFLOW_ENGINE_PORT", "8001"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
