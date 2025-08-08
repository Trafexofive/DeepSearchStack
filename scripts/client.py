#!/usr/bin/env python3
# ======================================================================================
# DeepSearchStack - Python Command-Line Client v1.3 (Definitive)
# ======================================================================================
import argparse
import os
import httpx
import json
import asyncio
from rich.console import Console
from rich.markdown import Markdown
from rich.live import Live
from rich.panel import Panel

# --- Configuration ---
BASE_URL = os.environ.get("BASE_URL", "http://localhost")
SEARCH_AGENT_URL = f"{BASE_URL}/agent"
LLM_GATEWAY_URL = f"{BASE_URL}/llm"
TIMEOUT = 180.0

console = Console()

async def handle_stream(response: httpx.Response, live: Live):
    buffer = ""
    sources = []
    try:
        response.raise_for_status()
        async for line in response.aiter_lines():
            if line.startswith("data:"):
                try:
                    data = json.loads(line[5:])
                    if data.get("finished"):
                        sources = data.get("sources", [])
                        break
                    content = data.get("content", "")
                    if content:
                        buffer += content
                        live.update(Markdown(buffer, style="bright_green"), refresh=True)
                except json.JSONDecodeError:
                    continue
    except httpx.HTTPStatusError as e:
        error_body = await e.response.aread()
        buffer += f"\n\n[bold red]API Error: {e.response.status_code}[/bold red]\n{error_body.decode()}"

    if sources:
        source_md = "\n\n---\n**Sources:**\n"
        for i, source in enumerate(sources):
            source_md += f"{i+1}. [{source['title']}]({source['url']})\n"
        buffer += source_md
    
    live.update(Panel(Markdown(buffer), border_style="green"), refresh=True)

async def cmd_health(args):
    console.print(Panel("[bold cyan]Checking Service Health[/bold cyan]", expand=False))
    async with httpx.AsyncClient() as client:
        for name, url in [("Search Agent", f"{SEARCH_AGENT_URL}/health"), ("LLM Gateway", f"{LLM_GATEWAY_URL}/health")]:
            try:
                resp = await client.get(url, timeout=10)
                resp.raise_for_status()
                console.print(f"[green]✔ {name}:[/green] Healthy (200 OK)")
            except (httpx.RequestError, httpx.HTTPStatusError) as e:
                console.print(f"[red]✖ {name}:[/red] Unhealthy - {e}")

async def cmd_llm_providers(args):
    console.print(Panel("[bold cyan]Available LLM Providers[/bold cyan]", expand=False))
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{LLM_GATEWAY_URL}/providers", timeout=10)
            resp.raise_for_status()
            console.print(resp.json())
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            console.print(f"[red]Error: {e}[/red]")

async def cmd_search_providers(args):
    console.print(Panel("[bold cyan]Available Search Providers[/bold cyan]", expand=False))
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(f"{SEARCH_AGENT_URL}/providers", timeout=10)
            resp.raise_for_status()
            console.print(resp.json())
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            console.print(f"[red]Error: {e}[/red]")

async def cmd_ask(args):
    console.print(f"Asking [bold yellow]{args.provider or 'default'}[/bold yellow]...")
    messages = [{"role": "user", "content": args.query}]
    if args.system:
        messages.insert(0, {"role": "system", "content": args.system})
    payload = {"messages": messages, "provider": args.provider, "temperature": args.temp, "stream": args.stream}
    
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            if args.stream:
                async with client.stream("POST", f"{LLM_GATEWAY_URL}/completion", json=payload) as response:
                    with Live(console=console, auto_refresh=False) as live:
                        await handle_stream(response, live)
            else:
                resp = await client.post(f"{LLM_GATEWAY_URL}/completion", json=payload)
                resp.raise_for_status()
                console.print(Panel(Markdown(resp.json().get("content", "")), title="Response", border_style="green"))
        except httpx.HTTPStatusError as e:
            console.print(f"[bold red]API Error:[/bold red] {e.response.status_code} - {e.response.text}")

async def cmd_search(args):
    console.print(f"Searching for: \"{args.query}\"...")
    # FIX: Ensure 'providers' is always a list, never null.
    providers_list = args.providers.split(',') if args.providers else ["whoogle", "searxng"]
    payload = {
        "query": args.query,
        "providers": providers_list,
        "llm_provider": args.llm_provider,
        "max_results": args.max_results,
        "sort_by": args.sort
    }
    
    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        try:
            endpoint = f"{SEARCH_AGENT_URL}/search/stream" if args.stream else f"{SEARCH_AGENT_URL}/search"
            if args.stream:
                async with client.stream("POST", endpoint, json=payload) as response:
                    with Live(console=console, auto_refresh=False) as live:
                        await handle_stream(response, live)
            else:
                resp = await client.post(endpoint, json=payload)
                resp.raise_for_status()
                data = resp.json()
                md = f"{data.get('answer', '')}\n\n---\n**Sources:**\n"
                for i, source in enumerate(data.get('sources', [])):
                     md += f"{i+1}. [{source['title']}]({source['url']})\n"
                console.print(Panel(Markdown(md), title="Search Result", border_style="green"))
        except httpx.HTTPStatusError as e:
            error_body = await e.response.aread()
            console.print(f"[bold red]API Error:[/bold red] {e.response.status_code} - {error_body.decode()}")

async def main():
    parser = argparse.ArgumentParser(description="DeepSearchStack Advanced Command-Line Client")
    subparsers = parser.add_subparsers(dest="command", required=True, help="Available commands")

    p_search = subparsers.add_parser("search", help="Perform a full search and synthesis.")
    p_search.add_argument("query", type=str, help="The search query.")
    p_search.add_argument("--stream", action="store_true")
    p_search.add_argument("--llm-provider", type=str)
    p_search.add_argument("-p", "--providers", type=str)
    p_search.add_argument("-n", "--max-results", type=int, default=10)
    p_search.add_argument("--sort", type=str, default="relevance", choices=["relevance", "date"])
    p_search.set_defaults(func=cmd_search)

    p_ask = subparsers.add_parser("ask", help="Directly query the LLM Gateway.")
    p_ask.add_argument("query", type=str, help="The prompt for the LLM.")
    p_ask.add_argument("--stream", action="store_true")
    p_ask.add_argument("-p", "--provider", type=str)
    p_ask.add_argument("--system", type=str)
    p_ask.add_argument("-t", "--temp", type=float, default=0.7)
    p_ask.set_defaults(func=cmd_ask)

    p_health = subparsers.add_parser("health", help="Check service health.")
    p_health.set_defaults(func=cmd_health)
    
    p_llm_providers = subparsers.add_parser("llm-providers", help="List available LLM providers.")
    p_llm_providers.set_defaults(func=cmd_llm_providers)

    p_search_providers = subparsers.add_parser("search-providers", help="List available search providers.")
    p_search_providers.set_defaults(func=cmd_search_providers)

    args = parser.parse_args()
    await args.func(args)

if __name__ == "__main__":
    asyncio.run(main())
