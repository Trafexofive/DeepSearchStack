import asyncio
import os
import httpx
import json

# URLs now point to the reverse proxy by default
SEARCH_AGENT_URL = os.environ.get("SEARCH_AGENT_URL", "http://127.0.0.1/agent")
LLM_GATEWAY_URL = os.environ.get("LLM_GATEWAY_URL", "http://127.0.0.1/llm")

async def perform_search(client: httpx.AsyncClient, query: str) -> dict | None:
    """Helper function to perform a single search."""
    print("========================================================================")
    print(f"🔎 Querying Search Agent with: \"{query}\"")
    print("========================================================================")
    
    payload = {"query": query}
    
    try:
        response = await client.post(f"{SEARCH_AGENT_URL}/search", json=payload, timeout=120.0)
        
        if response.status_code == 200:
            result = response.json()
            print("\n✅ Answer from Search Agent:")
            print(result.get('answer', 'No answer found.'))
            
            sources = result.get('sources', [])
            if sources:
                print("\n📚 Sources:")
                for source in sources[:3]: # Print top 3 sources
                    print(f"- {source.get('title', 'N/A')}: {source.get('url', 'N/A')}")
            print("\n")
            return result
        else:
            print(f"\n❌ Error: {response.status_code} - {response.text}")
            return None

    except httpx.RequestError as e:
        print(f"\n❌ Request Error: Could not connect to the Search Agent at {SEARCH_AGENT_URL}.")
        print(f"   Details: {e}")
        return None
    except Exception as e:
        print(f"\n❌ An unexpected error occurred: {e}")
        return None

async def generate_follow_up_question(client: httpx.AsyncClient, context: str) -> str | None:
    """Uses the LLM to generate a follow-up question."""
    print("--- [LLM] Analyzing result to generate a follow-up question... ---")
    
    system_prompt = "You are a researcher. Based on the following text, what is the single most insightful follow-up question to ask to get more detail or a deeper explanation? Return only the question, nothing else."
    
    payload = {
        "provider": "gemini",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context}
        ],
        "temperature": 0.6
    }
    
    try:
        response = await client.post(f"{LLM_GATEWAY_URL}/completion", json=payload, timeout=60.0)
        if response.status_code == 200:
            result = response.json()
            question = result.get('content', '').strip().strip('"')
            print(f"--- [LLM] Generated Question: {question} ---")
            return question
        else:
            print(f"\n❌ LLM Error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"\n❌ An unexpected error occurred while generating follow-up: {e}")
        return None

async def main():
    """Runs a dynamic chained search demonstration."""
    
    async with httpx.AsyncClient() as client:
        # --- Step 1: Broad, high-level query ---
        initial_query = "What are the core principles of Retrieval-Augmented Generation (RAG)?"
        first_result = await perform_search(client, initial_query)
        
        if not first_result or not first_result.get("answer"):
            print("Aborting chain due to error or no answer in initial search.")
            return
            
        # --- Step 2: Use the LLM to generate a dynamic follow-up question ---
        follow_up_query = await generate_follow_up_question(client, first_result["answer"])
        
        if not follow_up_query:
            print("Could not generate a follow-up question. Ending chain.")
            return
            
        # --- Step 3: Perform the second search with the new, more specific query ---
        second_result = await perform_search(client, follow_up_query)

        if not second_result:
            print("Second part of the chain failed.")
            return

        print("✅ Dynamic chained search demonstration complete.")

if __name__ == "__main__":
    asyncio.run(main())