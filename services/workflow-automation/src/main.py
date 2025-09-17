import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Dict, Any, List
import os
import yaml
from workflow_engine import WorkflowEngine
import asyncio
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Workflow Automation Service", version="1.0.0")

# Global workflow engine instance
workflow_engine = None

class WorkflowRequest(BaseModel):
    manifest_path: str

class WorkflowResponse(BaseModel):
    workflow_id: str
    status: str
    tasks: Dict[str, Any]
    outputs: List[Dict[str, Any]]

@app.on_event("startup")
async def startup_event():
    global workflow_engine
    config = {
        "search_agent_url": os.environ.get("SEARCH_AGENT_URL", "http://search-agent:8001"),
        "llm_gateway_url": os.environ.get("LLM_GATEWAY_URL", "http://llm-gateway:8080"),
        "vector_store_url": os.environ.get("VECTOR_STORE_URL", "http://vector-store:8003")
    }
    workflow_engine = WorkflowEngine(config)
    logger.info("Workflow Automation Service started")

@app.post("/workflows/execute", response_model=WorkflowResponse)
async def execute_workflow(request: WorkflowRequest):
    """Execute a workflow from a manifest file"""
    try:
        if not workflow_engine:
            raise HTTPException(status_code=500, detail="Workflow engine not initialized")
        
        result = await workflow_engine.execute_workflow(request.manifest_path)
        return WorkflowResponse(**result)
    except Exception as e:
        logger.error(f"Workflow execution failed: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "workflow-automation", "timestamp": datetime.now().isoformat()}

@app.get("/")
async def root():
    return {
        "message": "Workflow Automation Service",
        "description": "Automate complex workflows across DeepSearchStack services",
        "endpoints": {
            "/health": "GET - Health check",
            "/workflows/execute": "POST - Execute a workflow from a manifest",
            "/workflows/templates": "GET - List available workflow templates"
        }
    }

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8005)