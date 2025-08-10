# ======================================================================================
# Search Agent's LLM Client - Final Version
#
# Description:
# This client communicates with the LLM Gateway. This final version includes the
# necessary `Message` Pydantic model to correctly structure the data sent to the
# gateway, resolving the fatal import error on startup.
# ======================================================================================
import os
import httpx
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

class Message(BaseModel):
    role: str
    content: str

class LLMClient:
    """Client to interact with the LLM API Gateway"""
    
    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or os.environ.get("LLM_GATEWAY_URL", "http://llm-gateway:8080")
    
    async def get_completion(self, 
                           messages: List[Message], 
                           provider: Optional[str] = None,
                           temperature: float = 0.7) -> str:
        """Get a complete, non-streaming response from the LLM Gateway."""
        payload = {
            "provider": provider,
            "messages": [msg.dict() for msg in messages],
            "temperature": temperature,
            "fallback": True,
            "stream": False
        }
        
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(f"{self.base_url}/completion", json=payload)
            response.raise_for_status()
            result = response.json()
            return result["content"]

    async def get_streaming_completion(self, messages: List[Message], provider: Optional[str] = None, temperature: float = 0.7):
        """Get a streaming response from the LLM Gateway."""
        payload = {
            "provider": provider,
            "messages": [msg.dict() for msg in messages],
            "temperature": temperature,
            "fallback": True,
            "stream": True
        }
        
        try:
            async with httpx.AsyncClient(timeout=90.0) as client:
                async with client.stream("POST", f"{self.base_url}/completion", json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        if line.startswith("data:"):
                            try:
                                data = json.loads(line[5:])
                                if data.get("content"):
                                    yield data["content"]
                            except json.JSONDecodeError:
                                continue
        except httpx.ConnectError as e:
            raise ConnectionError(f"Could not connect to LLM Gateway at {self.base_url}") from e
