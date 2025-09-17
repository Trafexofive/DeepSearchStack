import pytest
import asyncio
import os
import tempfile
import yaml
from unittest.mock import AsyncMock, patch
import sys
import json

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from workflow_engine import WorkflowEngine, WorkflowContext, TaskResult

@pytest.fixture
def workflow_context():
    return WorkflowContext("test-workflow")

@pytest.fixture
def workflow_engine():
    config = {
        "search_agent_url": "http://search-agent:8001",
        "llm_gateway_url": "http://llm-gateway:8080",
        "vector_store_url": "http://vector-store:8003"
    }
    return WorkflowEngine(config)

class TestWorkflowContext:
    def test_initialization(self, workflow_context):
        assert workflow_context.workflow_id == "test-workflow"
        assert "workflow" in workflow_context.variables
        assert "tasks" in workflow_context.variables
        
    def test_set_and_get_task_result(self, workflow_context):
        result = TaskResult(
            name="test-task",
            success=True,
            result="test result"
        )
        workflow_context.set_task_result("test-task", result)
        
        # Check that the result is stored correctly
        assert "test-task" in workflow_context.variables["tasks"]
        stored_result = workflow_context.variables["tasks"]["test-task"]
        assert stored_result["name"] == "test-task"
        assert stored_result["success"] is True
        assert stored_result["result"] == "test result"
        
    def test_get_variable(self, workflow_context):
        # Test getting existing variable
        workflow_var = workflow_context.get_variable("workflow.id")
        assert workflow_var == "test-workflow"
        
        # Test getting non-existing variable
        non_existing = workflow_context.get_variable("non.existing.variable")
        assert non_existing is None

class TestWorkflowEngine:
    def test_initialization(self, workflow_engine):
        assert workflow_engine.config is not None
        assert "search_agent_url" in workflow_engine.config
        assert "llm_gateway_url" in workflow_engine.config
        assert "vector_store_url" in workflow_engine.config
        
    def test_resolve_parameters_without_template(self, workflow_engine, workflow_context):
        params = {
            "query": "test query",
            "max_results": 10
        }
        resolved = workflow_engine.resolve_parameters(params, workflow_context)
        assert resolved == params
        
    def test_resolve_parameters_with_template(self, workflow_engine, workflow_context):
        # Set up a task result first
        task_result = TaskResult(
            name="previous-task",
            success=True,
            result="previous result data"
        )
        workflow_context.set_task_result("previous-task", task_result)
        
        params = {
            "input": "{{tasks.previous-task.result}}",
            "static": "static value"
        }
        resolved = workflow_engine.resolve_parameters(params, workflow_context)
        assert resolved["input"] == "previous result data"
        assert resolved["static"] == "static value"

    @pytest.mark.asyncio
    async def test_execute_search_task(self, workflow_engine):
        # Mock the HTTP client
        with patch('workflow_engine.httpx.AsyncClient') as mock_client:
            # Create a mock response
            mock_response = AsyncMock()
            mock_response.raise_for_status = AsyncMock()
            mock_response.json = AsyncMock(return_value={
                "answer": "Test search result",
                "sources": []
            })
            
            # Configure the mock client
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response
            mock_client.return_value = mock_instance
            
            # Execute the task
            params = {
                "query": "test query",
                "max_results": 5
            }
            result = await workflow_engine.execute_search_task(params)
            
            # Verify the call was made correctly
            mock_instance.post.assert_called_once_with(
                "http://search-agent:8001/search",
                json={"query": "test query", "max_results": 5}
            )
            
            # Verify the result
            assert "answer" in result
            assert result["answer"] == "Test search result"

    @pytest.mark.asyncio
    async def test_execute_llm_task(self, workflow_engine):
        # Mock the HTTP client
        with patch('workflow_engine.httpx.AsyncClient') as mock_client:
            # Create a mock response
            mock_response = AsyncMock()
            mock_response.raise_for_status = AsyncMock()
            mock_response.json = AsyncMock(return_value={
                "content": "Test LLM response",
                "provider_name": "test-provider"
            })
            
            # Configure the mock client
            mock_instance = AsyncMock()
            mock_instance.__aenter__.return_value = mock_instance
            mock_instance.post.return_value = mock_response
            mock_client.return_value = mock_instance
            
            # Execute the task
            params = {
                "messages": [
                    {"role": "user", "content": "Hello"}
                ],
                "temperature": 0.7
            }
            result = await workflow_engine.execute_llm_task(params)
            
            # Verify the call was made correctly
            mock_instance.post.assert_called_once_with(
                "http://llm-gateway:8080/completion",
                json={
                    "messages": [{"role": "user", "content": "Hello"}],
                    "temperature": 0.7,
                    "stream": False
                }
            )
            
            # Verify the result
            assert result == "Test LLM response"

    @pytest.mark.asyncio
    async def test_execute_storage_task(self, workflow_engine):
        # Mock the HTTP client
        with patch('workflow_engine.httpx.AsyncClient') as mock_client:
            # Execute the task
            params = {
                "document": {
                    "id": "test-doc-123",
                    "text": "Test document content",
                    "metadata": {"source": "test"}
                }
            }
            result = await workflow_engine.execute_storage_task(params)
            
            # Verify the result
            assert result["status"] == "stored"
            assert result["document_id"] == "test-doc-123"

    @pytest.mark.asyncio
    async def test_process_output_to_file(self, workflow_engine, workflow_context):
        # Create a temporary directory for testing
        with tempfile.TemporaryDirectory() as temp_dir:
            # Set up context with some data
            workflow_context.variables["test"] = "test output data"
            
            output_config = {
                "name": "test-output",
                "value": "test",
                "destinations": [
                    {
                        "type": "file",
                        "path": f"{temp_dir}/test-output.txt"
                    }
                ]
            }
            
            result = await workflow_engine.process_output(output_config, workflow_context)
            
            # Verify the result structure
            assert result["name"] == "test-output"
            assert result["value"] == "test output data"
            assert len(result["destinations"]) == 1
            assert result["destinations"][0]["type"] == "file"
            assert result["destinations"][0]["status"] == "success"
            
            # Verify the file was created with correct content
            output_file = os.path.join(temp_dir, "test-output.txt")
            assert os.path.exists(output_file)
            with open(output_file, 'r') as f:
                content = f.read()
                assert content == "test output data"