#!/usr/bin/env python3
"""Test tool availability and functionality"""

import requests

API_URL = "http://localhost:8000"

print("Testing Brain Researcher API Tools\n")

# 1. Get available tools
print("1. Fetching available tools...")
tools_response = requests.get(f"{API_URL}/tools")
if tools_response.status_code == 200:
    tools_data = tools_response.json()
    tools = tools_data.get("tools", [])
    print(f"   ✓ Found {len(tools)} tools")
    print("\n   Available tools:")
    for tool in tools[:5]:  # Show first 5
        print(f"   - {tool['name']}: {tool['description'][:60]}...")
    if len(tools) > 5:
        print(f"   ... and {len(tools) - 5} more")
else:
    print(f"   ✗ Failed to fetch tools: {tools_response.status_code}")

# 2. Test thread creation and messaging
print("\n2. Testing conversation flow...")
thread = requests.post(f"{API_URL}/threads").json()
thread_id = thread["id"]
print(f"   ✓ Created thread: {thread_id}")

# 3. Send a message
msg_data = {"role": "user", "content": "What is a 2-back task?"}
msg = requests.post(f"{API_URL}/threads/{thread_id}/messages", json=msg_data).json()
print(f"   ✓ Sent message: '{msg_data['content']}'")

# 4. Create run (get response)
print("\n3. Getting AI response...")
run_data = {"assistant_id": "brain-researcher", "stream": False}
run_response = requests.post(f"{API_URL}/threads/{thread_id}/runs", json=run_data)

if run_response.status_code == 200:
    run_result = run_response.json()
    if run_result.get("last_message"):
        print(f"   ✓ Got response: {run_result['last_message']['content'][:100]}...")
        if run_result["last_message"].get("tool_calls"):
            print(f"   ✓ Tools used: {len(run_result['last_message']['tool_calls'])}")
    else:
        print("   ✗ No response generated")
else:
    print(f"   ✗ Failed to get response: {run_response.status_code}")
    print(f"   Error: {run_response.text}")

print("\nDone!")
