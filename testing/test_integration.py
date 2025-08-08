"""
DeepSearchStack - Comprehensive Integration Test Suite v2.5 (Production Ready)

This suite runs against a live, containerized stack and validates that all
services are healthy, communicating correctly, and that the core logic
(search, synthesis, provider fallback) is working as expected.

v2.5 Fix: Makes the health check helper function significantly more patient
and provides more detailed logging to gracefully handle slow-starting
services like YaCy.
"""

import pytest
import pytest_asyncio
import httpx
import os
import asyncio

# --- Configuration ---
BASE_URL = os.environ.get("BASE_URL", "http://localhost")
LLM_GATEWAY_URL = f"{BASE_URL}/llm"
SEARCH_AGENT_URL = f"{BASE_URL}/agent"
WEB_API_URL = f"{BASE_URL}/"
SEARXNG_URL = f"{BASE_URL}/searxng/"
WHOOGLE_URL = f"{BASE_URL}/whoogle/"
YACY_URL = f"{BASE_URL}/yacy"

# API keys and feature flags
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
ENABLE_GROQ = os.environ.get("ENABLE_GROQ", "false").lower() == 'true'
ENABLE_GEMINI = os.environ.get("ENABLE_GEMINI", "false").lower() == 'true'
OLLAMA_MODEL_TO_TEST = os.environ.get("OLLAMA_DEFAULT_MODEL", "llama3")

# Timeouts
API_TIMEOUT = 120

# --- Pytest Fixtures and Helpers ---

@pytest_asyncio.fixture(scope="function")
async def http_client():
    """Function-scoped async HTTP client for test isolation."""
    async with httpx.AsyncClient(timeout=API_TIMEOUT) as client:
        yield client

async def await_service_ready(
    client: httpx.AsyncClient, 
    service_name: str, 
    url: str, 
    expected_code: int = 200,
    retries: int = 40,      # Increased default retries
    delay: int = 8          # Increased default delay
):
    """Retries a health check with detailed logging until the service is ready or times out."""
    print(f"Waiting for {service_name} at {url}...")
    for i in range(retries):
        try:
            response = await client.get(url, timeout=15, follow_redirects=True)
            if response.status_code == expected_code:
                print(f"✅ {service_name} is healthy (Status: {response.status_code})")
                return
            else:
                print(f"Attempt {i+1}/{retries} for {service_name}: Got status {response.status_code}, expected {expected_code}. Retrying in {delay}s...")
        except httpx.RequestError as e:
            print(f"Attempt {i+1}/{retries} for {service_name}: Request failed ({e}). Retrying in {delay}s...")
        
        await asyncio.sleep(delay)
    
    pytest.fail(f"❌ {service_name} at {url} was not ready after {retries} attempts.")


# --- Test Suite Class ---

@pytest.mark.asyncio
class TestIntegrationSuite:
    """A single class for all integration tests with explicit dependencies."""

    # --- Health Checks (must pass first) ---
    @pytest.mark.dependency(name="health_web_api")
    async def test_health_web_api(self, http_client: httpx.AsyncClient):
        await await_service_ready(http_client, "Web API", WEB_API_URL, 200)

    @pytest.mark.dependency(name="health_llm_gateway")
    async def test_health_llm_gateway(self, http_client: httpx.AsyncClient):
        await await_service_ready(http_client, "LLM Gateway", f"{LLM_GATEWAY_URL}/health", 200)

    @pytest.mark.dependency(name="health_search_agent")
    async def test_health_search_agent(self, http_client: httpx.AsyncClient):
        await await_service_ready(http_client, "Search Agent", f"{SEARCH_AGENT_URL}/health", 200)

    @pytest.mark.dependency(name="health_searxng")
    async def test_health_searxng(self, http_client: httpx.AsyncClient):
        await await_service_ready(http_client, "SearXNG", SEARXNG_URL, 200)

    @pytest.mark.dependency(name="health_whoogle")
    async def test_health_whoogle(self, http_client: httpx.AsyncClient):
        await await_service_ready(http_client, "Whoogle", WHOOGLE_URL, 200)

    @pytest.mark.dependency(name="health_yacy")
    async def test_health_yacy(self, http_client: httpx.AsyncClient):
        # Give YaCy an exceptionally long time to start up if needed
        await await_service_ready(
            http_client, 
            "YaCy API", 
            f"{YACY_URL}/api/status.json", 
            200
        )

    # --- LLM Gateway Logic Tests (depend on gateway health) ---
    @pytest.mark.dependency(depends=["health_llm_gateway"])
    async def test_llm_list_providers(self, http_client: httpx.AsyncClient):
        response = await http_client.get(f"{LLM_GATEWAY_URL}/providers")
        assert response.status_code == 200
        data = response.json()
        assert "ollama" in data and data["ollama"]["available"] is True

    @pytest.mark.dependency(depends=["health_llm_gateway"])
    async def test_llm_completion_ollama(self, http_client: httpx.AsyncClient):
        payload = {"provider": "ollama", "messages": [{"role": "user", "content": "Briefly, why is the sky blue?"}]}
        response = await http_client.post(f"{LLM_GATEWAY_URL}/completion", json=payload)
        assert response.status_code == 200, f"Request failed: {response.text}"
        data = response.json()
        assert data["provider_name"] == "ollama" and data["model"] == OLLAMA_MODEL_TO_TEST

    @pytest.mark.dependency(depends=["health_llm_gateway"])
    @pytest.mark.skipif(not (GROQ_API_KEY and ENABLE_GROQ), reason="Groq not enabled or API key not set")
    async def test_llm_completion_groq(self, http_client: httpx.AsyncClient):
        payload = {"provider": "groq", "messages": [{"role": "user", "content": "Capital of France?"}]}
        response = await http_client.post(f"{LLM_GATEWAY_URL}/completion", json=payload)
        assert response.status_code == 200 and "paris" in response.json()["content"].lower()
    
    # --- Search Agent Logic Tests (depend on agent and llm gateway health) ---
    @pytest.mark.dependency(depends=["health_search_agent", "health_llm_gateway"])
    async def test_search_agent_e2e_success(self, http_client: httpx.AsyncClient):
        payload = {"query": "What are the latest developments in AI?"}
        response = await http_client.post(f"{SEARCH_AGENT_URL}/search", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert "answer" in data and len(data["answer"]) > 20
        assert "sources" in data and len(data["sources"]) > 0
