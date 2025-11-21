#!/usr/bin/env python3
"""
DeepSearchStack - Base Benchmark Suite Runner
"""

import argparse
import asyncio
import json
import os
from datetime import datetime
import sys
import os
# Add the benchmarks directory to the path so we can import load_test
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from load_test import DeepSearchBenchmark, print_benchmark_results


async def run_benchmarks(base_url: str, output_dir: str = "./reports", quick: bool = False):
    """Run the complete benchmark suite"""
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Determine request counts based on quick mode
    num_requests = 10 if quick else 50
    concurrency = 3 if quick else 10
    
    async with DeepSearchBenchmark(base_url) as benchmark:
        
        results = {}
        
        # 1. Crawler Performance Test
        print("🔍 Running Crawler Performance Test...")
        crawl_urls = [
            "https://example.com",
            "https://httpbin.org/html", 
            "https://quotes.toscrape.com/",
            "https://books.toscrape.com/",
            "https://httpbin.org/json",
        ] * (num_requests // 5 + 1)
        crawl_urls = crawl_urls[:num_requests]  # Trim to exact count
        
        crawl_result = await benchmark.crawl_benchmark(crawl_urls, concurrency=max(1, concurrency//2))
        print_benchmark_results(crawl_result)
        results['crawler'] = crawl_result.__dict__
        
        # 2. Search Performance Test  
        print("\n🔍 Running Search Performance Test...")
        search_queries = [
            "artificial intelligence",
            "machine learning", 
            "quantum computing",
            "renewable energy",
            "climate change",
            "distributed systems",
            "space exploration",
            "biotechnology"
        ] * (num_requests // 8 + 1)
        search_queries = search_queries[:num_requests]  # Trim to exact count
        
        search_result = await benchmark.search_benchmark(search_queries, concurrency=max(1, concurrency//3))
        print_benchmark_results(search_result)
        results['search'] = search_result.__dict__
        
        # 3. LLM Performance Test (if service is available)
        try:
            print("\n🧠 Running LLM Gateway Performance Test...")
            llm_messages_batch = [
                [{"role": "user", "content": f"What are the benefits of Python for AI? Message #{i}"}]
                for i in range(1, min(15, num_requests//3 + 2))  # Limit to avoid quota issues
            ]
            
            llm_result = await benchmark.llm_benchmark(llm_messages_batch, concurrency=max(1, concurrency//5))
            print_benchmark_results(llm_result)
            results['llm_gateway'] = llm_result.__dict__
        except Exception as e:
            print(f"⚠️  LLM Gateway test skipped due to: {e}")
            results['llm_gateway'] = {
                'test_skipped': True,
                'reason': str(e)
            }
        
        # Save combined results
        results_file = os.path.join(output_dir, f"benchmark_results_{timestamp}.json")
        with open(results_file, 'w') as f:
            json.dump(results, f, indent=2, default=str)
        
        print(f"\n💾 Results saved to: {results_file}")
        
        # Print summary
        total_requests = (
            results['crawler']['requests_sent'] + 
            results['search']['requests_sent'] + 
            results['llm_gateway'].get('requests_sent', 0)
        )
        
        successful_requests = (
            results['crawler']['successful_requests'] + 
            results['search']['successful_requests'] + 
            results['llm_gateway'].get('successful_requests', 0)
        )
        
        total_time = max(
            results['crawler']['total_time'],
            results['search']['total_time'], 
            results['llm_gateway'].get('total_time', 0)
        )
        
        overall_throughput = total_requests / total_time if total_time > 0 else 0
        overall_error_rate = (total_requests - successful_requests) / total_requests if total_requests > 0 else 0
        
        print(f"\n{'='*60}")
        print(f"SUMMARY")
        print(f"{'='*60}")
        print(f"Total Requests:      {total_requests}")
        print(f"Successful:          {successful_requests}")
        print(f"Failed:              {total_requests - successful_requests}")
        print(f"Success Rate:        {(successful_requests/total_requests)*100:.1f}%")
        print(f"Total Duration:      {total_time:.2f}s")
        print(f"Overall Throughput:  {overall_throughput:.2f} RPS")
        print(f"Overall Error Rate:  {overall_error_rate:.2%}")
        print(f"{'='*60}")


def main():
    parser = argparse.ArgumentParser(description="DeepSearchStack Base Benchmark Suite")
    parser.add_argument(
        "--base-url", 
        type=str, 
        default="http://localhost:8080",
        help="Base URL for the API endpoints (default: http://localhost:8080)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="./reports",
        help="Directory to save benchmark reports (default: ./reports)"
    )
    parser.add_argument(
        "--quick", 
        action="store_true",
        help="Run a quick version of the benchmark (fewer requests)"
    )
    
    args = parser.parse_args()
    
    print(f"🚀 Starting DeepSearchStack Base Benchmark Suite")
    print(f"🎯 Target URL: {args.base_url}")
    print(f"📁 Output directory: {args.output_dir}")
    print(f"⚡ Quick mode: {'Yes' if args.quick else 'No'}")
    print("-" * 60)
    
    asyncio.run(run_benchmarks(args.base_url, args.output_dir, args.quick))


if __name__ == "__main__":
    main()