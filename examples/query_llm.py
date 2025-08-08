"""Example of using the LLM Gateway with streaming."""
import asyncio
import os
import httpx
import json

async def query_llm_stream():
    """Query the LLM Gateway using a streaming connection."""
    base_url = os.environ.get("LLM_GATEWAY_URL", "http://127.0.0.1/llm")
    
    # Use a provider that is ready (e.g., groq or gemini)
    # This request asks for a streaming response.
    payload = {
        "provider": "gemini",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Tell me a short, fun story about a robot who discovers music."}
        ],
        "stream": True
    }
    
    print(f"--- Querying {payload['provider']} with a streaming request ---")
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            async with client.stream("POST", f"{base_url}/completion", json=payload) as response:
                # Check if the request was successful
                if response.status_code != 200:
                    print(f"\n❌ Error: {response.status_code}")
                    # Consume the response body to get the error message
                    error_text = await response.aread()
                    print(f"   Details: {error_text.decode()}")
                    return

                print("\n✅ Streaming response from LLM Gateway:")
                async for line in response.aiter_lines():
                    if line.startswith('data:'):
                        data_str = line[len('data:'):].strip()
                        try:
                            data = json.loads(data_str)
                            if data.get("content"):
                                print(data["content"], end="", flush=True)
                            if data.get("error"):
                                print(f"\n\n❌ An error occurred during streaming: {data['error']}")
                        except json.JSONDecodeError:
                            # Ignore lines that are not valid JSON
                            continue
            print("\n\n--- Stream complete ---")
        except httpx.RequestError as e:
            print(f"\n❌ Request Error: Could not connect to the LLM Gateway at {base_url}.")
            print(f"   Details: {e}")

if __name__ == "__main__":
    asyncio.run(query_llm_stream())
