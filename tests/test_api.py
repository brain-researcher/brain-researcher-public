#!/usr/bin/env python3
"""
Test script for Brain Researcher API endpoints
"""

import json

import requests

# Test the orchestrator API
print("Testing Brain Researcher Orchestrator API...")
print("=" * 50)

try:
    # Test health endpoint
    response = requests.get("http://localhost:3001/health")
    print(f"✅ Health check: {response.status_code}")
    if response.status_code == 200:
        print(f"   Response: {response.json()}")
except Exception as e:
    print(f"❌ Health check failed: {e}")

try:
    # Test job submission
    payload = {
        "prompt": "Analyze motor cortex activation",
        "pipeline": "GLM",
        "parameters": {"smoothing": 6},
    }
    response = requests.post("http://localhost:3001/run", json=payload)
    print(f"\n✅ Job submission: {response.status_code}")
    if response.status_code == 200:
        result = response.json()
        print(f"   Job ID: {result.get('job_id', 'N/A')}")
except Exception as e:
    print(f"\n❌ Job submission failed: {e}")

print("\n" + "=" * 50)
print("API test complete!")
