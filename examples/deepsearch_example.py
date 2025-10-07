#!/usr/bin/env python3
"""
Example: Using the DeepSearch API
"""
import asyncio
import httpx
import json
import sys

DEEPSEARCH_URL = "http://localhost:8001"


async def quick_search(query: str):
    """Simple non-streaming search"""
    print(f"\n🔍 Quick Search: {query}\n")
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            f"{DEEPSEARCH_URL}/deepsearch/quick",
            json={
                "query": query,
                "max_results": 20
            }
        )
        
        if response.status_code == 200:
            result = response.json()
            print(f"✅ Answer:\n{result['answer']}\n")
            print(f"\n📚 Sources ({len(result['sources'])}):")
            for i, source in enumerate(result['sources'][:5], 1):
                print(f"  [{i}] {source['title']}")
                print(f"      {source['url']}")
            
            print(f"\n⏱️  Execution time: {result['execution_time']:.2f}s")
            print(f"📊 Total results: {result['total_results']}")
            print(f"🌐 Scraped: {result['results_scraped']}")
            print(f"🧠 RAG chunks: {result['chunks_retrieved']}")
        else:
            print(f"❌ Error: {response.status_code}")
            print(response.text)


async def streaming_search(query: str):
    """Streaming search with progress updates"""
    print(f"\n🔍 Streaming Search: {query}\n")
    
    async with httpx.AsyncClient(timeout=180.0) as client:
        async with client.stream(
            "POST",
            f"{DEEPSEARCH_URL}/deepsearch",
            json={
                "query": query,
                "max_results": 50,
                "enable_scraping": True,
                "enable_rag": True,
                "enable_synthesis": True,
                "stream": True
            }
        ) as response:
            if response.status_code != 200:
                print(f"❌ Error: {response.status_code}")
                return
            
            print("📡 Streaming response:\n")
            answer_parts = []
            
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    try:
                        chunk = json.loads(line[6:])
                        
                        if chunk["type"] == "progress":
                            data = chunk["data"]
                            print(f"[{data['stage'].upper()}] {data['message']} ({int(data['progress']*100)}%)")
                        
                        elif chunk["type"] == "content":
                            content = chunk["data"]["content"]
                            answer_parts.append(content)
                            print(content, end="", flush=True)
                        
                        elif chunk["type"] == "sources":
                            sources = chunk["data"]["sources"]
                            print(f"\n\n📚 Sources ({len(sources)}):")
                            for i, source in enumerate(sources[:5], 1):
                                print(f"  [{i}] {source['title']}")
                        
                        elif chunk["type"] == "complete":
                            data = chunk["data"]
                            print(f"\n\n✅ Complete!")
                            print(f"⏱️  {data['execution_time']:.2f}s | 📊 {data['total_results']} results | 🌐 {data['results_scraped']} scraped | 🧠 {data['chunks_retrieved']} chunks")
                        
                        elif chunk["type"] == "error":
                            print(f"\n❌ Error: {chunk['data']['message']}")
                    
                    except json.JSONDecodeError:
                        continue


async def session_example(query: str):
    """Example with session management"""
    print(f"\n💬 Session Example: {query}\n")
    
    async with httpx.AsyncClient(timeout=120.0) as client:
        # Create session
        session_resp = await client.post(
            f"{DEEPSEARCH_URL}/sessions",
            json={"metadata": {"demo": True}}
        )
        session = session_resp.json()
        session_id = session["session_id"]
        print(f"✓ Created session: {session_id}")
        
        # First query
        resp1 = await client.post(
            f"{DEEPSEARCH_URL}/deepsearch/quick",
            json={
                "query": query,
                "session_id": session_id,
                "max_results": 10
            }
        )
        result1 = resp1.json()
        print(f"\n1️⃣  {result1['answer'][:200]}...")
        
        # Second query in same session
        resp2 = await client.post(
            f"{DEEPSEARCH_URL}/deepsearch/quick",
            json={
                "query": "Can you elaborate on that?",
                "session_id": session_id,
                "max_results": 10
            }
        )
        result2 = resp2.json()
        print(f"\n2️⃣  {result2['answer'][:200]}...")
        
        # Get session history
        history_resp = await client.get(f"{DEEPSEARCH_URL}/sessions/{session_id}")
        history = history_resp.json()
        print(f"\n📜 Session has {len(history['messages'])} messages")
        
        # Cleanup
        await client.delete(f"{DEEPSEARCH_URL}/sessions/{session_id}")
        print(f"✓ Deleted session")


async def main():
    """Run examples"""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python examples/deepsearch_example.py quick \"your query\"")
        print("  python examples/deepsearch_example.py stream \"your query\"")
        print("  python examples/deepsearch_example.py session \"your query\"")
        return
    
    mode = sys.argv[1]
    query = sys.argv[2] if len(sys.argv) > 2 else "What is artificial intelligence?"
    
    try:
        if mode == "quick":
            await quick_search(query)
        elif mode == "stream":
            await streaming_search(query)
        elif mode == "session":
            await session_example(query)
        else:
            print(f"Unknown mode: {mode}")
    except httpx.ConnectError:
        print(f"\n❌ Cannot connect to DeepSearch at {DEEPSEARCH_URL}")
        print("   Make sure the service is running: cd infra && docker-compose up deepsearch")
    except Exception as e:
        print(f"\n❌ Error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
