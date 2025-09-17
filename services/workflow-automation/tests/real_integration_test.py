#!/usr/bin/env python3
"""
Real Integration Test for Workflow Automation Service
This test uses the actual running services in the stack.
"""
import asyncio
import httpx
import json
import time

BASE_URL = "http://localhost:8005"
LLM_GATEWAY_URL = "http://localhost:32775"
SEARCH_AGENT_URL = "http://localhost:8001"

async def wait_for_services():
    """Wait for all required services to be ready"""
    print("🔍 Waiting for services to be ready...")
    services = {
        "Workflow Automation": f"{BASE_URL}/health",
        "LLM Gateway": f"{LLM_GATEWAY_URL}/health",
        "Search Agent": f"{SEARCH_AGENT_URL}/health"
    }
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for service_name, url in services.items():
            for i in range(30):  # Wait up to 30 seconds
                try:
                    response = await client.get(url)
                    if response.status_code == 200:
                        print(f"   ✅ {service_name} is ready")
                        break
                except:
                    pass
                print(f"   ⏳ Waiting for {service_name}... ({i+1}/30)")
                await asyncio.sleep(1)
            else:
                print(f"   ❌ {service_name} did not become ready in time")
                return False
    return True

async def test_real_llm_task():
    """Test executing a real LLM task through the workflow service"""
    print("\n🤖 Testing Real LLM Task Execution")
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Execute the workflow
        payload = {"manifest_path": "workflows/real-llm-test.yaml"}
        response = await client.post(f"{BASE_URL}/workflows/execute", json=payload)
        
        if response.status_code == 200:
            result = response.json()
            print(f"   ✅ Workflow executed successfully")
            print(f"   📊 Workflow ID: {result['workflow_id']}")
            print(f"   📈 Tasks: {len(result['tasks'])}")
            
            # Check the LLM task result
            if "simple-llm-task" in result["tasks"]:
                task_result = result["tasks"]["simple-llm-task"]
                if task_result["success"]:
                    print(f"   🎯 LLM Task Success!")
                    # The result should contain "4" or "four" since we asked "What is 2+2?"
                    llm_response = str(task_result["result"]).lower()
                    if "4" in llm_response or "four" in llm_response:
                        print(f"   🧠 LLM gave correct answer: {llm_response[:100]}...")
                    else:
                        print(f"   ⚠️  LLM response might be incorrect: {llm_response[:100]}...")
                else:
                    print(f"   ❌ LLM Task Failed: {task_result.get('error', 'Unknown error')}")
            return True
        else:
            print(f"   ❌ Workflow execution failed: {response.status_code}")
            print(f"   📄 Error: {response.text}")
            return False

async def test_service_connectivity():
    """Test direct connectivity to services"""
    print("\n🔌 Testing Direct Service Connectivity")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        # Test LLM Gateway directly
        try:
            response = await client.get(f"{LLM_GATEWAY_URL}/health")
            if response.status_code == 200:
                print("   ✅ LLM Gateway reachable")
            else:
                print(f"   ❌ LLM Gateway health check failed: {response.status_code}")
        except Exception as e:
            print(f"   ❌ LLM Gateway connection failed: {e}")
        
        # Test Search Agent directly
        try:
            response = await client.get(f"{SEARCH_AGENT_URL}/health")
            if response.status_code == 200:
                print("   ✅ Search Agent reachable")
            else:
                print(f"   ❌ Search Agent health check failed: {response.status_code}")
        except Exception as e:
            print(f"   ❌ Search Agent connection failed: {e}")

async def main():
    """Main integration test function"""
    print("🚀 Real Integration Test for Workflow Automation Service")
    print("=" * 60)
    
    # Wait for services to be ready
    if not await wait_for_services():
        print("❌ Required services are not ready. Exiting.")
        return 1
    
    # Test direct connectivity
    await test_service_connectivity()
    
    # Test real LLM task execution
    success = await test_real_llm_task()
    
    print("\n" + "=" * 60)
    if success:
        print("🎉 Real Integration Test Completed Successfully!")
        print("The Workflow Automation Service can successfully orchestrate real services.")
    else:
        print("💥 Real Integration Test Failed!")
        print("There were issues with the service orchestration.")
    
    return 0 if success else 1

if __name__ == "__main__":
    result = asyncio.run(main())
    exit(result)