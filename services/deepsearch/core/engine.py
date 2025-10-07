"""
DeepSearch Core Engine
Orchestrates the full search → scrape → embed → retrieve → synthesize pipeline
"""
import asyncio
import hashlib
import time
import logging
from typing import List, Dict, Optional, AsyncIterator
import httpx
import json

from models import (
    DeepSearchRequest, DeepSearchResponse, DeepSearchProgress,
    SearchResult, ScrapedContent, VectorChunk, StreamChunk
)
from config import config

logger = logging.getLogger("deepsearch.core")


class DeepSearchEngine:
    """Main DeepSearch orchestration engine"""
    
    def __init__(self):
        self.search_gateway_url = config.get_service_url("search_gateway")
        self.llm_gateway_url = config.get_service_url("llm_gateway")
        self.vector_store_url = config.get_service_url("vector_store")
        self.crawler_url = config.get_service_url("crawler")
        
        # Service clients
        self.http_client: Optional[httpx.AsyncClient] = None
        
    async def initialize(self):
        """Initialize async resources"""
        self.http_client = httpx.AsyncClient(timeout=60.0)
    
    async def shutdown(self):
        """Cleanup async resources"""
        if self.http_client:
            await self.http_client.aclose()
    
    async def deep_search(
        self, 
        request: DeepSearchRequest
    ) -> AsyncIterator[StreamChunk]:
        """
        Execute full DeepSearch pipeline with streaming progress
        
        Pipeline stages:
        1. Search: Query multiple providers in parallel
        2. Scrape: Extract full content from top results
        3. Embed: Store content in vector database
        4. Retrieve: Get most relevant chunks via RAG
        5. Synthesize: Generate comprehensive answer with LLM
        """
        start_time = time.time()
        
        try:
            # Stage 1: Search
            yield StreamChunk(
                type="progress",
                data=DeepSearchProgress(
                    stage="searching",
                    message=f"Searching across {len(request.providers or config.search_config.get('default_providers', []))} providers...",
                    progress=0.1
                ).dict()
            )
            
            search_results = await self._parallel_search(request)
            
            if not search_results:
                yield StreamChunk(
                    type="error",
                    data={"message": "No search results found"}
                )
                return
            
            # Stage 2: Scrape (if enabled)
            scraped_content = []
            if request.enable_scraping and config.scraping_config.get("enabled", True):
                yield StreamChunk(
                    type="progress",
                    data=DeepSearchProgress(
                        stage="scraping",
                        message=f"Scraping content from {min(len(search_results), request.max_scrape_urls or config.scraping_config.get('max_scrape_urls', 50))} URLs...",
                        progress=0.3
                    ).dict()
                )
                
                scraped_content = await self._parallel_scrape(
                    search_results,
                    max_urls=request.max_scrape_urls or config.scraping_config.get("max_scrape_urls", 50)
                )
            
            # Stage 3: Embed (if RAG enabled)
            if request.enable_rag and config.rag_config.get("enabled", True) and scraped_content:
                yield StreamChunk(
                    type="progress",
                    data=DeepSearchProgress(
                        stage="embedding",
                        message=f"Embedding {len(scraped_content)} documents into vector store...",
                        progress=0.5
                    ).dict()
                )
                
                await self._embed_documents(request.query, scraped_content)
            
            # Stage 4: Retrieve (RAG)
            rag_chunks = []
            if request.enable_rag and config.rag_config.get("enabled", True):
                yield StreamChunk(
                    type="progress",
                    data=DeepSearchProgress(
                        stage="retrieving",
                        message="Retrieving most relevant content chunks...",
                        progress=0.6
                    ).dict()
                )
                
                rag_chunks = await self._retrieve_chunks(
                    request.query,
                    top_k=request.rag_top_k or config.rag_config.get("top_k", 10)
                )
            
            # Stage 5: Synthesize
            if request.enable_synthesis:
                yield StreamChunk(
                    type="progress",
                    data=DeepSearchProgress(
                        stage="synthesizing",
                        message="Generating comprehensive answer...",
                        progress=0.7
                    ).dict()
                )
                
                # Build context from RAG chunks or search results
                context = self._build_context(
                    rag_chunks if rag_chunks else search_results,
                    scraped_content
                )
                
                # Stream synthesis
                answer_parts = []
                async for content_chunk in self._stream_synthesis(
                    request.query,
                    context,
                    request.llm_provider,
                    request.temperature
                ):
                    answer_parts.append(content_chunk)
                    yield StreamChunk(
                        type="content",
                        data={"content": content_chunk}
                    )
                
                answer = "".join(answer_parts)
            else:
                answer = "Search completed. Synthesis disabled."
            
            # Stage 6: Complete
            execution_time = time.time() - start_time
            
            yield StreamChunk(
                type="sources",
                data={"sources": [r.dict() for r in search_results]}
            )
            
            yield StreamChunk(
                type="complete",
                data=DeepSearchResponse(
                    query=request.query,
                    answer=answer,
                    sources=search_results,
                    scraped_content=scraped_content if scraped_content else None,
                    rag_chunks=rag_chunks if rag_chunks else None,
                    session_id=request.session_id,
                    execution_time=execution_time,
                    provider_used=request.llm_provider or config.synthesis_config.get("default_provider", "ollama"),
                    total_results=len(search_results),
                    results_scraped=len(scraped_content),
                    chunks_retrieved=len(rag_chunks)
                ).dict()
            )
            
        except Exception as e:
            logger.error(f"DeepSearch pipeline error: {e}", exc_info=True)
            yield StreamChunk(
                type="error",
                data={"message": f"Pipeline error: {str(e)}"}
            )
    
    async def _parallel_search(self, request: DeepSearchRequest) -> List[SearchResult]:
        """Execute parallel search across multiple providers"""
        providers = request.providers or config.search_config.get("default_providers", [])
        max_results = request.max_results or config.search_config.get("max_results", 100)
        
        search_payload = {
            "query": request.query,
            "providers": providers,
            "max_results": max_results,
            "sort_by": request.sort_by,
            "timeout": config.search_config.get("timeout", 30.0)
        }
        
        try:
            response = await self.http_client.post(
                f"{self.search_gateway_url}/search",
                json=search_payload,
                timeout=config.search_config.get("timeout", 30.0)
            )
            response.raise_for_status()
            results_data = response.json()
            return [SearchResult(**r) for r in results_data]
        except Exception as e:
            logger.error(f"Search gateway error: {e}")
            return []
    
    async def _parallel_scrape(
        self, 
        search_results: List[SearchResult], 
        max_urls: int
    ) -> List[ScrapedContent]:
        """Scrape content from URLs in parallel"""
        urls_to_scrape = [r.url for r in search_results[:max_urls]]
        concurrency = config.scraping_config.get("concurrency", 10)
        
        semaphore = asyncio.Semaphore(concurrency)
        
        async def scrape_one(url: str, title: str) -> Optional[ScrapedContent]:
            async with semaphore:
                try:
                    response = await self.http_client.post(
                        f"{self.crawler_url}/crawl",
                        json={
                            "url": url,
                            "extraction_strategy": config.scraping_config.get("extraction_strategy", "markdown")
                        },
                        timeout=config.scraping_config.get("timeout", 15.0)
                    )
                    response.raise_for_status()
                    data = response.json()
                    
                    return ScrapedContent(
                        url=url,
                        title=title,
                        content=data.get("content", ""),
                        markdown=data.get("content", ""),
                        success=data.get("success", False),
                        word_count=len(data.get("content", "").split()),
                        error_message=data.get("error_message")
                    )
                except Exception as e:
                    logger.warning(f"Scrape failed for {url}: {e}")
                    return ScrapedContent(
                        url=url,
                        title=title,
                        content="",
                        success=False,
                        error_message=str(e)
                    )
        
        tasks = [
            scrape_one(result.url, result.title) 
            for result in search_results[:max_urls]
        ]
        results = await asyncio.gather(*tasks)
        
        # Filter successful scrapes with min content length
        min_length = config.scraping_config.get("min_content_length", 100)
        return [
            r for r in results 
            if r and r.success and len(r.content) >= min_length
        ]
    
    async def _embed_documents(
        self, 
        query: str, 
        scraped_content: List[ScrapedContent]
    ):
        """Embed documents into vector store"""
        if not config.rag_config.get("store_scraped_content", True):
            return
        
        documents = []
        for content in scraped_content:
            # Split into chunks
            chunks = self._split_into_chunks(
                content.content,
                chunk_size=config.rag_config.get("chunk_size", 1000),
                overlap=config.rag_config.get("chunk_overlap", 200)
            )
            
            for i, chunk in enumerate(chunks):
                documents.append({
                    "id": hashlib.md5(f"{content.url}_{i}".encode()).hexdigest(),
                    "text": chunk,
                    "metadata": {
                        "url": content.url,
                        "title": content.title,
                        "chunk_index": i,
                        "query": query
                    }
                })
        
        if documents:
            try:
                await self.http_client.post(
                    f"{self.vector_store_url}/embed",
                    json={"documents": documents},
                    timeout=30.0
                )
            except Exception as e:
                logger.error(f"Vector store embed error: {e}")
    
    async def _retrieve_chunks(
        self, 
        query: str, 
        top_k: int
    ) -> List[VectorChunk]:
        """Retrieve most relevant chunks from vector store"""
        try:
            response = await self.http_client.post(
                f"{self.vector_store_url}/query",
                json={"query_text": query, "n_results": top_k},
                timeout=10.0
            )
            response.raise_for_status()
            data = response.json()
            
            # Convert ChromaDB response to VectorChunk objects
            chunks = []
            if "documents" in data and data["documents"]:
                for i, doc in enumerate(data["documents"][0]):
                    metadata = data.get("metadatas", [[]])[0][i] if "metadatas" in data else {}
                    distance = data.get("distances", [[]])[0][i] if "distances" in data else None
                    
                    chunks.append(VectorChunk(
                        chunk_id=data.get("ids", [[]])[0][i],
                        content=doc,
                        url=metadata.get("url", ""),
                        title=metadata.get("title", ""),
                        similarity_score=1 - distance if distance is not None else None,
                        metadata=metadata
                    ))
            
            return chunks
        except Exception as e:
            logger.error(f"Vector store query error: {e}")
            return []
    
    async def _stream_synthesis(
        self,
        query: str,
        context: str,
        llm_provider: Optional[str],
        temperature: Optional[float]
    ) -> AsyncIterator[str]:
        """Stream LLM synthesis"""
        provider = llm_provider or config.synthesis_config.get("default_provider", "ollama")
        temp = temperature or config.synthesis_config.get("temperature", 0.3)
        system_prompt = config.synthesis_config.get("system_prompt", "")
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"User Query: {query}\n\nSearch Context:\n{context}"}
        ]
        
        payload = {
            "provider": provider,
            "messages": messages,
            "temperature": temp,
            "stream": True
        }
        
        try:
            async with self.http_client.stream(
                "POST",
                f"{self.llm_gateway_url}/completion",
                json=payload,
                timeout=config.synthesis_config.get("timeout", 120.0)
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            data = json.loads(line[6:])
                            if "content" in data:
                                yield data["content"]
                        except json.JSONDecodeError:
                            continue
        except Exception as e:
            logger.error(f"LLM synthesis error: {e}")
            yield f"\n\n**Error during synthesis:** {str(e)}"
    
    def _build_context(
        self,
        chunks_or_results: List,
        scraped_content: Optional[List[ScrapedContent]] = None
    ) -> str:
        """Build context string for LLM from chunks or search results"""
        context_parts = []
        
        if chunks_or_results and isinstance(chunks_or_results[0], VectorChunk):
            # RAG mode: use chunks
            for i, chunk in enumerate(chunks_or_results, 1):
                context_parts.append(
                    f"Source [{i}]: {chunk.title}\n"
                    f"URL: {chunk.url}\n"
                    f"Content: {chunk.content}\n"
                )
        else:
            # Standard mode: use search results + scraped content
            for i, result in enumerate(chunks_or_results, 1):
                content = result.description
                
                # Find matching scraped content
                if scraped_content:
                    for scraped in scraped_content:
                        if scraped.url == result.url and scraped.success:
                            # Use first 2000 chars of scraped content
                            content = scraped.content[:2000]
                            break
                
                context_parts.append(
                    f"Source [{i}]: {result.title}\n"
                    f"URL: {result.url}\n"
                    f"Content: {content}\n"
                )
        
        return "\n\n".join(context_parts)
    
    def _split_into_chunks(
        self, 
        text: str, 
        chunk_size: int, 
        overlap: int
    ) -> List[str]:
        """Split text into overlapping chunks"""
        chunks = []
        start = 0
        
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]
            chunks.append(chunk)
            start = end - overlap
        
        return chunks
