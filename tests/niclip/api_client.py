#!/usr/bin/env python3
"""
NiCLIP API Client Examples
Shows different ways to call the Brain Researcher service
"""

import json

import requests

BASE_URL = "http://localhost:8000"


def example_1_direct_tool_call():
    """Direct tool invocation - fastest for single queries"""
    print("1️⃣ Direct Tool Call:")
    response = requests.post(
        f"{BASE_URL}/debug/tool/task_to_concept_mapping",
        json={"args": {"task_name": "n-back task", "include_synonyms": True}},
    )
    result = response.json()
    print(json.dumps(result, indent=2))
    return result


def example_2_chat_interface():
    """Chat interface - for natural language queries"""
    print("\n2️⃣ Chat Interface:")
    response = requests.post(
        f"{BASE_URL}/chat",
        json={
            "message": "What are the concepts for n-back task?",
            "thread_id": "test_thread_123",
        },
    )
    if response.status_code == 200:
        result = response.json()
        print(f"Response: {result.get('response', 'No response')}")
    else:
        print(f"Error: {response.status_code}")


def example_3_langgraph_api():
    """LangGraph-compatible API - for stateful conversations"""
    print("\n3️⃣ LangGraph API:")

    # Create thread
    thread_resp = requests.post(f"{BASE_URL}/threads")
    thread_id = thread_resp.json()["thread_id"]
    print(f"Created thread: {thread_id}")

    # Add message
    requests.post(
        f"{BASE_URL}/threads/{thread_id}/messages",
        json={"role": "user", "content": "Compare n-back and stroop tasks"},
    )

    # Run agent
    run_resp = requests.post(
        f"{BASE_URL}/threads/{thread_id}/runs",
        json={"assistant_id": "brain-researcher", "stream": False},
    )

    if run_resp.status_code == 200:
        result = run_resp.json()
        # Extract assistant response
        for msg in result.get("messages", []):
            if msg["role"] == "assistant":
                print(f"Assistant: {msg['content'][:200]}...")


def example_4_batch_processing():
    """Batch processing multiple tasks"""
    print("\n4️⃣ Batch Processing:")

    tasks = [
        "n-back task",
        "stroop task",
        "emotional faces task",
        "language processing fMRI task paradigm",
        "finger tapping",
    ]

    results = {}
    for task in tasks:
        response = requests.post(
            f"{BASE_URL}/debug/tool/task_to_concept_mapping",
            json={"args": {"task_name": task}},
        )
        if response.status_code == 200:
            data = response.json()
            if data.get("result", {}).get("data"):
                task_data = data["result"]["data"]
                results[task] = {
                    "concepts": task_data.get("concepts", []),
                    "process": task_data.get("primary_process", "N/A"),
                    "source": task_data.get("source", "unknown"),
                }

    # Display results
    for task, info in results.items():
        print(f"\n{task}:")
        print(f"  Concepts: {', '.join(info['concepts'][:3])}")
        print(f"  Process: {info['process']}")
        print(f"  Source: {info['source']}")


def example_5_websocket_streaming():
    """Example of streaming responses (if implemented)"""
    print("\n5️⃣ Streaming (WebSocket) - Not implemented yet")
    print("  This would allow real-time streaming of agent responses")


if __name__ == "__main__":
    print("🧠 NiCLIP API Client Examples")
    print("=" * 50)

    # Check if service is running
    try:
        health = requests.get(f"{BASE_URL}/health", timeout=2)
        if health.status_code == 200:
            print("✅ Service is running\n")

            example_1_direct_tool_call()
            example_2_chat_interface()
            example_3_langgraph_api()
            example_4_batch_processing()
            example_5_websocket_streaming()
        else:
            print("❌ Service is not healthy")
    except:
        print("❌ Cannot connect to service")
        print("Start it with: br serve agent")
