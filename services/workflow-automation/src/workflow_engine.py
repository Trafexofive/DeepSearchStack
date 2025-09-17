import yaml
import json
import httpx
import asyncio
import logging
from typing import Dict, Any, List, Optional
from pydantic import BaseModel
from datetime import datetime
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class TaskResult(BaseModel):
    name: str
    success: bool
    result: Any = None
    error: Optional[str] = None

class WorkflowContext:
    def __init__(self, workflow_id: str):
        self.workflow_id = workflow_id
        self.variables = {
            "workflow": {
                "id": workflow_id,
                "timestamp": datetime.now().isoformat()
            },
            "tasks": {}
        }
    
    def set_task_result(self, task_name: str, result: TaskResult):
        self.variables["tasks"][task_name] = result.dict()
    
    def get_variable(self, path: str) -> Any:
        """Get variable using dot notation like 'tasks.search-task.result'"""
        keys = path.split('.')
        value = self.variables
        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return None

class WorkflowEngine:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        # Check if we're running in Docker (use internal URLs) or on host (use external URLs)
        if os.path.exists('/.dockerenv') or 'DOCKER_ENV' in os.environ:
            # Running inside Docker container
            self.services = {
                "agent": os.environ.get("SEARCH_AGENT_URL", "http://search-agent:8001"),
                "llm-gateway": os.environ.get("LLM_GATEWAY_URL", "http://llm-gateway:8080"),
                "vector-store": os.environ.get("VECTOR_STORE_URL", "http://vector-store:8003"),
                "search-gateway": os.environ.get("SEARCH_GATEWAY_URL", "http://search-gateway:8002")
            }
        else:
            # Running on host (testing)
            self.services = {
                "agent": os.environ.get("SEARCH_AGENT_URL", "http://localhost:8001"),
                "llm-gateway": os.environ.get("LLM_GATEWAY_URL", "http://localhost:32776"),
                "vector-store": os.environ.get("VECTOR_STORE_URL", "http://localhost:8003"),
                "search-gateway": os.environ.get("SEARCH_GATEWAY_URL", "http://localhost:8002")
            }
    
    async def execute_workflow(self, manifest_path: str) -> Dict[str, Any]:
        """Execute a workflow from a manifest file"""
        with open(manifest_path, 'r') as f:
            workflow_manifest = yaml.safe_load(f)
        
        workflow_id = workflow_manifest.get('metadata', {}).get('name', 'unnamed-workflow')
        logger.info(f"Executing workflow: {workflow_id}")
        
        context = WorkflowContext(workflow_id)
        results = {}
        
        # Execute tasks in order (with dependency handling)
        tasks = workflow_manifest.get('spec', {}).get('tasks', [])
        task_results = {}
        
        # Simple approach: execute tasks in order for now
        for task in tasks:
            task_name = task['name']
            logger.info(f"Executing task: {task_name}")
            
            try:
                result = await self.execute_task(task, context)
                task_results[task_name] = result
                context.set_task_result(task_name, result)
                
                if not result.success:
                    logger.error(f"Task {task_name} failed: {result.error}")
                    # Depending on workflow policy, we might want to continue or stop
            except Exception as e:
                logger.error(f"Task {task_name} failed with exception: {str(e)}")
                task_results[task_name] = TaskResult(
                    name=task_name,
                    success=False,
                    error=str(e)
                )
                context.set_task_result(task_name, task_results[task_name])
        
        # Process outputs
        outputs = workflow_manifest.get('spec', {}).get('outputs', [])
        output_results = []
        for output in outputs:
            output_result = await self.process_output(output, context)
            output_results.append(output_result)
        
        return {
            "workflow_id": workflow_id,
            "status": "completed",
            "tasks": task_results,
            "outputs": output_results
        }
    
    async def execute_task(self, task: Dict[str, Any], context: WorkflowContext) -> TaskResult:
        """Execute a single task based on its type"""
        task_type = task['type']
        task_name = task['name']
        
        # Resolve parameters with context variables
        resolved_params = self.resolve_parameters(task.get('parameters', {}), context)
        
        try:
            if task_type == "search":
                result = await self.execute_search_task(resolved_params)
            elif task_type == "llm":
                result = await self.execute_llm_task(resolved_params)
            elif task_type == "storage":
                result = await self.execute_storage_task(resolved_params)
            else:
                raise ValueError(f"Unknown task type: {task_type}")
            
            return TaskResult(
                name=task_name,
                success=True,
                result=result
            )
        except Exception as e:
            return TaskResult(
                name=task_name,
                success=False,
                error=str(e)
            )
    
    def resolve_parameters(self, params: Dict[str, Any], context: WorkflowContext) -> Dict[str, Any]:
        """Resolve template variables in parameters"""
        resolved = {}
        for key, value in params.items():
            if isinstance(value, str) and '{{' in value:
                # Simple template resolution
                resolved_value = value
                for var_path in context.variables:
                    if var_path in resolved_value:
                        var_value = context.get_variable(var_path)
                        if var_value:
                            resolved_value = resolved_value.replace(f"{{{{{var_path}}}}}", str(var_value))
                resolved[key] = resolved_value
            elif isinstance(value, dict):
                resolved[key] = self.resolve_parameters(value, context)
            else:
                resolved[key] = value
        return resolved
    
    async def execute_search_task(self, params: Dict[str, Any]) -> Any:
        """Execute a search task using the search gateway"""
        query = params.get('query', '')
        if not query:
            raise ValueError("Search task requires a query parameter")
        
        service_url = self.services.get('search-gateway', 'http://search-gateway:8002')
        payload = {
            "query": query,
            "max_results": params.get('max_results', 10)
        }
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{service_url}/search", json=payload)
            response.raise_for_status()
            return response.json()
    
    async def execute_llm_task(self, params: Dict[str, Any]) -> Any:
        """Execute an LLM task using the LLM gateway"""
        messages = params.get('messages', [])
        if not messages:
            raise ValueError("LLM task requires messages parameter")
        
        service_url = self.services.get('llm-gateway', 'http://llm-gateway:8080')
        payload = {
            "messages": messages,
            "temperature": params.get('temperature', 0.7),
            "stream": False
        }
        
        # Add provider parameter if specified
        if 'provider' in params:
            payload['provider'] = params['provider']
        
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(f"{service_url}/completion", json=payload)
            response.raise_for_status()
            result = response.json()
            return result.get('content', '')
    
    async def execute_storage_task(self, params: Dict[str, Any]) -> Any:
        """Execute a storage task using the vector store"""
        service_url = self.services.get('vector-store', 'http://vector-store:8003')
        
        # For now, we'll just log the storage request
        logger.info(f"Storing document in vector store: {params}")
        
        # In a real implementation, you would call the vector store API
        # For example:
        # async with httpx.AsyncClient() as client:
        #     response = await client.post(f"{service_url}/embed", json=params)
        #     response.raise_for_status()
        #     return response.json()
        
        return {"status": "stored", "document_id": params.get('document', {}).get('id', 'unknown')}
    
    async def process_output(self, output: Dict[str, Any], context: WorkflowContext) -> Dict[str, Any]:
        """Process an output directive"""
        output_name = output.get('name', 'unnamed-output')
        value_path = output.get('value', '')
        
        # Resolve the value from context
        resolved_value = context.get_variable(value_path.replace('{{', '').replace('}}', '').strip())
        
        result = {
            "name": output_name,
            "value": resolved_value,
            "destinations": []
        }
        
        # Process destinations
        for dest in output.get('destinations', []):
            dest_type = dest.get('type')
            if dest_type == "file":
                file_path = dest.get('path', '').replace('{{workflow.id}}', context.workflow_id)
                # Ensure directory exists
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                with open(file_path, 'w') as f:
                    f.write(str(resolved_value))
                result["destinations"].append({"type": "file", "path": file_path, "status": "success"})
            elif dest_type == "api":
                # In a real implementation, you would POST to the endpoint
                result["destinations"].append({"type": "api", "endpoint": dest.get('endpoint'), "status": "simulated"})
        
        return result