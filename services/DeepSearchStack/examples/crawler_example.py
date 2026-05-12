#!/usr/bin/env python3
"""
Example usage of the crawler service
"""

import requests
import json

def crawl_example():
    print("=== Crawler Service Example ===\n")
    
    # Example 1: Simple crawl with LLM extraction
    print("1. Crawling example.com with LLM extraction:")
    response = requests.post('http://localhost:8003/crawl', 
                           json={
                               'url': 'https://example.com',
                               'extraction_strategy': 'llm'
                           })
    
    if response.status_code == 200:
        data = response.json()
        print(f"Success: {data['success']}")
        if data['success']:
            print(f"Content length: {len(data['content'])} characters")
            print(f"Content preview: {data['content'][:200]}...")
        else:
            print(f"Error: {data.get('error_message', 'Unknown error')}")
    else:
        print(f"Request failed with status code: {response.status_code}")
    
    print("\n" + "="*50 + "\n")
    
    # Example 2: CSS selector extraction
    print("2. Crawling with CSS selector extraction:")
    response = requests.post('http://localhost:8003/crawl', 
                           json={
                               'url': 'https://httpbin.org/html',
                               'extraction_strategy': 'json_css',
                               'css_selector': 'h1'
                           })
    
    if response.status_code == 200:
        data = response.json()
        print(f"Success: {data['success']}")
        if data['success']:
            print(f"Content preview: {data['content'][:200]}...")
        else:
            print(f"Error: {data.get('error_message', 'Unknown error')}")
    else:
        print(f"Request failed with status code: {response.status_code}")

if __name__ == "__main__":
    crawl_example()