#!/usr/bin/env python3
"""
Test script for the crawler service
"""

import requests
import time

def test_crawler():
    # Wait a moment for service to be ready
    print("Testing crawler service...")
    
    # Health check
    try:
        health_response = requests.get('http://localhost:8003/health', timeout=5)
        print(f"Health check: {health_response.status_code}")
        print(f"Health response: {health_response.json()}")
    except Exception as e:
        print(f"Health check failed: {e}")
        return
    
    # Test crawling
    test_urls = [
        "https://httpbin.org/html",
        "https://example.com"
    ]
    
    for url in test_urls:
        print(f"\nTesting crawl for: {url}")
        try:
            response = requests.post('http://localhost:8003/crawl', 
                                   json={'url': url, 'extraction_strategy': 'llm'},
                                   timeout=30)
            print(f"Crawl status: {response.status_code}")
            if response.status_code == 200:
                data = response.json()
                print(f"Success: {data['success']}")
                if data['success']:
                    content_preview = data['content'][:200] + "..." if len(data['content']) > 200 else data['content']
                    print(f"Content preview: {content_preview}")
                else:
                    print(f"Error: {data.get('error_message', 'Unknown error')}")
            else:
                print(f"Error response: {response.text}")
        except Exception as e:
            print(f"Crawl failed: {e}")

if __name__ == "__main__":
    test_crawler()