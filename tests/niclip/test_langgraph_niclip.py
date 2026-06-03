#!/usr/bin/env python3
"""Test NiCLIP integration through LangGraph API."""

import requests
import json
import time
import sys

def test_langgraph_api(port=8000):
    """Test the LangGraph-compatible agent service with NiCLIP."""
    base_url = f"http://localhost:{port}"

    print("🤖 Testing Brain Researcher Agent with NiCLIP (LangGraph API)")
    print("=" * 60)

    # Create a thread
    print("\n📋 Creating conversation thread...")
    try:
        response = requests.post(f"{base_url}/threads")
        if response.status_code == 200:
            thread_data = response.json()
            thread_id = thread_data['thread_id']
            print(f"✓ Thread created: {thread_id}")
        else:
            print(f"✗ Failed to create thread: {response.status_code}")
            return
    except Exception as e:
        print(f"✗ Error creating thread: {e}")
        return

    # Test queries
    test_queries = [
        "What concepts are associated with the n-back task?",
        "List tasks that involve working memory",
        "What cognitive process category does face recognition belong to?",
        "Show me tasks related to emotion processing",
        "Compare n-back task and stroop task - what concepts do they share?"
    ]

    for i, query in enumerate(test_queries, 1):
        print(f"\n💬 Test {i}: {query}")
        print("-" * 40)

        try:
            # Send message
            msg_response = requests.post(
                f"{base_url}/threads/{thread_id}/messages",
                json={"role": "user", "content": query}
            )

            if msg_response.status_code != 200:
                print(f"✗ Failed to send message: {msg_response.status_code}")
                continue

            # Run the agent
            run_response = requests.post(
                f"{base_url}/threads/{thread_id}/runs",
                json={"assistant_id": "brain-researcher", "stream": False}
            )

            if run_response.status_code == 200:
                result = run_response.json()

                # Extract the response
                if 'messages' in result:
                    for msg in result['messages']:
                        if msg.get('role') == 'assistant':
                            content = msg.get('content', '')
                            print(f"\n🤖 Response:\n{content[:500]}{'...' if len(content) > 500 else ''}")

                            # Check for tool usage
                            if 'metadata' in msg and 'tools_used' in msg['metadata']:
                                tools = msg['metadata']['tools_used']
                                print(f"\n🔧 Tools used: {', '.join(tools)}")

                # Show any events
                if 'events' in result:
                    tool_events = [e for e in result['events'] if e.get('type') == 'tool_call']
                    if tool_events:
                        print(f"\n📊 Tool calls:")
                        for event in tool_events[:3]:  # Show first 3
                            tool_name = event.get('tool_name', 'unknown')
                            args = event.get('args', {})
                            print(f"  • {tool_name}: {json.dumps(args, indent=2)}")
            else:
                print(f"✗ Failed to run agent: {run_response.status_code}")

        except Exception as e:
            print(f"✗ Error: {e}")

        # Small delay between queries
        time.sleep(1)

    # Test direct tool debug endpoint
    print("\n\n🔧 Direct Tool Test")
    print("-" * 40)

    try:
        response = requests.post(
            f"{base_url}/debug/tool/task_to_concept_mapping",
            json={"args": {"task_name": "emotional faces task", "include_synonyms": True}}
        )

        if response.status_code == 200:
            result = response.json()
            print(f"\nTool: task_to_concept_mapping")
            print(f"Input: emotional faces task")
            print(f"Result:")
            print(json.dumps(result, indent=2))
        else:
            print(f"✗ Tool test failed: {response.status_code}")
    except Exception as e:
        print(f"✗ Error testing tool: {e}")

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    test_langgraph_api(port)