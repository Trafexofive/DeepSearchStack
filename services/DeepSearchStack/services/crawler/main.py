import asyncio
import time
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
from crawl4ai import AsyncWebCrawler
from crawl4ai.extraction_strategy import LLMExtractionStrategy, JsonCssExtractionStrategy
import uvicorn

app = FastAPI(title="Crawler Service", description="Microservice for web crawling using crawl4ai")

class CrawlRequest(BaseModel):
    url: str
    extraction_strategy: str = "llm"  # "llm" or "json_css"
    css_selector: Optional[str] = None  # Used when extraction_strategy is "json_css"

class CrawlResponse(BaseModel):
    url: str
    content: str
    extracted_data: Optional[Dict[str, Any]] = None
    success: bool
    error_message: Optional[str] = None

@app.on_event("startup")
async def startup_event():
    print("Initializing WebCrawler...")
    # Initialize the crawler (this will be reused)
    app.state.crawler = AsyncWebCrawler()
    await app.state.crawler.start()
    print("Crawler service started and ready to process requests")

@app.on_event("shutdown")
async def shutdown_event():
    print("Shutting down WebCrawler...")
    if hasattr(app.state, 'crawler'):
        await app.state.crawler.close()
    print("Crawler service shut down")

@app.post("/crawl", response_model=CrawlResponse)
async def crawl_url(request: CrawlRequest):
    try:
        print(f"Starting crawl for URL: {request.url}")
        
        # Use the initialized crawler
        if request.extraction_strategy == "llm":
            result = await app.state.crawler.arun(
                url=request.url,
                extraction_strategy=LLMExtractionStrategy()
            )
        elif request.extraction_strategy == "json_css" and request.css_selector:
            result = await app.state.crawler.arun(
                url=request.url,
                extraction_strategy=JsonCssExtractionStrategy(schema=request.css_selector)
            )
        else:
            result = await app.state.crawler.arun(url=request.url)
        
        if result.success:
            # Extract content properly
            content = ""
            if hasattr(result, 'markdown_v2') and result.markdown_v2:
                content = result.markdown_v2.text
            elif hasattr(result, 'markdown'):
                content = result.markdown
            else:
                content = ""
                
            # Extract extracted_content properly
            extracted_data = None
            if hasattr(result, 'extracted_content') and result.extracted_content:
                extracted_data = result.extracted_content
            
            return CrawlResponse(
                url=request.url,
                content=content,
                extracted_data=extracted_data,
                success=True
            )
        else:
            return CrawlResponse(
                url=request.url,
                content="",
                success=False,
                error_message=getattr(result, 'error_message', 'Unknown error')
            )
            
    except Exception as e:
        return CrawlResponse(
            url=request.url,
            content="",
            success=False,
            error_message=str(e)
        )

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "crawler"}

@app.get("/")
async def root():
    return {
        "message": "Crawler Service with crawl4ai", 
        "endpoints": {
            "/crawl": "POST - Crawl a URL",
            "/health": "GET - Health check",
        }
    }

if __name__ == "__main__":
    print("Crawler service starting...")
    uvicorn.run(app, host="0.0.0.0", port=8000)