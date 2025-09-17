#!/usr/bin/env python3
"""
CLI for Workflow Automation Service
"""
import argparse
import httpx
import json
import os
from pathlib import Path

BASE_URL = os.environ.get("WORKFLOW_SERVICE_URL", "http://localhost:8005")

async def execute_workflow(workflow_path: str):
    """Execute a workflow from a manifest file"""
    try:
        async with httpx.AsyncClient() as client:
            payload = {"manifest_path": workflow_path}
            response = await client.post(f"{BASE_URL}/workflows/execute", json=payload)
            response.raise_for_status()
            result = response.json()
            print(json.dumps(result, indent=2))
    except httpx.HTTPError as e:
        print(f"Error executing workflow: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

async def health_check():
    """Check service health"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{BASE_URL}/health")
            response.raise_for_status()
            result = response.json()
            print(json.dumps(result, indent=2))
    except httpx.HTTPError as e:
        print(f"Health check failed: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")

async def list_workflows():
    """List available workflow templates"""
    workflows_dir = Path(__file__).parent.parent / "workflows"
    if workflows_dir.exists():
        print("Available workflows:")
        for workflow_file in workflows_dir.glob("*.yaml"):
            print(f"  - {workflow_file.name}")
    else:
        print("No workflows directory found")

async def main():
    parser = argparse.ArgumentParser(description="Workflow Automation CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Execute command
    execute_parser = subparsers.add_parser("execute", help="Execute a workflow")
    execute_parser.add_argument("workflow", help="Path to workflow manifest")

    # Health command
    subparsers.add_parser("health", help="Check service health")

    # List command
    subparsers.add_parser("list", help="List available workflows")

    args = parser.parse_args()

    if args.command == "execute":
        await execute_workflow(args.workflow)
    elif args.command == "health":
        await health_check()
    elif args.command == "list":
        await list_workflows()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())