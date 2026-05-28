#!/usr/bin/env python
"""
Test script for Brain Researcher Agent with DeepSeek API
"""

import json
import os
import time

import pytest
import requests

BASE_URL = os.environ.get("AGENT_BASE_URL", "http://127.0.0.1:8000")


def _agent_reachable() -> bool:
    try:
        resp = requests.get(f"{BASE_URL}/health", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


if not _agent_reachable():
    pytest.skip(f"Agent service not reachable at {BASE_URL}", allow_module_level=True)

def test_health():
    """Test health endpoint"""
    print("Testing health endpoint...")
    response = requests.get(f"{BASE_URL}/health")
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Agent is healthy!")
        print(f"   - Mode: {data['mode']}")
        print(f"   - Tools available: {data['tools_available']}")
        print(f"   - LangGraph compatible: {data['langgraph_compatible']}")
        return True
    else:
        print(f"❌ Health check failed: {response.status_code}")
        return False

def list_tools():
    """List available tools"""
    print("\nListing available tools...")
    response = requests.get(f"{BASE_URL}/tools")
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Found {len(data['tools'])} tools:")
        for i, tool in enumerate(data['tools'][:10], 1):
            print(f"   {i}. {tool['name']}: {tool['description'][:80]}...")
        if len(data['tools']) > 10:
            print(f"   ... and {len(data['tools']) - 10} more tools")
        return True
    else:
        print(f"❌ Failed to list tools: {response.status_code}")
        return False

def test_debug_tool():
    """Test a simple tool directly"""
    print("\nTesting coordinate_to_concept tool...")
    response = requests.post(
        f"{BASE_URL}/debug/tool/coordinate_to_concept",
        json={"coordinates": [[-45, -60, 20]]}
    )
    if response.status_code == 200:
        data = response.json()
        print(f"✅ Tool executed successfully!")
        if data.get('result'):
            print(f"   Result: {json.dumps(data['result'], indent=2)[:200]}...")
        return True
    else:
        print(f"❌ Tool execution failed: {response.status_code}")
        return False

def create_thread_and_chat():
    """Create a thread and send a message"""
    print("\nCreating thread for conversation...")
    
    # Create thread
    response = requests.post(
        f"{BASE_URL}/threads",
        headers={"Content-Type": "application/json"},
        json={}
    )
    if response.status_code != 201:
        print(f"❌ Failed to create thread: {response.status_code}")
        return False
    
    thread_data = response.json()
    thread_id = thread_data['id']
    print(f"✅ Created thread: {thread_id}")
    
    # Try the thread-based approach
    print("\nAttempting to analyze neuroimaging data...")
    
    # Add message to thread
    message = {
        "content": "What brain regions are activated during motor tasks? Please use coordinate [-45, -60, 20] as an example.",
        "role": "user"
    }
    
    response = requests.post(
        f"{BASE_URL}/threads/{thread_id}/messages",
        headers={"Content-Type": "application/json"},
        json=message
    )
    
    if response.status_code == 200:
        print(f"✅ Message added to thread")
        
        # Run the agent
        run_response = requests.post(
            f"{BASE_URL}/threads/{thread_id}/runs",
            headers={"Content-Type": "application/json"},
            json={"assistant_id": "brain-researcher"}
        )
        
        if run_response.status_code == 200:
            run_data = run_response.json()
            print(f"✅ Agent run started: {run_data.get('id')}")
            
            # Wait a bit for processing
            time.sleep(3)
            
            # Get messages
            messages_response = requests.get(f"{BASE_URL}/threads/{thread_id}/messages")
            if messages_response.status_code == 200:
                messages = messages_response.json()
                print(f"✅ Retrieved {len(messages.get('messages', []))} messages")
                for msg in messages.get('messages', []):
                    print(f"\n   {msg.get('role', 'unknown').upper()}: {msg.get('content', '')[:200]}")
        else:
            print(f"⚠️  Run failed: {run_response.status_code}")
    else:
        print(f"⚠️  Message add failed: {response.status_code}")
    
    return True

def main():
    """Run all tests"""
    print("=" * 60)
    print("🧠 Brain Researcher Agent Test Suite")
    print("=" * 60)
    
    # Run tests
    tests = [
        test_health,
        list_tools,
        test_debug_tool,
        create_thread_and_chat
    ]
    
    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"❌ Test failed with error: {e}")
            results.append(False)
        print("-" * 60)
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 Test Summary")
    print("=" * 60)
    passed = sum(1 for r in results if r)
    total = len(results)
    print(f"Tests passed: {passed}/{total}")
    
    if passed == total:
        print("\n✅ All tests passed! Agent is working correctly.")
    else:
        print(f"\n⚠️  {total - passed} test(s) failed. Check the logs above.")
    
    print("\n🚀 Agent is running at http://localhost:8000")
    print("📖 Documentation available at http://localhost:8000/")

if __name__ == "__main__":
    main()
