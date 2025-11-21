#!/usr/bin/env python3
"""
DeepSearchStack - Comprehensive Benchmark Suite
Realistic performance testing for core search functionality
"""

import asyncio
import time
import json
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
import aiohttp
import statistics
from concurrent.futures import ThreadPoolExecutor
import argparse
import sys


@dataclass
class BenchmarkResult:
    test_name: str
    requests_sent: int
    successful_requests: int
    failed_requests: int
    total_time: float  # seconds
    avg_response_time: float  # seconds
    min_response_time: float  # seconds
    max_response_time: float  # seconds
    throughput: float  # requests per second
    error_rate: float
    response_times: List[float]
    errors: List[str]


class DeepSearchBenchmark:
    def __init__(self, base_url: str = "http://localhost:8080"):
        self.base_url = base_url
        self.session = None
        
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            connector=aiohttp.TCPConnector(limit=100, limit_per_host=30)
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    

    async def crawl_benchmark(self, urls: List[str], concurrency: int = 10) -> BenchmarkResult:
        """Test crawler performance with realistic URLs"""
        print(f"[CRAWL] Testing {len(urls)} URLs with {concurrency} concurrent requests")
        
        semaphore = asyncio.Semaphore(concurrency)
        results = []
        errors = []
        response_times = []
        
        async def crawl_single(url: str):
            async with semaphore:
                start_time = time.time()
                try:
                    payload = {
                        "url": url,
                        "formats": ["markdown"],
                        "extract_metadata": True,
                        "timeout": 10
                    }
                    
                    async with self.session.post(
                        f"{self.base_url.replace(':8080', ':8004')}/crawl",
                        json=payload
                    ) as resp:
                        response_time = time.time() - start_time
                        response_times.append(response_time)
                        
                        if resp.status == 200:
                            content = await resp.json()
                            results.append(content)
                            return True, None
                        else:
                            error_text = await resp.text()
                            errors.append(f"HTTP {resp.status}: {error_text}")
                            return False, f"HTTP {resp.status}: {error_text}"
                            
                except Exception as e:
                    response_time = time.time() - start_time
                    response_times.append(response_time)
                    error_msg = f"Exception: {str(e)}"
                    errors.append(error_msg)
                    return False, error_msg
        
        start_total = time.time()
        tasks = [crawl_single(url) for url in urls]
        results_raw = await asyncio.gather(*tasks, return_exceptions=True)
        
        total_time = time.time() - start_total
        
        successful_requests = sum(1 for success, _ in results_raw if isinstance(success, bool) and success)
        failed_requests = len(results_raw) - successful_requests
        
        if response_times:
            avg_response_time = statistics.mean(response_times)
            min_response_time = min(response_times)
            max_response_time = max(response_times)
        else:
            avg_response_time = min_response_time = max_response_time = 0
            
        throughput = len(urls) / total_time if total_time > 0 else 0
        error_rate = failed_requests / len(urls) if len(urls) > 0 else 0
        
        return BenchmarkResult(
            test_name="Crawler Load Test",
            requests_sent=len(urls),
            successful_requests=successful_requests,
            failed_requests=failed_requests,
            total_time=total_time,
            avg_response_time=avg_response_time,
            min_response_time=min_response_time,
            max_response_time=max_response_time,
            throughput=throughput,
            error_rate=error_rate,
            response_times=response_times,
            errors=errors
        )


    async def search_benchmark(self, queries: List[str], concurrency: int = 5) -> BenchmarkResult:
        """Test search functionality performance"""
        print(f"[SEARCH] Testing {len(queries)} queries with {concurrency} concurrent requests")
        
        semaphore = asyncio.Semaphore(concurrency)
        results = []
        errors = []
        response_times = []
        
        async def search_single(query: str):
            async with semaphore:
                start_time = time.time()
                try:
                    payload = {
                        "query": query,
                        "max_results": 5,
                        "search_depth": "advanced",
                        "include_domains": [],
                        "exclude_domains": []
                    }
                    
                    async with self.session.post(
                        f"{self.base_url.replace(':8080', ':8003')}/search",  # Search gateway port
                        json=payload
                    ) as resp:
                        response_time = time.time() - start_time
                        response_times.append(response_time)
                        
                        if resp.status == 200:
                            content = await resp.json()
                            results.append(content)
                            return True, None
                        else:
                            error_text = await resp.text()
                            errors.append(f"HTTP {resp.status}: {error_text}")
                            return False, f"HTTP {resp.status}: {error_text}"
                            
                except Exception as e:
                    response_time = time.time() - start_time
                    response_times.append(response_time)
                    error_msg = f"Exception: {str(e)}"
                    errors.append(error_msg)
                    return False, error_msg
        
        start_total = time.time()
        tasks = [search_single(query) for query in queries]
        results_raw = await asyncio.gather(*tasks, return_exceptions=True)
        
        total_time = time.time() - start_total
        
        successful_requests = sum(1 for success, _ in results_raw if isinstance(success, bool) and success)
        failed_requests = len(results_raw) - successful_requests
        
        if response_times:
            avg_response_time = statistics.mean(response_times)
            min_response_time = min(response_times)
            max_response_time = max(response_times)
        else:
            avg_response_time = min_response_time = max_response_time = 0
            
        throughput = len(queries) / total_time if total_time > 0 else 0
        error_rate = failed_requests / len(queries) if len(queries) > 0 else 0
        
        return BenchmarkResult(
            test_name="Search Aggregation Load Test",
            requests_sent=len(queries),
            successful_requests=successful_requests,
            failed_requests=failed_requests,
            total_time=total_time,
            avg_response_time=avg_response_time,
            min_response_time=min_response_time,
            max_response_time=max_response_time,
            throughput=throughput,
            error_rate=error_rate,
            response_times=response_times,
            errors=errors
        )


    async def llm_benchmark(self, messages_batch: List[List[Dict]], provider: str = "gemini", concurrency: int = 3) -> BenchmarkResult:
        """Test LLM gateway performance"""
        print(f"[LLM] Testing {len(messages_batch)} requests with {concurrency} concurrent requests")
        
        semaphore = asyncio.Semaphore(concurrency)
        results = []
        errors = []
        response_times = []
        
        async def llm_single(messages: List[Dict]):
            async with semaphore:
                start_time = time.time()
                try:
                    payload = {
                        "provider": provider,
                        "messages": messages,
                        "temperature": 0.7,
                        "max_tokens": 500
                    }
                    
                    async with self.session.post(
                        f"{self.base_url}/completion",
                        json=payload
                    ) as resp:
                        response_time = time.time() - start_time
                        response_times.append(response_time)
                        
                        if resp.status == 200:
                            content = await resp.json()
                            results.append(content)
                            return True, None
                        else:
                            error_text = await resp.text()
                            errors.append(f"HTTP {resp.status}: {error_text}")
                            return False, f"HTTP {resp.status}: {error_text}"
                            
                except Exception as e:
                    response_time = time.time() - start_time
                    response_times.append(response_time)
                    error_msg = f"Exception: {str(e)}"
                    errors.append(error_msg)
                    return False, error_msg
        
        start_total = time.time()
        tasks = [llm_single(messages) for messages in messages_batch]
        results_raw = await asyncio.gather(*tasks, return_exceptions=True)
        
        total_time = time.time() - start_total
        
        successful_requests = sum(1 for success, _ in results_raw if isinstance(success, bool) and success)
        failed_requests = len(results_raw) - successful_requests
        
        if response_times:
            avg_response_time = statistics.mean(response_times)
            min_response_time = min(response_times)
            max_response_time = max(response_times)
        else:
            avg_response_time = min_response_time = max_response_time = 0
            
        throughput = len(messages_batch) / total_time if total_time > 0 else 0
        error_rate = failed_requests / len(messages_batch) if len(messages_batch) > 0 else 0
        
        return BenchmarkResult(
            test_name="LLM Gateway Load Test",
            requests_sent=len(messages_batch),
            successful_requests=successful_requests,
            failed_requests=failed_requests,
            total_time=total_time,
            avg_response_time=avg_response_time,
            min_response_time=min_response_time,
            max_response_time=max_response_time,
            throughput=throughput,
            error_rate=error_rate,
            response_times=response_times,
            errors=errors
        )


def print_benchmark_results(result: BenchmarkResult):
    """Pretty print benchmark results"""
    print(f"\n{'='*60}")
    print(f"BENCHMARK RESULTS: {result.test_name}")
    print(f"{'='*60}")
    print(f"Requests Sent:        {result.requests_sent:,}")
    print(f"Successful:           {result.successful_requests:,}")
    print(f"Failed:               {result.failed_requests:,}")
    print(f"Error Rate:           {result.error_rate:.2%}")
    print(f"Total Time:           {result.total_time:.2f}s")
    print(f"Throughput:           {result.throughput:.2f} RPS")
    print(f"Avg Response Time:    {result.avg_response_time:.3f}s")
    print(f"Min Response Time:    {result.min_response_time:.3f}s")
    print(f"Max Response Time:    {result.max_response_time:.3f}s")
    
    if result.errors:
        print(f"\nTOP ERRORS:")
        for i, error in enumerate(result.errors[:5]):  # Show top 5 errors
            print(f"  {i+1}. {error}")
    
    # Performance classification
    if result.throughput > 10:
        perf_label = "🔥 EXCELLENT"
    elif result.throughput > 5:
        perf_label = "⚡ GOOD"
    elif result.throughput > 1:
        perf_label = "👍 AVERAGE"
    elif result.throughput > 0.1:
        perf_label = "🐌 SLOW"
    else:
        perf_label = "💀 POOR"
    
    print(f"\nPERFORMANCE RATING: {perf_label}")
    print(f"{'='*60}\n")


async def run_comprehensive_benchmark(base_url: str = "http://localhost:8080"):
    """Run comprehensive benchmark suite"""
    print("🚀 Starting DeepSearchStack Comprehensive Benchmark Suite")
    print("="*60)
    
    async with DeepSearchBenchmark(base_url) as benchmark:
        
        # Crawler Benchmark
        crawl_urls = [
            "https://example.com",
            "https://httpbin.org/html", 
            "https://quotes.toscrape.com/",
            "https://books.toscrape.com/",
            "https://httpbin.org/json",
            "https://example.com",
            "https://httpbin.org/robots.txt",
            "https://quotes.toscrape.com/page/1/",
            "https://example.com",
            "https://httpbin.org/xml"
        ] * 3  # 30 total requests
        
        crawl_result = await benchmark.crawl_benchmark(crawl_urls, concurrency=10)
        print_benchmark_results(crawl_result)
        
        # Search Benchmark
        search_queries = [
            "What is artificial intelligence?",
            "Latest developments in quantum computing",
            "How does machine learning work?",
            "Benefits of renewable energy",
            "Climate change solutions",
            "Advantages of distributed systems",
            "Future of space exploration",
            "Impact of technology on society",
            "History of computer science",
            "Recent advances in biotechnology"
        ] * 2  # 20 total requests
        
        search_result = await benchmark.search_benchmark(search_queries, concurrency=5)
        print_benchmark_results(search_result)
        
        # LLM Benchmark
        llm_messages_batch = [
            [{"role": "user", "content": f"What are the benefits of Python programming? Question #{i}"}]
            for i in range(1, 15)  # 15 total requests
        ]
        
        llm_result = await benchmark.llm_benchmark(llm_messages_batch, "gemini", concurrency=3)
        print_benchmark_results(llm_result)
        
        # Final summary
        print("🎯 BENCHMARK SUMMARY")
        print("="*60)
        total_requests = crawl_result.requests_sent + search_result.requests_sent + llm_result.requests_sent
        total_successful = crawl_result.successful_requests + search_result.successful_requests + llm_result.successful_requests
        total_failed = crawl_result.failed_requests + search_result.failed_requests + llm_result.failed
        total_time = max(crawl_result.total_time, search_result.total_time, llm_result.total_time)
        overall_throughput = total_requests / total_time if total_time > 0 else 0
        
        print(f"Total Requests:       {total_requests:,}")
        print(f"Successful:           {total_successful:,}")
        print(f"Failed:               {total_failed:,}")
        print(f"Overall Success Rate: {total_successful/total_requests:.2% if total_requests > 0 else 0:.2%}")
        print(f"Combined Throughput:  {overall_throughput:.2f} RPS")
        print("="*60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DeepSearchStack Benchmark Suite")
    parser.add_argument("--base-url", type=str, default="http://localhost:8080", 
                       help="Base URL for API endpoints")
    parser.add_argument("--quick", action="store_true", 
                       help="Run a quicker version of the benchmark")
    
    args = parser.parse_args()
    
    print(f"Starting benchmarks with base URL: {args.base_url}")
    
    if args.quick:
        # Quick benchmark version
        async def quick_benchmark():
            async with DeepSearchBenchmark(args.base_url) as benchmark:
                # Just run a small subset
                urls = ["https://example.com"] * 3
                result = await benchmark.crawl_benchmark(urls, concurrency=2)
                print_benchmark_results(result)
                
                queries = ["What is AI?"] * 3
                result = await benchmark.search_benchmark(queries, concurrency=2)
                print_benchmark_results(result)
                
        asyncio.run(quick_benchmark())
    else:
        asyncio.run(run_comprehensive_benchmark(args.base_url))