
import pytest
import pytest_asyncio
import httpx
import os

# --- Test Configuration ---
# URLs point to the reverse proxy
LLM_GATEWAY_URL = os.environ.get("LLM_GATEWAY_URL", "http://localhost/llm")
WEB_API_URL = os.environ.get("WEB_API_URL", "http://localhost/")

# Use a provider that is likely to be configured and available
# The test will gracefully skip if no paid providers are configured.
TEST_PROVIDER = "gemini" if os.environ.get("GEMINI_API_KEY") else "groq"
API_KEY_CONFIGURED = bool(os.environ.get("GEMINI_API_KEY") or os.environ.get("GROQ_API_KEY"))

# --- Pytest Fixtures ---

@pytest_asyncio.fixture(scope="module")
async def http_client():
    """Module-scoped async HTTP client."""
    async with httpx.AsyncClient(timeout=45.0) as client:
        yield client

# --- Test Suite ---

@pytest.mark.asyncio
class TestGatewaySuite:
    """Focused tests for the LLM and Web-API gateways."""

    # -- LLM Gateway Tests --

    async def test_llm_gateway_health(self, http_client: httpx.AsyncClient):
        """Checks if the LLM Gateway's health endpoint is responsive."""
        response = await http_client.get(f"{LLM_GATEWAY_URL}/health")
        assert response.status_code == 200, "LLM Gateway /health should return 200 OK"
        data = response.json()
        assert data["status"] == "healthy"
        assert "active_providers" in data

    async def test_llm_gateway_list_providers(self, http_client: httpx.AsyncClient):
        """Checks if the LLM Gateway can list its available providers."""
        response = await http_client.get(f"{LLM_GATEWAY_URL}/providers")
        assert response.status_code == 200, "LLM Gateway /providers should return 200 OK"
        data = response.json()
        assert isinstance(data, dict)
        assert "ollama" in data, "Ollama should always be a listed provider"

    @pytest.mark.skipif(not API_KEY_CONFIGURED, reason="No paid API keys (GEMINI or GROQ) are configured")
    async def test_llm_gateway_completion(self, http_client: httpx.AsyncClient):
        """Performs a simple, non-streaming completion request."""
        payload = {
            "provider": TEST_PROVIDER,
            "messages": [{"role": "user", "content": "What is 1 + 1?"}],
            "stream": False
        }
        response = await http_client.post(f"{LLM_GATEWAY_URL}/completion", json=payload)
        assert response.status_code == 200, f"Completion request failed: {response.text}"
        data = response.json()
        assert "content" in data
        assert data["provider_name"] == TEST_PROVIDER
        assert "2" in data["content"] or "two" in data["content"].lower()

    # -- Web API Gateway Tests --

    async def test_web_api_gateway_health(self, http_client: httpx.AsyncClient):
        """Checks if the Web API gateway (frontend proxy) is running."""
        response = await http_client.get(f"{WEB_API_URL}")
        # The web-api root endpoint proxies to the frontend, which should return 200 OK
        assert response.status_code == 200, "Web API root should be accessible"
        # Check for some text that should be in the Next.js app
        assert "DeepSearchStack" in response.text
