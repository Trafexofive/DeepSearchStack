#!/bin/bash
# Test runner for workflow automation service

echo "🧪 Running Unit Tests for Workflow Automation Service"

# Run unit tests
cd /home/mlamkadm/services/deeps/services/workflow-automation
python -m pytest tests/ -v

echo ""
echo "🏁 Unit tests completed"