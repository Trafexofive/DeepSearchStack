#!/usr/bin/env python3
"""
Test script for the OpenWebUI service
"""

import requests
import time

def test_openwebui():
    # Wait a moment for service to be ready
    print("Testing OpenWebUI service...")
    
    # Health check
    try:
        health_response = requests.get('http://localhost:3000/health', timeout=5)
        print(f"Health check: {health_response.status_code}")
        if health_response.status_code == 200:
            print("OpenWebUI is healthy!")
        else:
            print(f"Health check failed: {health_response.text}")
    except Exception as e:
        print(f"Health check failed: {e}")
        return
    
    # Test accessing the main page
    try:
        response = requests.get('http://localhost:3000', timeout=10)
        print(f"Main page access: {response.status_code}")
        if response.status_code == 200:
            print("OpenWebUI main page is accessible!")
        else:
            print(f"Failed to access main page: {response.text}")
    except Exception as e:
        print(f"Failed to access main page: {e}")

if __name__ == "__main__":
    test_openwebui()