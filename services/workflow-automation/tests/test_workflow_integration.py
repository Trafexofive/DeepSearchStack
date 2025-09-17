import pytest
import asyncio
import os
import tempfile
import yaml
import json
from unittest.mock import AsyncMock, patch
import sys

# Add src to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from workflow_engine import WorkflowEngine, WorkflowContext

@pytest.fixture
def sample_workflow_manifest():
    return {
        "apiVersion": "automation.deeps/v1",
        "kind": "Workflow",
        "metadata": {
            "name": "test-workflow",
            "description": "Test workflow for integration testing"
        },
        "spec": {
            "triggers": [
                {"type": "api", "endpoint": "/trigger/test"}
            ],
            "tasks": [
                {
                    "name": "test-search",
                    "type": "search",
                    "provider": "agent",
                    "parameters": {
                        "query": "test search query",
                        "max_results": 3
                    },
                    "conditions": {},
                    "retries": 1,
                    "timeout": 30
                },
                {
                    "name": "test-llm",
                    "type": "llm",
                    "provider": "llm-gateway",
                    "dependsOn": ["test-search"],
                    "parameters": {
                        "messages": [
                            {"role": "user", "content": "Summarize: {{tasks.test-search.result.answer}}"}
                        ],
                        "temperature": 0.5
                    },
                    "conditions": {},
                    "retries": 1,
                    "timeout": 30
                }
            ],
            "outputs": [
                {
                    "name": "final-result",
                    "value": "{{tasks.test-llm.result}}",
                    "destinations": [
                        {"type": "file", "path": "/tmp/test-result.txt"}
                    ]
                }
            ]
        }
    }

@pytest.fixture
def workflow_engine():
    config = {
        "search_agent_url": "http://search-agent:8001",
        "llm_gateway_url": "http://llm-gateway:8080",
        "vector_store_url": "http://vector-store:8003"
    }
    return WorkflowEngine(config)

class TestWorkflowIntegration:
    @pytest.mark.asyncio
    async def test_workflow_execution_with_mocks(self, workflow_engine, sample_workflow_manifest):
        # Create a temporary file for the manifest
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(sample_workflow_manifest, f)
            manifest_path = f.name
        
        try:
            # Mock the HTTP calls
            with patch('workflow_engine.httpx.AsyncClient') as mock_client:
                # Create mock responses
                mock_search_response = AsyncMock()
                mock_search_response.raise_for_status = AsyncMock()
                mock_search_response.json = AsyncMock(return_value={
                    "answer": "This is a test search result with important information.",
                    "sources": []
                })
                
                mock_llm_response = AsyncMock()
                mock_llm_response.raise_for_status = AsyncMock()
                mock_llm_response.json = AsyncMock(return_value={
                    "content": "This is a summary of the search results.",
                    "provider_name": "test-provider"
                })
                
                # Configure the mock client to return appropriate responses
                mock_instance = AsyncMock()
                mock_instance.__aenter__.return_value = mock_instance
                mock_instance.post.side_effect = [
                    mock_search_response,  # First call for search
                    mock_llm_response      # Second call for LLM
                ]
                mock_client.return_value = mock_instance
                
                # Execute the workflow
                result = await workflow_engine.execute_workflow(manifest_path)
                
                # Verify the overall result structure
                assert result["workflow_id"] == "test-workflow"
                assert result["status"] == "completed"
                assert "tasks" in result
                assert "outputs" in result
                
                # Verify task results
                assert "test-search" in result["tasks"]
                assert "test-llm" in result["tasks"]
                
                # Verify search task result
                search_result = result["tasks"]["test-search"]
                assert search_result["success"] is True
                assert "answer" in search_result["result"]
                
                # Verify LLM task result
                llm_result = result["tasks"]["test-llm"]
                assert llm_result["success"] is True
                assert llm_result["result"] == "This is a summary of the search results."
                
                # Verify outputs
                assert len(result["outputs"]) == 1
                output = result["outputs"][0]
                assert output["name"] == "final-result"
                assert output["value"] == "This is a summary of the search results."
                
                # Verify that the HTTP calls were made correctly
                assert mock_instance.post.call_count == 2
                
                # First call should be to search agent
                mock_instance.post.assert_any_call(
                    "http://search-agent:8001/search",
                    json={"query": "test search query", "max_results": 3}
                )
                
                # Second call should be to LLM gateway
                mock_instance.post.assert_any_call(
                    "http://llm-gateway:8080/completion",
                    json={
                        "messages": [
                            {"role": "user", "content": "Summarize: This is a test search result with important information."}
                        ],
                        "temperature": 0.5,
                        "stream": False
                    }
                )
                
        finally:
            # Clean up the temporary file
            os.unlink(manifest_path)

    @pytest.mark.asyncio
    async def test_workflow_with_failed_task(self, workflow_engine, sample_workflow_manifest):
        # Modify the workflow to test error handling
        sample_workflow_manifest["spec"]["tasks"][0]["parameters"]["query"] = ""
        
        # Create a temporary file for the manifest
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(sample_workflow_manifest, f)
            manifest_path = f.name
        
        try:
            # Execute the workflow - this should fail because search query is empty
            result = await workflow_engine.execute_workflow(manifest_path)
            
            # Verify that the workflow completed but the search task failed
            assert result["workflow_id"] == "test-workflow"
            assert result["status"] == "completed"
            assert "test-search" in result["tasks"]
            
            # The search task should have failed
            search_result = result["tasks"]["test-search"]
            assert search_result["success"] is False
            assert "requires a query" in search_result["error"]
            
        finally:
            # Clean up the temporary file
            os.unlink(manifest_path)

    @pytest.mark.asyncio
    async def test_empty_workflow(self, workflow_engine):
        empty_workflow = {
            "apiVersion": "automation.deeps/v1",
            "kind": "Workflow",
            "metadata": {
                "name": "empty-workflow"
            },
            "spec": {
                "tasks": [],
                "outputs": []
            }
        }
        
        # Create a temporary file for the manifest
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            yaml.dump(empty_workflow, f)
            manifest_path = f.name
        
        try:
            # Execute the empty workflow
            result = await workflow_engine.execute_workflow(manifest_path)
            
            # Should complete successfully with no tasks
            assert result["workflow_id"] == "empty-workflow"
            assert result["status"] == "completed"
            assert result["tasks"] == {}
            assert result["outputs"] == []
            
        finally:
            # Clean up the temporary file
            os.unlink(manifest_path)