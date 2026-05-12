# Chimera - Ollama API Server & Worker Fleet

**Forged by Gemini in accordance with the Himothy Covenant.**

This repository contains a highly scalable, resilient, and GPU-accelerated environment for serving Ollama models. It provides a load-balancing API gateway that dynamically spawns and manages a fleet of Ollama worker instances, distributing requests among them.

## I. The Architecture of the Forge

The system is comprised of two core components:

1.  **The Ollama Server (`ollama-server`):** A primary, standalone Ollama instance. While it can be used directly, its main purpose in this stack is to serve as the base image for the worker fleet.

2.  **The API Gateway (`api-gateway`):** The heart of the Chimera stack. This FastAPI application acts as both a reverse proxy and a worker orchestrator. It exposes the Ollama API while intelligently managing a fleet of dynamically spawned worker containers in the background.

### Key Features:

-   **Dynamic Worker Scaling:** The gateway can spawn and prune worker instances via a simple API call.
-   **GPU Acceleration:** All workers are automatically configured to leverage available NVIDIA GPUs for maximum performance.
-   **Robust Load Balancing:** Requests are distributed across available `IDLE` workers. If all workers are busy, requests are queued until a worker becomes available.
-   **Automatic Model Caching:** The required models are pulled automatically by workers upon startup, ensuring they are ready for inference.
-   **Resilience:** The gateway is designed to handle worker failures, removing them from the pool and ensuring the system remains operational.

## II. The Forging Process (Deployment)

All commands are executed via the Master Control Program (`Makefile`).

### Prerequisites

-   Docker & Docker Compose
-   NVIDIA Container Toolkit (for GPU acceleration)

### 1. Ignite the Chimera Stack

This single command will build all necessary images and start both the primary Ollama server and the API Gateway.

```bash
make start-all
```

### 2. Verify System Status

To check the status of the running services:

```bash
make status
```

You should see both `ollama-server` and `api-gateway` running.

## III. Configuration

All configuration is managed via the `.env` file in the root of the project. A documented example is provided in `.env.example`.

**Key Configuration Variables:**

*   `GATEWAY_PORT`: The external port for the API Gateway.
*   `FRONTEND_PORT`: The external port for the Chimera Frontend.
*   `OLLAMA_PORT`: The internal port for the main Ollama server.
*   `REQUIRED_MODEL`: The default model that workers will download to be considered "ready".
*   `WORKER_IMAGE`: The base image for the dynamically spawned workers.
*   `CHIMERA_NETWORK`: The name of the Docker network.
*   `NEXTAUTH_SECRET`: A secret key for signing authentication tokens.
*   `NEXTAUTH_URL`: The public URL of your application.
*   `DATABASE_URL`: The connection string for your database.

## V. Reverse Proxy

The stack now includes a Traefik reverse proxy that acts as the single entrypoint for all external traffic. It routes requests to the appropriate services.

**Key Features:**

*   **Dynamic Routing:** Traefik automatically discovers and routes traffic to the `api-gateway` and `chimera-frontend` services.

**Configuration:**

*   `TRAEFIK_API_DOMAIN`: The domain for the API Gateway.
*   `TRAEFIK_FRONTEND_DOMAIN`: The domain for the Chimera Frontend.

## VI. Interacting with the Oracle (Usage)

All interaction with the Ollama models should be directed to the **API Gateway** on port `8000`.

### Spawning and Pruning Workers

The gateway exposes administrative endpoints for managing the worker fleet.

-   **Spawn a new worker:**

    ```bash
    curl -X POST http://localhost:8000/admin/instances/spawn
    ```

-   **Prune all workers:**

    ```bash
    curl -X POST http://localhost:8000/admin/instances/prune
    ```

-   **List all workers and their states:**

    ```bash
    curl http://localhost:8000/admin/instances
    ```

### Sending Inference Requests

Use the standard Ollama API endpoints, but target the gateway. The included `client.sh` script is pre-configured to do this.

```bash
# Ensure the client is executable
chmod +x client.sh

# List available models (will be pulled by workers as needed)
./client.sh list

# Run a generation task
./client.sh generate --prompt "Explain the significance of the Himothy Covenant."
```

## IV. The Trials of the Forge (Testing)

This repository includes comprehensive test suites to validate the functionality of the entire stack.

-   **Client Test Suite:** Runs a series of commands using `client.sh` to test various Ollama functionalities through the gateway.

    ```bash
    make test-client
    ```

-   **Gateway & Worker Lifecycle Test:** A more advanced test that simulates a real-world scenario: it spawns multiple workers and immediately fires concurrent requests, testing the gateway's queueing and load-balancing capabilities.

    ```bash
    make test-gateway
    ```

## V. The Covenant of Pragmatic Purity

-   **Modularity:** The `ollama-base` Dockerfile now correctly copies the `entrypoint.sh` script from `infra/ollama-base/entrypoint.sh`.
-   **Clarity:** The `Makefile` provides a single, self-documenting interface for managing the stack.
-   **Control:** You have absolute control over the entire system. No black boxes.
