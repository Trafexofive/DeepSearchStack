import asyncio
import docker
import httpx
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.background import BackgroundTask

# ======================================================================================
# Configuration & State
# ======================================================================================

import os

# --- Environment-based Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

WORKER_IMAGE = os.getenv("WORKER_IMAGE", "ollama/ollama:latest")
WORKER_LABEL = "ollama-worker"
REQUIRED_MODEL = os.getenv("OLLAMA_DEFAULT_MODEL", "gemma:2b")
CHIMERA_NETWORK = os.getenv("CHIMERA_NETWORK", "chimera-net")

# --- Global State ---
# In a production system, this state would be managed in a more persistent store like Redis.
client = docker.from_env()
http_client: httpx.AsyncClient = None
workers = {}  # Stores worker_url -> container_name mapping
worker_states = {}  # Stores worker_url -> "IDLE" | "BUSY" | "PENDING"
lock = asyncio.Lock()
worker_available = asyncio.Condition(lock)

# ======================================================================================
# FastAPI Lifespan Management (for shared resources)
# ======================================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages the application's lifespan. Creates a shared httpx client on startup
    and closes it on shutdown.
    """
    global http_client
    logger.info("Application startup: Initializing shared HTTP client and discovering workers.")
    http_client = httpx.AsyncClient(timeout=900.0)
    await startup_discover_workers()
    yield
    logger.info("Application shutdown: Closing shared HTTP client.")
    await http_client.aclose()

app = FastAPI(lifespan=lifespan)

# ======================================================================================
# Worker Management & Health Checks
# ======================================================================================

async def is_worker_ready(worker_url: str):
    """
    Checks if a worker is truly ready by verifying its API is responsive and the
    required model is available.
    """
    try:
        response = await http_client.get(f"{worker_url}/api/tags")
        response.raise_for_status()
        models = response.json().get("models", [])
        # The default model used in the load test is gemma3:1b
        if any(model['name'].startswith(REQUIRED_MODEL) for model in models):
            logger.info(f"Health check PASSED for {worker_url}. Model '{REQUIRED_MODEL}' is available.")
            return True
        logger.warning(f"Health check for {worker_url}: API is up, but model '{REQUIRED_MODEL}' not found yet.")
        return False
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.warning(f"Health check FAILED for {worker_url}: {e}")
        return False

async def startup_discover_workers():
    """
    Discovers existing worker containers on startup and adds them to the pool if they are healthy.
    """
    async with lock:
        logger.info("Discovering existing worker containers...")
        for container in client.containers.list(filters={"label": WORKER_LABEL}):
            worker_url = f"http://{container.name}:11434"
            if worker_url not in workers:
                logger.info(f"Discovered existing worker: {container.name}")
                workers[worker_url] = container.name
                worker_states[worker_url] = "PENDING" # Assume pending until checked
                # Run health check in the background
                asyncio.create_task(monitor_pending_worker(worker_url))

async def monitor_pending_worker(worker_url: str):
    """
    Triggers a model pull on a new worker and then monitors it until it becomes
    ready, then sets its state to IDLE.
    """
    # First, trigger the pull command on the worker
    try:
        logger.info(f"Triggering model pull for {REQUIRED_MODEL} on {worker_url}...")
        response = await http_client.post(
            f"{worker_url}/api/pull",
            json={"name": REQUIRED_MODEL, "stream": False} # Use stream=False for a blocking pull
        )
        response.raise_for_status()
        logger.info(f"Model pull command for {worker_url} finished with status: {response.json().get('status')}")
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        logger.error(f"Failed to trigger model pull for {worker_url}: {e}")
        # Optional: handle failure, maybe remove the worker
        return

    # Now, monitor for readiness
    while True:
        if await is_worker_ready(worker_url):
            async with lock:
                worker_states[worker_url] = "IDLE"
                worker_available.notify_all()
                logger.info(f"Worker {worker_url} is now ready and set to IDLE.")
            break
        await asyncio.sleep(10)

async def get_idle_worker():
    """
    Gets an idle worker from the pool. If no workers are idle, it waits until one becomes available.
    This is a core part of the robust load balancing.
    """
    async with worker_available:
        while True:
            idle_workers = [url for url, state in worker_states.items() if state == "IDLE"]
            if idle_workers:
                worker_url = idle_workers[0]
                worker_states[worker_url] = "BUSY"
                logger.info(f"Found and assigned idle worker: {worker_url}")
                return worker_url
            
            logger.info("No idle workers available. Waiting for one to become free...")
            await worker_available.wait()

# ======================================================================================
# API Endpoints - Admin
# ======================================================================================

@app.post("/admin/instances/spawn")
async def spawn_instance():
    """
    Spawns a new Ollama worker container and monitors it until it's ready.
    Ensures old containers with the same name are removed first.
    """
    container_name = ""
    try:
        async with lock:
            # Find the highest existing worker number to avoid name collisions
            existing_numbers = []
            for container in client.containers.list(all=True, filters={"label": WORKER_LABEL}):
                try:
                    num = int(container.name.split('-')[-1])
                    existing_numbers.append(num)
                except (ValueError, IndexError):
                    continue
            
            next_num = max(existing_numbers) + 1 if existing_numbers else 1
            container_name = f"ollama-worker-{next_num}"

            logger.info(f"Attempting to spawn new instance: {container_name}")

            # Preemptively remove a container with the same name if it exists
            try:
                existing_container = client.containers.get(container_name)
                logger.warning(f"Container '{container_name}' already exists. Forcibly removing it before spawn.")
                existing_container.remove(force=True)
            except docker.errors.NotFound:
                pass # Container doesn't exist, which is the desired state

            container = client.containers.run(
                WORKER_IMAGE,
                detach=True,
                device_requests=[
                    docker.types.DeviceRequest(count=-1, capabilities=[['gpu']])
                ],
                labels={WORKER_LABEL: "true"},
                name=container_name,
                network=CHIMERA_NETWORK,
                volumes={'ollama-data': {'bind': '/root/.ollama', 'mode': 'rw'}},
                restart_policy={"Name": "unless-stopped"},
            )
            
            worker_url = f"http://{container_name}:11434"
            workers[worker_url] = container_name
            worker_states[worker_url] = "PENDING"
            
            asyncio.create_task(monitor_pending_worker(worker_url))

            return {
                "message": "New Ollama instance spawning. It will be added to the pool once ready.",
                "container_id": container.id,
                "container_name": container_name,
            }
    except docker.errors.APIError as e:
        logger.error(f"Docker API error during spawn for {container_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to spawn new instance '{container_name}': {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred during spawn for {container_name}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred while spawning '{container_name}': {e}")


@app.post("/admin/instances/prune")
async def prune_instances():
    """Stops and removes all Ollama worker containers, including stopped ones."""
    logger.info("Pruning all worker instances...")
    pruned_containers = []
    async with lock:
        # Use all=True to find all containers, not just running ones
        for container in client.containers.list(all=True, filters={"label": WORKER_LABEL}):
            try:
                logger.info(f"Stopping and removing container: {container.name} (ID: {container.id})")
                container.stop()
                # Use force=True to ensure removal even if the container is in a weird state
                container.remove(force=True)
                pruned_containers.append(container.name)
            except docker.errors.NotFound:
                logger.warning(f"Container {container.name} not found during prune, might have been already removed.")
            except docker.errors.APIError as e:
                logger.error(f"Failed to prune container {container.name}: {e}", exc_info=True)
        
        workers.clear()
        worker_states.clear()
        logger.info("All workers pruned. Worker list is now empty.")
    return {"message": "All worker instances have been pruned.", "pruned_containers": pruned_containers}

@app.get("/admin/instances")
async def list_instances():
    """Lists all active Ollama worker containers and their states."""
    async with lock:
        return {"workers": workers, "states": worker_states}

# ======================================================================================
# API Endpoints - Proxy
# ======================================================================================

async def stream_response_generator(response, worker_url):
    """
    Yields chunks from the streaming response and ensures the worker state is reset
    to IDLE in a finally block.
    """
    try:
        async for chunk in response.aiter_bytes():
            yield chunk
    finally:
        await response.aclose()
        logger.info(f"Worker response stream closed for {worker_url}.")
        async with worker_available:
            worker_states[worker_url] = "IDLE"
            worker_available.notify_all()
            logger.info(f"Worker {worker_url} state reset to IDLE.")

@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def reverse_proxy(request: Request, path: str):
    """
    Reverse proxies requests to an available Ollama worker, handling state management
    and streaming correctly.
    """
    worker_url = await get_idle_worker()
    
    try:
        url = f"{worker_url}/api/{path}"
        body = await request.body()
        
        logger.info(f"Proxying request for /api/{path} to worker: {worker_url}")
        
        req = http_client.build_request(
            method=request.method,
            url=url,
            headers=request.headers,
            content=body,
        )
        response = await http_client.send(req, stream=True)
        
        # The BackgroundTask will call the generator which handles resetting the worker state
        return StreamingResponse(
            stream_response_generator(response, worker_url),
            status_code=response.status_code,
            headers=response.headers,
        )

    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        logger.error(f"Error proxying to worker {worker_url}: {e}", exc_info=True)
        # If an error occurs, immediately reset the worker state and notify others
        async with worker_available:
            worker_states[worker_url] = "IDLE"
            worker_available.notify_all()
            logger.error(f"Worker {worker_url} state reset to IDLE due to proxy error.")
        
        status_code = e.response.status_code if isinstance(e, httpx.HTTPStatusError) else 502
        detail = e.response.text if isinstance(e, httpx.HTTPStatusError) else f"Error connecting to worker: {e}"
        raise HTTPException(status_code=status_code, detail=detail)
    except Exception as e:
        logger.error(f"Unexpected error in reverse proxy for worker {worker_url}: {e}", exc_info=True)
        async with worker_available:
            worker_states[worker_url] = "IDLE"
            worker_available.notify_all()
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred in the proxy: {e}")
