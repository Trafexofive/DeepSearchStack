"""Example of using the Search Agent"""
import asyncio
import os
import httpx

async def query_search_agent():
    """Query the Search Agent"""
    base_url = os.environ.get("SEARCH_AGENT_URL", "http://localhost/agent")
    
    headers = {"Host": "localhost"}
    
    payload = {
        "query": "What is the latest news on the Gemini project?"
    }
    
    transport = httpx.AsyncHTTPTransport(resolver=httpx.Resolver(family=httpx.AF_INET))
    async with httpx.AsyncClient(transport=transport, timeout=60.0) as client:
        response = await client.post(f"{base_url}/search", json=payload, headers=headers)
        
        if response.status_code == 200:
            result = response.json()
            print("\nResponse from Search Agent:")
            print(f"Answer: {result['answer']}")
            print("\nSources:")
            for source in result['sources']:
                print(f"- {source['title']}: {source['url']}")
        else:
            print(f"\nError: {response.status_code} - {response.text}")

if __name__ == "__main__":
    asyncio.run(query_search_agent())

