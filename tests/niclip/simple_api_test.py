#!/usr/bin/env python3
"""
Simple ways to call the NiCLIP service
"""


import requests

# The service runs on port 8000
BASE_URL = "http://localhost:8000"

print("🔍 How to Call the NiCLIP Service\n")

# Method 1: Direct Tool Call (Simplest)
print("1️⃣ METHOD 1: Direct Tool Call")
print("-" * 40)
print("Code:")
print(
    """
response = requests.post(
    "http://localhost:8000/debug/tool/task_to_concept_mapping",
    json={"args": {"task_name": "n-back task"}}
)
result = response.json()
"""
)

# Actually run it
response = requests.post(
    f"{BASE_URL}/debug/tool/task_to_concept_mapping",
    json={"args": {"task_name": "n-back task"}},
)
result = response.json()

print("\nResult:")
if result.get("result", {}).get("data"):
    data = result["result"]["data"]
    print(f"Task: {data['task_name']}")
    print(f"Concepts: {data['concepts']}")
    print(f"Source: {data['source']}")

# Method 2: Using curl in terminal
print("\n\n2️⃣ METHOD 2: Using curl in Terminal")
print("-" * 40)
print("Run this command:")
print(
    """
curl -X POST http://localhost:8000/debug/tool/task_to_concept_mapping \\
  -H "Content-Type: application/json" \\
  -d '{"args": {"task_name": "stroop task"}}' | python -m json.tool
"""
)

# Method 3: LangGraph API (for conversations)
print("\n\n3️⃣ METHOD 3: LangGraph API (Stateful)")
print("-" * 40)
print("Code:")
print(
    """
# Create thread
thread_resp = requests.post("http://localhost:8000/threads",
                           headers={"Content-Type": "application/json"})
thread_id = thread_resp.json()["thread_id"]

# Send message
requests.post(f"http://localhost:8000/threads/{thread_id}/messages",
              json={"role": "user", "content": "What is n-back task?"})

# Run agent
run_resp = requests.post(f"http://localhost:8000/threads/{thread_id}/runs",
                        json={"assistant_id": "brain-researcher"})
"""
)

# Actually create a thread
thread_resp = requests.post(
    f"{BASE_URL}/threads", headers={"Content-Type": "application/json"}
)
if thread_resp.status_code in [200, 201]:
    thread_id = thread_resp.json()["thread_id"]
    print(f"\nCreated thread: {thread_id}")

# Method 4: Batch processing
print("\n\n4️⃣ METHOD 4: Batch Processing Multiple Tasks")
print("-" * 40)
print("Processing multiple tasks:")

tasks = ["n-back task", "stroop task", "emotional faces task"]
for task in tasks:
    response = requests.post(
        f"{BASE_URL}/debug/tool/task_to_concept_mapping",
        json={"args": {"task_name": task}},
    )
    if response.status_code == 200:
        data = response.json().get("result", {}).get("data", {})
        concepts = data.get("concepts", [])
        print(f"\n{task}: {', '.join(concepts[:2])}...")

# Show available endpoints
print("\n\n5️⃣ AVAILABLE ENDPOINTS:")
print("-" * 40)
print("GET  /health              - Check service health")
print("GET  /tools               - List all available tools")
print("POST /debug/tool/<name>   - Call a specific tool")
print("POST /threads             - Create conversation thread")
print("POST /threads/<id>/runs   - Run agent on thread")

print("\n\n📝 QUICK TERMINAL COMMANDS:")
print("-" * 40)
print("# Check if service is running:")
print("curl http://localhost:8000/health")
print("\n# Get task concepts:")
print(
    'curl -X POST http://localhost:8000/debug/tool/task_to_concept_mapping -H "Content-Type: application/json" -d \'{"args": {"task_name": "n-back task"}}\' | jq .'
)
print("\n# List all tools:")
print("curl http://localhost:8000/tools | jq '.tools[].name'")
