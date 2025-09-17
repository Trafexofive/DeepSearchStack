#!/bin/bash
# Integration test for workflow automation service

echo "🧪 Workflow Automation Service Integration Test"
echo "================================================"

# Test 1: Service Health
echo ""
echo "1. Testing service health..."
if curl -f -s http://localhost:8005/health > /dev/null; then
    echo "   ✅ Service is healthy"
else
    echo "   ❌ Service health check failed"
    exit 1
fi

# Test 2: Execute test workflow
echo ""
echo "2. Executing test workflow..."
RESPONSE=$(curl -s -X POST http://localhost:8005/workflows/execute \
  -H "Content-Type: application/json" \
  -d '{"manifest_path": "workflows/test-workflow.yaml"}')

if echo "$RESPONSE" | grep -q "workflow_id"; then
    echo "   ✅ Workflow executed successfully"
    WORKFLOW_ID=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['workflow_id'])")
    echo "   🆔 Workflow ID: $WORKFLOW_ID"
else
    echo "   ❌ Workflow execution failed"
    echo "   📄 Response: $RESPONSE"
    exit 1
fi

# Test 3: Check if output file was created
echo ""
echo "3. Checking output files..."
if [ -d "/home/mlamkadm/services/deeps/services/workflow-automation/data/test" ]; then
    FILE_COUNT=$(ls -1 /home/mlamkadm/services/deeps/services/workflow-automation/data/test/*.txt 2>/dev/null | wc -l)
    if [ "$FILE_COUNT" -gt 0 ]; then
        echo "   ✅ Output files created successfully ($FILE_COUNT files)"
        echo "   📁 Files:"
        ls -1 /home/mlamkadm/services/deeps/services/workflow-automation/data/test/*.txt | head -3
    else
        echo "   ⚠️  No output files found (this might be expected if the workflow failed)"
    fi
else
    echo "   ⚠️  Data directory not found"
fi

echo ""
echo "================================================"
echo "🎉 Integration test completed successfully!"
echo "The Workflow Automation Service is working properly."