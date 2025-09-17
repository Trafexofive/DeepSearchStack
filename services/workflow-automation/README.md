# Workflow Automation Service

This service provides automated workflows that orchestrate tasks across the DeepSearchStack infrastructure.

## Features

- **Declarative Workflows**: Define complex automation workflows using YAML manifests
- **Cross-Service Orchestration**: Seamlessly integrate with Search Agent, LLM Gateway, Vector Store, and other services
- **Flexible Triggers**: Schedule workflows or trigger them via API
- **Templating**: Use context variables to pass data between tasks
- **Error Handling**: Configurable retries and timeouts for robust execution

## Workflow Manifest Schema

```yaml
apiVersion: automation.deeps/v1
kind: Workflow
metadata:
  name: workflow-name
  description: "Description of the workflow"
spec:
  triggers:
    - type: "schedule"
      cron: "0 * * * *"  # Hourly
    - type: "api"
      endpoint: "/trigger/workflow-name"
  tasks:
    - name: "task-name"
      type: "search|llm|storage|api"
      provider: "service-name"
      parameters:
        # Task-specific parameters
      conditions: {}
      retries: 3
      timeout: 120
      dependsOn: ["previous-task"]
  outputs:
    - name: "output-name"
      value: "{{tasks.task-name.result}}"
      destinations:
        - type: "file"
          path: "/data/output.txt"
        - type: "api"
          endpoint: "http://external-service/webhook"
```

## Available Workflows

1. **AI Research Summary** (`workflows/ai-research-summary.yaml`)
   - Searches for latest AI research
   - Summarizes findings using LLM
   - Stores results in vector database

2. **Weather Data Analysis** (`workflows/weather-analysis.yaml`)
   - Fetches weather data
   - Analyzes trends and patterns
   - Stores analysis results

## API Endpoints

- `GET /health` - Health check
- `POST /workflows/execute` - Execute a workflow from a manifest
- `GET /workflows/templates` - List available workflow templates

## Usage

### Start the service

```bash
make workflow-automation
```

### Execute a workflow via CLI

```bash
python scripts/workflow-cli.py execute workflows/ai-research-summary.yaml
```

### Execute a workflow via API

```bash
curl -X POST http://localhost:8005/workflows/execute \
  -H "Content-Type: application/json" \
  -d '{"manifest_path": "workflows/ai-research-summary.yaml"}'
```

## Environment Variables

- `SEARCH_AGENT_URL` - URL for the Search Agent service
- `LLM_GATEWAY_URL` - URL for the LLM Gateway service
- `VECTOR_STORE_URL` - URL for the Vector Store service