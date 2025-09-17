#!/bin/bash
# Test script for workflow automation service

echo "Testing Workflow Automation Service"

# Check if the service is running
echo "1. Checking service health..."
curl -f http://localhost:8005/health
if [ $? -ne 0 ]; then
    echo "Service is not healthy"
    exit 1
fi

echo ""
echo "2. Executing test workflow..."
# Execute the test workflow
curl -X POST http://localhost:8005/workflows/execute \
  -H "Content-Type: application/json" \
  -d '{"manifest_path": "workflows/test-workflow.yaml"}'

echo ""
echo "3. Done!"
