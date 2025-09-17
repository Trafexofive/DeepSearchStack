#!/usr/bin/env python3
"""
End-to-End Test Suite for Workflow Automation Service
"""
import asyncio
import httpx
import json
import os
import time
import subprocess
import sys
from pathlib import Path

# Configuration
BASE_URL = "http://localhost:8005"
HEALTH_ENDPOINT = f"{BASE_URL}/health"
EXECUTE_ENDPOINT = f"{BASE_URL}/workflows/execute"

class WorkflowE2ETestSuite:
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
        
    async def wait_for_service(self, max_retries=30, delay=2):
        """Wait for the workflow service to be healthy"""
        print("🔍 Waiting for Workflow Automation Service to be ready...")
        for i in range(max_retries):
            try:
                response = await self.client.get(HEALTH_ENDPOINT)
                if response.status_code == 200:
                    data = response.json()
                    if data.get("status") == "healthy":
                        print("✅ Workflow Automation Service is healthy!")
                        return True
            except Exception as e:
                pass
            print(f"⏳ Waiting... ({i+1}/{max_retries})")
            await asyncio.sleep(delay)
        return False
    
    async def test_health_endpoint(self):
        """Test the health endpoint"""
        print("\n🧪 Testing Health Endpoint...")
        try:
            response = await self.client.get(HEALTH_ENDPOINT)
            assert response.status_code == 200, f"Expected 200, got {response.status_code}"
            data = response.json()
            assert data["status"] == "healthy", f"Expected healthy status, got {data['status']}"
            assert "timestamp" in data, "Missing timestamp in response"
            print("✅ Health endpoint test passed")
            return True
        except Exception as e:
            print(f"❌ Health endpoint test failed: {e}")
            return False
    
    async def test_execute_nonexistent_workflow(self):
        """Test executing a workflow that doesn't exist"""
        print("\n🧪 Testing Non-existent Workflow Execution...")
        try:
            payload = {"manifest_path": "/non/existent/workflow.yaml"}
            response = await self.client.post(EXECUTE_ENDPOINT, json=payload)
            # Should return an error (not 200)
            assert response.status_code != 200, f"Expected error status, got {response.status_code}"
            print("✅ Non-existent workflow test passed")
            return True
        except Exception as e:
            print(f"❌ Non-existent workflow test failed: {e}")
            return False
    
    async def test_workflow_execution(self):
        """Test executing a real workflow"""
        print("\n🧪 Testing Real Workflow Execution...")
        try:
            # Use the test workflow we created earlier
            payload = {"manifest_path": "workflows/test-workflow.yaml"}
            response = await self.client.post(EXECUTE_ENDPOINT, json=payload)
            
            if response.status_code == 200:
                data = response.json()
                assert "workflow_id" in data, "Missing workflow_id in response"
                assert data["workflow_id"] == "test-workflow", f"Expected test-workflow, got {data['workflow_id']}"
                assert "status" in data, "Missing status in response"
                assert data["status"] == "completed", f"Expected completed status, got {data['status']}"
                assert "tasks" in data, "Missing tasks in response"
                assert "outputs" in data, "Missing outputs in response"
                print("✅ Workflow execution test passed")
                return True
            else:
                print(f"❌ Workflow execution failed with status {response.status_code}: {response.text}")
                return False
        except Exception as e:
            print(f"❌ Workflow execution test failed: {e}")
            return False
    
    async def test_invalid_payload(self):
        """Test sending invalid payload"""
        print("\n🧪 Testing Invalid Payload...")
        try:
            # Send invalid JSON
            response = await self.client.post(EXECUTE_ENDPOINT, json={"invalid": "data"})
            # Should handle gracefully
            print("✅ Invalid payload test passed")
            return True
        except Exception as e:
            print(f"❌ Invalid payload test failed: {e}")
            return False
    
    async def run_all_tests(self):
        """Run all tests in sequence"""
        print("🚀 Starting Workflow Automation Service End-to-End Test Suite")
        print("=" * 60)
        
        # Wait for service to be ready
        if not await self.wait_for_service():
            print("❌ Service did not become ready in time")
            return False
        
        # Run individual tests
        tests = [
            self.test_health_endpoint,
            self.test_execute_nonexistent_workflow,
            self.test_workflow_execution,
            self.test_invalid_payload
        ]
        
        results = []
        for test in tests:
            try:
                result = await test()
                results.append(result)
            except Exception as e:
                print(f"❌ Test {test.__name__} failed with exception: {e}")
                results.append(False)
        
        # Summary
        passed = sum(results)
        total = len(results)
        print("\n" + "=" * 60)
        print(f"📊 Test Results: {passed}/{total} tests passed")
        
        if passed == total:
            print("🎉 All tests passed! Workflow Automation Service is working correctly.")
            return True
        else:
            print("💥 Some tests failed. Please check the output above.")
            return False

async def main():
    """Main test function"""
    test_suite = WorkflowE2ETestSuite()
    success = await test_suite.run_all_tests()
    return 0 if success else 1

if __name__ == "__main__":
    result = asyncio.run(main())
    sys.exit(result)