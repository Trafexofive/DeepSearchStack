import asyncio
import os
import httpx
import json

# --- Configuration ---
SEARCH_AGENT_URL = os.environ.get("SEARCH_AGENT_URL", "http://127.0.0.1/agent")
LLM_GATEWAY_URL = os.environ.get("LLM_GATEWAY_URL", "http://127.0.0.1/llm")

# --- Helper Functions ---

async def perform_search(client: httpx.AsyncClient, query: str) -> dict:
    """Performs a single search and returns the full result dictionary."""
    print(f"--- [Reporter] Researching: \"{query}\" ---")
    try:
        response = await client.post(f"{SEARCH_AGENT_URL}/search", json={"query": query}, timeout=120.0)
        response.raise_for_status()
        result = response.json()
        print(f"--- [Reporter] Research complete for: \"{query}\" ---")
        return result
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"[Error] Search failed for query ''{query}' ': {e}")
        return {"answer": f"Failed to get information on {query}.", "sources": []}

async def generate_final_report(client: httpx.AsyncClient, topic: str, search_results: list[dict]) -> str:
    """Synthesizes a final report from all gathered information and sources."""
    print("--- [Reporter] Synthesizing final report... ---")
    
    # Combine answers and format sources for the prompt
    context = ""
    source_map = {}
    source_counter = 1
    for i, result in enumerate(search_results):
        context += f"**Query {i+1} Analysis:**\n{result.get('answer', '')}\n\n"
        for source in result.get('sources', []):
            if source['url'] not in source_map:
                source_map[source['url']] = source_counter
                context += f"[Source {source_counter}] {source['title']}: {source['description'][:200]}...\n"
                source_counter += 1
    
    system_prompt = (
        "You are a professional reporter. Your task is to write a comprehensive, well-structured summary article on the given topic. "
        "Use the provided context from multiple search queries to write your report. "
        "Synthesize the information into a coherent narrative. Be neutral, factual, and easy to read. "
        "Cite the sources provided in the context using bracket notation like [Source 1], [Source 2], etc."
    )
    
    user_prompt = f"**Topic:** {topic}\n\n**Research Context:**\n{context}"
    
    payload = {
        "provider": "gemini", # Use a powerful model for better synthesis
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.6
    }
    
    try:
        response = await client.post(f"{LLM_GATEWAY_URL}/completion", json=payload, timeout=180.0)
        response.raise_for_status()
        result = response.json()
        print("--- [Reporter] Final report generated. ---")
        return result.get('content', "Failed to generate the final report.")
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"[Error] Could not generate final report: {e}")
        return "Error: The final report could not be generated due to a communication failure."

# --- Main Agent Logic ---

async def main():
    """The main function for the reporter agent."""
    
    main_topic = "The current state of the global semiconductor industry"
    
    queries = [
        main_topic,
        "What are the key challenges facing semiconductor manufacturing in 2025?",
        "Which companies are the market leaders in semiconductor design and fabrication?",
        "What is the impact of recent geopolitical events on the semiconductor supply chain?"
    ]
    
    async with httpx.AsyncClient() as client:
        # 1. Gather information from all queries in parallel
        search_tasks = [perform_search(client, query) for query in queries]
        all_results = await asyncio.gather(*search_tasks)
        
        # Filter out failed searches
        successful_results = [res for res in all_results if res and 'answer' in res and not res['answer'].startswith("Failed")]
        
        if not successful_results:
            print("\n[Critical Error] No information was gathered. Cannot generate a report.")
            return

        # 3. Synthesize the final report
        final_report = await generate_final_report(client, main_topic, successful_results)
        
        # 4. Print the final output
        print("\n" + "="*80)
        print(f"📰 FINAL REPORT: {main_topic}")
        print("="*80 + "\n")
        print(final_report)

if __name__ == "__main__":
    asyncio.run(main())