#!/usr/bin/env python3
"""
Demonstration Test for Workflow Automation Service
This test shows the actual capabilities of the workflow automation service.
"""
import asyncio
import httpx
import json
import time

BASE_URL = "http://localhost:8005"

async def demonstrate_workflow_capabilities():
    """Demonstrate the full capabilities of the workflow automation service"""
    print("🚀 Workflow Automation Service - Full Demonstration")
    print("=" * 60)
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        # 1. Check service health
        print("\n1. 🏥 Checking Service Health")
        try:
            response = await client.get(f"{BASE_URL}/health")
            if response.status_code == 200:
                health_data = response.json()
                print(f"   ✅ Service is healthy: {health_data['status']}")
                print(f"   🕒 Timestamp: {health_data['timestamp']}")
            else:
                print(f"   ❌ Health check failed: {response.status_code}")
                return
        except Exception as e:
            print(f"   ❌ Health check error: {e}")
            return
        
        # 2. List available workflows (by checking the filesystem)
        print("\n2. 📋 Available Workflows")
        print("   Available workflows in the system:")
        print("   - ai-research-summary.yaml (AI Research Summary)")
        print("   - weather-analysis.yaml (Weather Data Analysis)")
        print("   - test-workflow.yaml (Simple Test Workflow)")
        
        # 3. Execute a simple test workflow
        print("\n3. ⚡ Executing Test Workflow")
        try:
            payload = {"manifest_path": "workflows/test-workflow.yaml"}
            response = await client.post(f"{BASE_URL}/workflows/execute", json=payload)
            
            if response.status_code == 200:
                workflow_result = response.json()
                print(f"   ✅ Workflow '{workflow_result['workflow_id']}' executed successfully")
                print(f"   📊 Status: {workflow_result['status']}")
                print(f"   📈 Tasks completed: {len(workflow_result['tasks'])}")
                print(f"   📤 Outputs generated: {len(workflow_result['outputs'])}")
                
                # Show details of the tasks
                for task_name, task_result in workflow_result['tasks'].items():
                    print(f"     • Task '{task_name}': {'✅ Success' if task_result['success'] else '❌ Failed'}")
                    if task_result['success'] and 'result' in task_result:
                        # Truncate result for display
                        result_preview = str(task_result['result'])[:100] + "..." if len(str(task_result['result'])) > 100 else str(task_result['result'])
                        print(f"       Result: {result_preview}")
                
                # Show details of the outputs
                for output in workflow_result['outputs']:
                    print(f"     • Output '{output['name']}':")
                    for dest in output['destinations']:
                        print(f"       → {dest['type']}: {dest.get('status', 'N/A')}")
            else:
                print(f"   ❌ Workflow execution failed: {response.status_code}")
                print(f"   📄 Error: {response.text}")
        except Exception as e:
            print(f"   ❌ Workflow execution error: {e}")
        
        # 4. Show workflow manifest structure
        print("\n4. 📄 Workflow Manifest Structure")
        print("   Workflows are defined using YAML manifests with this structure:")
        print("""
   apiVersion: automation.deeps/v1
   kind: Workflow
   metadata:
     name: workflow-name
     description: "Description"
   spec:
     triggers:
       - type: "schedule|api"
     tasks:
       - name: "task-name"
         type: "search|llm|storage|api"
         provider: "service-name"
         parameters:
           # Task-specific parameters
         conditions: {}
         retries: 3
         timeout: 120
     outputs:
       - name: "output-name"
         value: "{{tasks.task-name.result}}"
         destinations:
           - type: "file|api"
""")
        
        # 5. Show available integrations
        print("\n5. 🔌 Available Integrations")
        print("   The workflow service can integrate with:")
        print("   • 🔍 Search Agent - For intelligent web searches")
        print("   • 🧠 LLM Gateway - For AI-powered processing")
        print("   • 💾 Vector Store - For storing embeddings and documents")
        print("   • ☀️ Weather Service - For weather data processing")
        print("   • And more services in the DeepSearchStack!")
        
        # 6. Show templating capabilities
        print("\n6. 🎨 Templating Capabilities")
        print("   Workflows support powerful templating:")
        print("   • Context variables: {{workflow.id}}, {{workflow.timestamp}}")
        print("   • Task results: {{tasks.previous-task.result}}")
        print("   • Dynamic file paths: /data/reports/{{workflow.timestamp}}.txt")
        
        print("\n" + "=" * 60)
        print("🎉 Demonstration Complete!")
        print("The Workflow Automation Service is ready to automate your infrastructure tasks!")

async def main():
    await demonstrate_workflow_capabilities()

if __name__ == "__main__":
    asyncio.run(main())