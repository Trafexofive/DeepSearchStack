# Adding LLM API Gateway to Deep Search Agent Stack

I'll design a flexible API gateway for integrating various LLM providers (focusing on free options) into your deep search stack.

## Architecture Update

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Web UI/API    │    │  Search Agent   │    │  Data Pipeline  │
│   (FastAPI)     │◄──►│   (C++/Python)  │◄──►│   (C++/Bash)    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   PostgreSQL    │    │  Vector Store   │    │  Search Index   │
│   (Metadata)    │    │   (Chroma/      │    │   (Xapian/      │
│                 │    │   Custom)       │    │   Lucene++)     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                │
                                ▼
                       ┌─────────────────┐
                       │    LLM API      │
                       │    Gateway      │◄──── New Component
                       └─────────────────┘
                                │
                                ▼
                 ┌───────────────────────────────┐
                 │                               │
        ┌────────┴───────┐  ┌───────────┐  ┌────┴────────┐
        │  Gemini API    │  │ Groq API  │  │ Ollama API  │
        │  (Google)      │  │           │  │ (Local)     │
        └────────────────┘  └───────────┘  └─────────────┘
```

## LLM API Gateway Implementation

Let's create this component:

```python name=llm_gateway/provider_base.py
"""Base class for LLM providers"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel

class Message(BaseModel):
    role: str  # "system", "user", "assistant"
    content: str

class CompletionRequest(BaseModel):
    messages: List[Message]
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    top_p: float = 1.0
    stream: bool = False

class CompletionResponse(BaseModel):
    content: str
    provider_name: str
    model: str
    usage: Dict[str, int] = {}
    raw_response: Optional[Dict] = None

class LLMProvider(ABC):
    """Base class for all LLM providers"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key
    
    @abstractmethod
    async def get_completion(self, request: CompletionRequest) -> CompletionResponse:
        """Get completion from the LLM provider"""
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        """Get the name of the provider"""
        pass
    
    @abstractmethod
    def get_available_models(self) -> List[str]:
        """Get list of available models from this provider"""
        pass
    
    def is_available(self) -> bool:
        """Check if the provider is available and configured correctly"""
        try:
            models = self.get_available_models()
            return len(models) > 0
        except:
            return False
```

```python name=llm_gateway/providers/gemini_provider.py
"""Google Gemini API Provider"""
import google.generativeai as genai
import os
from typing import Dict, List, Optional, Any
from ..provider_base import LLMProvider, CompletionRequest, CompletionResponse

class GeminiProvider(LLMProvider):
    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("Gemini API key is required")
        
        genai.configure(api_key=self.api_key)
        self.models = {
            "gemini-1.0-pro": genai.GenerativeModel('gemini-1.0-pro'),
            "gemini-1.5-pro": genai.GenerativeModel('gemini-1.5-pro'),
        }
    
    async def get_completion(self, request: CompletionRequest) -> CompletionResponse:
        model_name = "gemini-1.5-pro"  # Default to the latest model
        model = self.models[model_name]
        
        # Convert messages to Gemini format
        gemini_messages = []
        for msg in request.messages:
            # Handle system message as a user message for Gemini
            if msg.role == "system":
                gemini_messages.append({"role": "user", "parts": [msg.content]})
                gemini_messages.append({"role": "model", "parts": ["I'll help you with that."]})
            else:
                role = "user" if msg.role == "user" else "model"
                gemini_messages.append({"role": role, "parts": [msg.content]})
        
        # Generate response
        generation_config = {
            "temperature": request.temperature,
            "top_p": request.top_p,
            "max_output_tokens": request.max_tokens if request.max_tokens else 1024
        }
        
        response = model.generate_content(
            gemini_messages,
            generation_config=generation_config,
            stream=request.stream
        )
        
        if request.stream:
            # Collect stream response
            content = ""
            for chunk in response:
                if chunk.text:
                    content += chunk.text
            return CompletionResponse(
                content=content,
                provider_name="gemini",
                model=model_name,
                usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            )
        else:
            return CompletionResponse(
                content=response.text,
                provider_name="gemini",
                model=model_name,
                usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            )
    
    def get_name(self) -> str:
        return "gemini"
    
    def get_available_models(self) -> List[str]:
        return list(self.models.keys())
```

```python name=llm_gateway/providers/groq_provider.py
"""Groq API Provider"""
import os
import httpx
from typing import Dict, List, Optional, Any
from ..provider_base import LLMProvider, CompletionRequest, CompletionResponse

class GroqProvider(LLMProvider):
    def __init__(self, api_key: Optional[str] = None):
        super().__init__(api_key)
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError("Groq API key is required")
        
        self.base_url = "https://api.groq.com/openai/v1"
        self.available_models = [
            "llama3-8b-8192",
            "mixtral-8x7b-32768",
            "gemma-7b-it"
        ]
    
    async def get_completion(self, request: CompletionRequest) -> CompletionResponse:
        model_name = "llama3-8b-8192"  # Default model
        
        # Convert to OpenAI format (which Groq uses)
        messages = [{"role": msg.role, "content": msg.content} for msg in request.messages]
        
        # Prepare request
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens if request.max_tokens else 1024,
            "top_p": request.top_p,
            "stream": request.stream
        }
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        async with httpx.AsyncClient() as client:
            if not request.stream:
                response = await client.post(
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers
                )
                response_data = response.json()
                
                return CompletionResponse(
                    content=response_data["choices"][0]["message"]["content"],
                    provider_name="groq",
                    model=model_name,
                    usage=response_data.get("usage", {}),
                    raw_response=response_data
                )
            else:
                # Handle streaming
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    json=payload,
                    headers=headers
                ) as response:
                    content = ""
                    async for chunk in response.aiter_lines():
                        if chunk.startswith("data:"):
                            data = chunk[5:].strip()
                            if data == "[DONE]":
                                break
                            # Parse JSON chunk
                            try:
                                import json
                                data = json.loads(data)
                                if data["choices"][0]["delta"].get("content"):
                                    content += data["choices"][0]["delta"]["content"]
                            except Exception:
                                pass
                    
                    return CompletionResponse(
                        content=content,
                        provider_name="groq",
                        model=model_name,
                        usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                    )
    
    def get_name(self) -> str:
        return "groq"
    
    def get_available_models(self) -> List[str]:
        return self.available_models
```

```python name=llm_gateway/providers/ollama_provider.py
"""Ollama API Provider"""
import os
import httpx
from typing import Dict, List, Optional, Any
from ..provider_base import LLMProvider, CompletionRequest, CompletionResponse

class OllamaProvider(LLMProvider):
    def __init__(self, base_url: Optional[str] = None):
        super().__init__(api_key=None)  # Ollama doesn't need an API key
        self.base_url = base_url or os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        self._available_models = None
    
    async def get_completion(self, request: CompletionRequest) -> CompletionResponse:
        model_name = "llama3" # Default model
        
        # Format messages for Ollama
        prompt = ""
        for msg in request.messages:
            if msg.role == "system":
                prompt += f"<|system|>\n{msg.content}\n"
            elif msg.role == "user":
                prompt += f"<|user|>\n{msg.content}\n"
            elif msg.role == "assistant":
                prompt += f"<|assistant|>\n{msg.content}\n"
        
        prompt += "<|assistant|>\n"
        
        # Prepare request
        payload = {
            "model": model_name,
            "prompt": prompt,
            "temperature": request.temperature,
            "top_p": request.top_p,
            "stream": request.stream
        }
        
        if request.max_tokens:
            payload["max_tokens"] = request.max_tokens
        
        async with httpx.AsyncClient() as client:
            if not request.stream:
                response = await client.post(
                    f"{self.base_url}/api/generate",
                    json=payload
                )
                response_data = response.json()
                
                return CompletionResponse(
                    content=response_data["response"],
                    provider_name="ollama",
                    model=model_name,
                    usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                    raw_response=response_data
                )
            else:
                # Handle streaming
                async with client.stream(
                    "POST",
                    f"{self.base_url}/api/generate",
                    json=payload
                ) as response:
                    content = ""
                    async for chunk in response.aiter_lines():
                        try:
                            import json
                            data = json.loads(chunk)
                            if "response" in data:
                                content += data["response"]
                        except Exception:
                            pass
                    
                    return CompletionResponse(
                        content=content,
                        provider_name="ollama",
                        model=model_name,
                        usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
                    )
    
    async def fetch_available_models(self) -> List[str]:
        """Fetch available models from Ollama API"""
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"{self.base_url}/api/tags")
                data = response.json()
                return [model["name"] for model in data["models"]]
        except Exception:
            return ["llama3", "codellama", "mistral"]
    
    def get_name(self) -> str:
        return "ollama"
    
    def get_available_models(self) -> List[str]:
        if not self._available_models:
            import asyncio
            self._available_models = asyncio.run(self.fetch_available_models())
        return self._available_models
```

```python name=llm_gateway/api_gateway.py
"""LLM API Gateway - Unified interface for multiple LLM providers"""
import os
import logging
from typing import Dict, List, Optional, Any, Union
from fastapi import FastAPI, HTTPException, Depends, Request
from pydantic import BaseModel
import asyncio
import time
import random

from .provider_base import LLMProvider, CompletionRequest, CompletionResponse, Message
from .providers.gemini_provider import GeminiProvider
from .providers.groq_provider import GroqProvider
from .providers.ollama_provider import OllamaProvider

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="LLM API Gateway", description="Unified API for multiple LLM providers")

# Initialize providers
providers: Dict[str, LLMProvider] = {}

async def initialize_providers():
    """Initialize all available LLM providers"""
    # Gemini (Google)
    try:
        if os.environ.get("GEMINI_API_KEY"):
            providers["gemini"] = GeminiProvider()
            logger.info("Gemini provider initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize Gemini provider: {e}")
    
    # Groq
    try:
        if os.environ.get("GROQ_API_KEY"):
            providers["groq"] = GroqProvider()
            logger.info("Groq provider initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize Groq provider: {e}")
    
    # Ollama
    try:
        providers["ollama"] = OllamaProvider()
        logger.info("Ollama provider initialized")
    except Exception as e:
        logger.warning(f"Failed to initialize Ollama provider: {e}")

@app.on_event("startup")
async def startup_event():
    await initialize_providers()

class CompletionRequestAPI(BaseModel):
    """API request for completion"""
    provider: Optional[str] = None  # If None, gateway will select best available
    model: Optional[str] = None
    messages: List[Message]
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    top_p: float = 1.0
    stream: bool = False
    fallback: bool = True  # Whether to try another provider if first one fails

@app.get("/providers", tags=["Gateway"])
async def list_providers():
    """Get list of available LLM providers"""
    result = {}
    for name, provider in providers.items():
        try:
            result[name] = {
                "available": True,
                "models": provider.get_available_models()
            }
        except Exception as e:
            result[name] = {
                "available": False,
                "error": str(e)
            }
    return result

@app.post("/completion", tags=["LLM"], response_model=CompletionResponse)
async def get_completion(request: CompletionRequestAPI):
    """Get completion from specified LLM provider"""
    if not providers:
        raise HTTPException(status_code=503, detail="No LLM providers available")
    
    # Select provider
    provider_name = request.provider
    if not provider_name:
        # Auto-select available provider
        available_providers = [name for name, provider in providers.items() 
                              if provider.is_available()]
        if not available_providers:
            raise HTTPException(status_code=503, detail="No LLM providers available")
        provider_name = random.choice(available_providers)
    
    if provider_name not in providers:
        raise HTTPException(status_code=404, detail=f"Provider {provider_name} not found")
    
    provider = providers[provider_name]
    try:
        # Convert API request to provider request
        provider_request = CompletionRequest(
            messages=request.messages,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            top_p=request.top_p,
            stream=request.stream
        )
        
        start_time = time.time()
        response = await provider.get_completion(provider_request)
        end_time = time.time()
        
        logger.info(f"Completion from {provider_name} took {end_time - start_time:.2f} seconds")
        return response
    
    except Exception as e:
        logger.error(f"Error from provider {provider_name}: {e}")
        if request.fallback:
            # Try another provider
            fallback_providers = [name for name in providers.keys() 
                                if name != provider_name and providers[name].is_available()]
            if fallback_providers:
                fallback_name = random.choice(fallback_providers)
                logger.info(f"Falling back to provider: {fallback_name}")
                try:
                    return await providers[fallback_name].get_completion(provider_request)
                except Exception as fallback_e:
                    raise HTTPException(status_code=500, 
                                      detail=f"Primary provider ({provider_name}) error: {e}. "
                                            f"Fallback provider ({fallback_name}) error: {fallback_e}")
        
        raise HTTPException(status_code=500, detail=f"Provider error: {str(e)}")

@app.get("/health", tags=["Gateway"])
async def health_check():
    """Check health of the LLM API Gateway"""
    return {
        "status": "healthy",
        "providers": {name: provider.is_available() for name, provider in providers.items()},
        "timestamp": time.time()
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
```

```dockerfile name=llm_gateway/Dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Expose port
EXPOSE 8080

# Run the application
CMD ["uvicorn", "api_gateway:app", "--host", "0.0.0.0", "--port", "8080"]
```

```text name=llm_gateway/requirements.txt
fastapi==0.104.1
uvicorn==0.23.2
httpx==0.25.0
pydantic==2.4.2
google-generativeai==0.2.0
python-dotenv==1.0.0
```

## Adding to Docker Compose

Update your Docker Compose configuration:

```yaml name=docker-compose.yml
version: '3.8'

services:
  # Existing services...
  
  llm-gateway:
    build: ./llm_gateway
    ports:
      - "8080:8080"
    environment:
      - GEMINI_API_KEY=${GEMINI_API_KEY}
      - GROQ_API_KEY=${GROQ_API_KEY}
      - OLLAMA_BASE_URL=http://ollama:11434
    depends_on:
      - ollama
  
  ollama:
    image: ollama/ollama:latest
    volumes:
      - ollama_data:/root/.ollama
    ports:
      - "11434:11434"

volumes:
  # Existing volumes...
  ollama_data:
```

## Environment Configuration

```dotenv name=.env.example
# LLM API Keys
GEMINI_API_KEY=your_gemini_api_key
GROQ_API_KEY=your_groq_api_key

# Optional - Ollama configuration
OLLAMA_BASE_URL=http://ollama:11434
```

## Integration with Search Agent

```python name=search-agent/llm_client.py
"""LLM Client for the Search Agent"""
import os
import httpx
from typing import List, Dict, Any, Optional

class LLMClient:
    """Client to interact with the LLM API Gateway"""
    
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or os.environ.get("LLM_GATEWAY_URL", "http://llm-gateway:8080")
    
    async def get_completion(self, 
                           messages: List[Dict[str, str]], 
                           provider: Optional[str] = None,
                           temperature: float = 0.7) -> str:
        """Get completion from LLM Gateway"""
        payload = {
            "provider": provider,
            "messages": messages,
            "temperature": temperature,
            "fallback": True
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{self.base_url}/completion", json=payload)
            if response.status_code != 200:
                raise Exception(f"LLM Gateway error: {response.text}")
            
            result = response.json()
            return result["content"]
    
    async def get_available_providers(self) -> Dict[str, Any]:
        """Get available LLM providers"""
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.base_url}/providers")
            if response.status_code != 200:
                raise Exception(f"LLM Gateway error: {response.text}")
            
            return response.json()
```

## Usage Examples

```python name=examples/query_llm.py
"""Example of using the LLM Gateway"""
import asyncio
import os
import sys
import httpx

async def query_llm():
    """Query the LLM Gateway"""
    base_url = os.environ.get("LLM_GATEWAY_URL", "http://localhost:8080")
    
    # List available providers
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{base_url}/providers")
        providers = response.json()
        print("Available providers:")
        print(providers)
        
        # Query using the first available provider
        payload = {
            "messages": [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "What are the key benefits of self-hosted search engines?"}
            ],
            "temperature": 0.7,
            "fallback": True
        }
        
        response = await client.post(f"{base_url}/completion", json=payload)
        result = response.json()
        
        print("\nResponse from LLM:")
        print(f"Provider: {result['provider_name']}")
        print(f"Model: {result['model']}")
        print(f"Content: {result['content']}")

if __name__ == "__main__":
    asyncio.run(query_llm())
```

This LLM API Gateway handles multiple free LLM providers with:

1. **Unified API**: Consistent interface across different providers
2. **Provider Management**: Automatic fallback if a provider fails
3. **Docker Integration**: Containerized with access to local Ollama
4. **Configuration**: Environment variables for API keys
5. **Extensibility**: Easy to add more providers
6. **Health Monitoring**: Status endpoint for monitoring

You can now integrate this LLM gateway with your search agent for enhanced reasoning capabilities!
