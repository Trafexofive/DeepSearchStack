"""Functional tests for the LLM API Gateway"""
import pytest
import httpx
import os

BASE_URL = os.environ.get("LLM_GATEWAY_URL", "http://localhost:8080")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

@pytest.mark.asyncio
async def test_health_check():
    """Test the /health endpoint"""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        response = await client.get("/health")
        assert response.status_code == 200, "Health check should return 200 OK"
        data = response.json()
        assert data["status"] == "healthy"
        assert "providers" in data

@pytest.mark.asyncio
async def test_list_providers():
    """Test the /providers endpoint"""
    async with httpx.AsyncClient(base_url=BASE_URL) as client:
        response = await client.get("/providers")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, dict)
        assert "ollama" in data, "Ollama provider should be listed"

@pytest.mark.asyncio
async def test_completion_with_ollama():
    """Test the /completion endpoint specifically with the Ollama provider."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=60.0) as client:
        payload = {
            "provider": "ollama",
            "messages": [{"role": "user", "content": "Why is the sky blue?"}],
            "temperature": 0.1
        }
        response = await client.post("/completion", json=payload)
        
        # This test now depends on the 'llama3' model being available in Ollama.
        # The new error handling in the provider will give a clear message if it's not.
        assert response.status_code == 200, f"Ollama request failed: {response.text}"
        data = response.json()
        assert "content" in data
        assert "blue" in data["content"].lower()
        assert data["provider_name"] == "ollama"

@pytest.mark.asyncio
@pytest.mark.skipif(not GROQ_API_KEY, reason="GROQ_API_KEY is not set")
async def test_completion_with_groq():
    """Test the /completion endpoint specifically with the Groq provider."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        payload = {
            "provider": "groq",
            "messages": [{"role": "user", "content": "What is the capital of France?"}],
            "temperature": 0.1
        }
        response = await client.post("/completion", json=payload)
        assert response.status_code == 200, f"Groq request failed: {response.text}"
        data = response.json()
        assert "content" in data
        assert "paris" in data["content"].lower()
        assert data["provider_name"] == "groq"

@pytest.mark.asyncio
@pytest.mark.skipif(not GEMINI_API_KEY, reason="GEMINI_API_KEY is not set")
async def test_completion_with_gemini():
    """Test the /completion endpoint specifically with the Gemini provider."""
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        payload = {
            "provider": "gemini",
            "messages": [{"role": "user", "content": "What is 2 + 2?"}],
            "temperature": 0.1
        }
        response = await client.post("/completion", json=payload)
        assert response.status_code == 200, f"Gemini request failed: {response.text}"
        data = response.json()
        assert "content" in data
        assert "4" in data["content"]
        assert data["provider_name"] == "gemini"
