#!/usr/bin/env python3
"""Test NiCLIP integration through the agent service."""

import time

import requests


def test_agent_service(port=8000):
    """Test the agent service with NiCLIP examples."""
    base_url = f"http://localhost:{port}"

    print("🤖 Testing Brain Researcher Agent with NiCLIP")
    print("=" * 60)

    # Check if service is running
    try:
        response = requests.get(f"{base_url}/health", timeout=2)
        if response.status_code == 200:
            print(f"✓ Agent service is running on port {port}")
        else:
            print(f"✗ Agent service not healthy on port {port}")
            return
    except:
        print(f"✗ Cannot connect to agent service on port {port}")
        print("  Please start the service with:")
        print(
            f"  BR_KG_API_URL=http://localhost:5005 python -m brain_researcher.services.agent.web_service --port {port}"
        )
        return

    # Test 1: Direct tool invocation
    print("\n📋 Test 1: Direct Tool Invocation")
    print("-" * 40)

    try:
        response = requests.post(
            f"{base_url}/debug/tool/task_to_concept_mapping",
            json={"args": {"task_name": "n-back task", "include_synonyms": True}},
            timeout=10,
        )

        if response.status_code == 200:
            result = response.json()
            print("\nn-back task mapping:")
            print(f"  Status: {result.get('status')}")
            if result.get("data"):
                data = result["data"]
                print(f"  Concepts: {data.get('concepts', [])}")
                print(f"  Primary Process: {data.get('primary_process', 'N/A')}")
                print(f"  Data Source: {data.get('source', 'N/A')}")
        else:
            print(f"  Error: {response.status_code}")
    except Exception as e:
        print(f"  Error: {str(e)}")

    # Test 2: Chat queries
    print("\n\n💬 Test 2: Chat Queries")
    print("-" * 40)

    test_queries = [
        "What concepts are associated with the n-back task?",
        "List tasks related to working memory",
        "What cognitive process does face recognition belong to?",
        "Show me emotion-related tasks",
    ]

    for query in test_queries:
        print(f"\nQuery: {query}")
        try:
            response = requests.post(
                f"{base_url}/chat",
                json={"message": query, "thread_id": f"test_{int(time.time())}"},
                timeout=30,
            )

            if response.status_code == 200:
                result = response.json()
                if result.get("response"):
                    # Extract and clean the response
                    resp_text = result["response"]
                    # Print first 200 chars of response
                    print(
                        f"Response: {resp_text[:200]}{'...' if len(resp_text) > 200 else ''}"
                    )

                    # Check if tools were used
                    if "tools_used" in result:
                        print(f"Tools used: {result['tools_used']}")
            else:
                print(f"Error: {response.status_code}")
        except Exception as e:
            print(f"Error: {str(e)}")

    # Test 3: Multiple tool test
    print("\n\n🔧 Test 3: Complex Query (Multiple Tools)")
    print("-" * 40)

    complex_query = "Compare the concepts between n-back task and stroop task. What cognitive processes do they involve?"

    print(f"Query: {complex_query}")
    try:
        response = requests.post(
            f"{base_url}/chat",
            json={
                "message": complex_query,
                "thread_id": f"test_complex_{int(time.time())}",
            },
            timeout=30,
        )

        if response.status_code == 200:
            result = response.json()
            if result.get("response"):
                print(f"\nResponse:\n{result['response']}")

                # Show tool usage details if available
                if "tool_calls" in result:
                    print("\nTool calls made:")
                    for tool in result["tool_calls"]:
                        print(f"  • {tool}")
        else:
            print(f"Error: {response.status_code}")
    except Exception as e:
        print(f"Error: {str(e)}")


if __name__ == "__main__":
    import sys

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    test_agent_service(port)
