"""
WorkflowClient — DAG workflow execution.

Endpoints:
  GET  /api/workflows               — List available workflows
  POST /api/workflows/execute       — Execute a workflow
"""

from typing import Optional

from pydantic import BaseModel


class TriggerRequest(BaseModel):
    workflow: str
    params: dict = {}


class StepResult(BaseModel):
    step_id: str
    status: str
    output: Optional[dict] = None
    error: str = ""
    duration_ms: int = 0


class WorkflowResult(BaseModel):
    workflow: str
    status: str
    steps: list[StepResult]


class WorkflowInfo(BaseModel):
    name: str
    version: str
    description: str
    steps: int


class WorkflowClient:
    """Client for the workflow_engine service."""

    def __init__(self, base_url: str = "http://localhost:80", api_key: Optional[str] = None, timeout: float = 300.0):
        from substrate.client import SubstrateClient
        self._client = SubstrateClient(base_url, api_key, timeout)

    async def list(self) -> list[WorkflowInfo]:
        """List available workflow manifests."""
        resp = await self._client._request("GET", "/api/workflows")
        resp.raise_for_status()
        return [WorkflowInfo(**w) for w in resp.json().get("workflows", [])]

    async def execute(self, workflow: str, params: dict = {}) -> WorkflowResult:
        """Execute a workflow DAG. Blocks until completion (may take 60-120s)."""
        req = TriggerRequest(workflow=workflow, params=params)
        resp = await self._client._request("POST", "/api/workflows/execute", json=req.model_dump())
        resp.raise_for_status()
        data = resp.json()
        steps = [StepResult(**s) for s in data.get("steps", [])]
        return WorkflowResult(workflow=data["workflow"], status=data["status"], steps=steps)

    # Convenience: trigger seo_content_loop
    async def seo_content_loop(self, topic: str, keyword: str = "",
                                tone: str = "technical") -> WorkflowResult:
        """Run the full SEO content pipeline: research → outline → generate → audit → publish."""
        return await self.execute("seo_content_loop", {
            "topic": topic,
            "keyword": keyword or topic,
            "tone": tone,
        })

    async def weekly_recon_sweep(self, targets: list[str] = []) -> WorkflowResult:
        """Run competitive intelligence sweep."""
        return await self.execute("weekly_recon_sweep", {"targets": targets})

    async def close(self):
        await self._client.close()
