#!/bin/bash
# Test script that runs inside the workflow container

echo "🧪 Running Integration Test Inside Workflow Container"
echo "====================================================="

# Test service connectivity
echo ""
echo "1. Testing service connectivity..."
if curl -f -s http://search-agent:8001/health > /dev/null; then
    echo "   ✅ Search Agent reachable at http://search-agent:8001"
else
    echo "   ❌ Search Agent not reachable"
fi

if curl -f -s http://llm-gateway:8080/health > /dev/null; then
    echo "   ✅ LLM Gateway reachable at http://llm-gateway:8080"
else
    echo "   ❌ LLM Gateway not reachable"
fi

# Test workflow execution
echo ""
echo "2. Testing workflow execution..."
RESPONSE=$(curl -s -X POST http://localhost:8005/workflows/execute \
  -H "Content-Type: application/json" \
  -d '{"manifest_path": "workflows/real-llm-test.yaml"}')

if echo "$RESPONSE" | grep -q "workflow_id"; then
    echo "   ✅ Workflow executed successfully"
    WORKFLOW_ID=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['workflow_id'])")
    echo "   🆔 Workflow ID: $WORKFLOW_ID"
    
    # Check if the task succeeded
    if echo "$RESPONSE" | grep -q '"success":true'; then
        echo "   🎯 Task completed successfully"
    else
        echo "   ⚠️  Task may have failed, checking details..."
        echo "   📄 Response: $RESPONSE"
    fi
else
    echo "   ❌ Workflow execution failed"
    echo "   📄 Response: $RESPONSE"
fi

echo ""
echo "====================================================="
echo "🎉 Container-based integration test completed!"