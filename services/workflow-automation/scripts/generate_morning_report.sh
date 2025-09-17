#!/bin/bash
# Generate Daily Morning Report

echo "🌅 Generating Daily Morning Report"
echo "================================="

# Trigger the workflow
echo "🚀 Triggering morning report workflow..."
RESPONSE=$(curl -s -X POST http://localhost:8005/workflows/execute \
  -H "Content-Type: application/json" \
  -d '{"manifest_path": "workflows/daily-morning-report.yaml"}')

# Check if workflow executed successfully
if echo "$RESPONSE" | grep -q '"status":"completed"'; then
    echo "✅ Workflow completed successfully!"
    
    # Extract workflow ID
    WORKFLOW_ID=$(echo "$RESPONSE" | python3 -c "
import sys, json
data = json.load(sys.stdin)
print(data.get('workflow_id', 'unknown'))
")
    echo "📝 Workflow ID: $WORKFLOW_ID"
    
    # Check if the final task succeeded
    if echo "$RESPONSE" | grep -q '"compile-morning-report".*"success":true'; then
        echo "🏆 Report compilation successful!"
        
        # Show where the report is saved
        TIMESTAMP=$(date +%Y%m%d-%H%M%S)
        echo "📄 Report saved to: /data/reports/morning-report-$TIMESTAMP.md"
        echo "📋 Latest report: /data/reports/latest-morning-report.md"
        
        # Display a preview of the report
        echo ""
        echo "📋 Report Preview:"
        echo "=================="
        docker exec workflow-automation-1 cat /data/reports/latest-morning-report.md | head -20
        
        echo ""
        echo "🎉 Daily Morning Report Generated Successfully!"
        echo "   Run 'docker exec workflow-automation-1 cat /data/reports/latest-morning-report.md' to view the full report."
    else
        echo "⚠️  Report compilation failed. Checking task statuses:"
        echo "$RESPONSE" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for task_name, task_data in data.get('tasks', {}).items():
    status = '✅ SUCCESS' if task_data.get('success') else '❌ FAILED'
    print(f'  {status} Task: {task_name}')
"
    fi
else
    echo "❌ Workflow failed to complete"
    echo "📄 Error details:"
    echo "$RESPONSE" | python3 -m json.tool
fi