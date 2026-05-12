import asyncio
import os
import httpx

# --- Configuration ---
# URLs now point to the reverse proxy, which handles routing to the correct service.
SEARCH_AGENT_URL = os.environ.get("SEARCH_AGENT_URL", "http://127.0.0.1/agent")
LLM_GATEWAY_URL = os.environ.get("LLM_GATEWAY_URL", "http://127.0.0.1/llm")


# --- Helper Functions ---

async def perform_search(client: httpx.AsyncClient, query: str) -> str:
    """Performs a search and returns the synthesized answer."""
    print(f"--- [Case Study] Researching: \"{query}\" ---")
    try:
        response = await client.post(f"{SEARCH_AGENT_URL}/search", json={"query": query}, timeout=120.0)
        response.raise_for_status()
        return response.json().get("answer", f"No answer found for query: {query}")
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"[Error] Search failed for query ''{query}'' : {e}")
        return f"Error: Could not retrieve information for query: {query}."

async def generate_case_study(client: httpx.AsyncClient, subject: str, challenge: str, solution: str, outcome: str) -> str:
    """Uses the LLM Gateway to synthesize the final case study document."""
    print("--- [Case Study] Synthesizing final document... ---")
    
    system_prompt = (
        "You are a business analyst. Your task is to write a formal case study based on the provided information. "
        "Structure the document with clear headings: 'Executive Summary', 'The Challenge', 'The Solution', and 'The Outcome'. "
        "Write in a professional, analytical tone. Start with a brief executive summary that encapsulates the entire case study."
    )
    
    user_prompt = (
        f"**Case Study Subject:** {subject}\n\n" 
        f"**Challenge Context:**\n{challenge}\n\n" 
        f"**Solution Context:**\n{solution}\n\n" 
        f"**Outcome Context:**\n{outcome}"
    )

    payload = {
        "provider": "gemini",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.6
    }

    try:
        response = await client.post(f"{LLM_GATEWAY_URL}/completion", json=payload, timeout=180.0)
        response.raise_for_status()
        return response.json().get("content", "Failed to generate the case study.")
    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"[Error] Could not generate case study: {e}")
        return "Error: The case study could not be generated due to a communication failure with the LLM Gateway."

# --- Main Agent Logic ---

async def main():
    """The main function for the case study agent."""
    
    case_study_subject = "Netflix's transition from DVD rental to a global streaming service"
    
    # 1. Define the specific research queries for each section of the case study
    challenge_query = f"What were the primary business and logistical challenges Netflix faced when transitioning from DVDs to streaming?"
    solution_query = f"What key technologies and content strategies did Netflix implement to build its streaming platform?"
    outcome_query = f"What were the long-term outcomes and market impact of Netflix's successful pivot to streaming?"
    
    async with httpx.AsyncClient() as client:
        # 2. Execute the research queries in parallel
        tasks = {
            "challenge": perform_search(client, challenge_query),
            "solution": perform_search(client, solution_query),
            "outcome": perform_search(client, outcome_query),
        }
        
        results = await asyncio.gather(*tasks.values())
        
        challenge_context, solution_context, outcome_context = results

        # 3. Check if we have enough information
        if "Error:" in challenge_context or "Error:" in solution_context or "Error:" in outcome_context:
            print("\n[Critical Error] Failed to gather all necessary information. Cannot generate a complete case study.")
            return

        # 4. Synthesize the final case study document
        final_document = await generate_case_study(
            client, 
            case_study_subject, 
            challenge_context, 
            solution_context, 
            outcome_context
        )
        
        # 5. Print the final output
        print("\n" + "="*80)
        print(f"📄 CASE STUDY: {case_study_subject}")
        print("="*80 + "\n")
        print(final_document)

if __name__ == "__main__":
    asyncio.run(main())