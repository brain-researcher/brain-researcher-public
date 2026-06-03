#!/usr/bin/env python3
"""
Test script to verify agent output logging at each stage.
"""

import json
import time
from pathlib import Path

import requests

from brain_researcher.services.agent.utils.agent_output_collector import (
    AgentOutputCollector,
)


def test_agent_conversation():
    """Test a conversation with the agent and log outputs."""

    # Initialize the output collector
    collector = AgentOutputCollector()
    print(f"Initialized collector with session ID: {collector.session_id}")

    # Test query for connectivity analysis
    query = "Calculate connectivity matrix for the test fMRI data in /app/data/openneuro/ds000114/sub-06/ses-retest/func/sub-06_ses-retest_task-covertverbgeneration_bold.nii.gz"

    print(f"\n📤 Sending query: {query}")

    # Stage 1: Planning
    print("\n🔄 Stage 1: Planning...")
    start_time = time.time()

    # Send request to agent
    try:
        response = requests.post(
            "http://localhost:8000/chat", json={"message": query}, timeout=30
        )

        planning_time = time.time() - start_time

        if response.status_code == 200:
            result = response.json()
            print(f"✅ Got response in {planning_time:.2f}s")

            # Log the planning stage
            collector.collect_tool_execution(
                tool_name="AgentPlanning",
                tool_category="agent",
                input_params={"query": query},
                execute_fn=lambda: result,
            )

            print("📝 Logged planning stage")

            # Display response
            if "response" in result:
                print(f"\n📊 Agent Response:\n{result['response'][:500]}...")
            if "tools_used" in result:
                print(f"\n🛠️ Tools used: {result.get('tools_used', [])}")

        else:
            print(f"❌ Error: {response.status_code}")
            print(response.text)

    except requests.exceptions.Timeout:
        print("⏱️ Request timed out")
    except Exception as e:
        print(f"❌ Error: {e}")

    # Stage 2: Tool Execution (simulate)
    print("\n🔄 Stage 2: Tool Execution...")

    # Simulate connectivity matrix tool execution
    def simulate_connectivity_tool():
        """Simulate connectivity matrix calculation."""
        time.sleep(1)  # Simulate processing
        return {
            "status": "success",
            "output": "connectivity_matrix.npy",
            "shape": [116, 116],
            "metrics": {"mean_connectivity": 0.342, "std_connectivity": 0.156},
        }

    collector.collect_tool_execution(
        tool_name="ConnectivityMatrixTool",
        tool_category="nilearn/connectivity",
        input_params={
            "data_path": "/app/data/openneuro/ds000114/sub-06/ses-retest/func/sub-06_ses-retest_task-covertverbgeneration_bold.nii.gz",
            "atlas": "AAL",
        },
        execute_fn=simulate_connectivity_tool,
    )

    print("📝 Logged tool execution stage")

    # Stage 3: Review/Summary
    print("\n🔄 Stage 3: Review...")

    review_data = {
        "summary": "Successfully calculated connectivity matrix",
        "tools_executed": ["ConnectivityMatrixTool"],
        "outputs_generated": ["connectivity_matrix.npy"],
        "total_time": time.time() - start_time,
    }

    collector.collect_tool_execution(
        tool_name="AgentReview",
        tool_category="agent",
        input_params={"query": query},
        execute_fn=lambda: review_data,
    )

    print("📝 Logged review stage")

    # Get session summary
    print("\n📊 Session Summary:")
    summary = collector.get_session_summary()
    print(json.dumps(summary, indent=2))

    # Check generated files
    print("\n📁 Checking generated log files...")

    base_path = Path("/app/brain_researcher/data/agent_outputs")

    # Check for today's session file
    today = time.strftime("%Y-%m-%d")
    session_file = base_path / "metadata" / "sessions" / f"{today}.jsonl"

    if session_file.exists():
        print(f"✅ Session file exists: {session_file}")
        with open(session_file) as f:
            lines = f.readlines()
            print(f"   Contains {len(lines)} log entries")

            # Show first entry
            if lines:
                first_entry = json.loads(lines[0])
                print("\n   First entry:")
                print(f"   - Tool: {first_entry.get('tool_name')}")
                print(f"   - Category: {first_entry.get('tool_category')}")
                print(f"   - Success: {first_entry.get('success')}")
                print(f"   - Time: {first_entry.get('execution_time', 0):.2f}s")
    else:
        print(f"❌ Session file not found: {session_file}")

    # Check category-specific files
    categories = ["agent", "nilearn/connectivity"]
    for category in categories:
        category_file = base_path / category / "executions.jsonl"
        if category_file.exists():
            print(f"✅ Category file exists: {category_file}")
            with open(category_file) as f:
                lines = f.readlines()
                print(f"   Contains {len(lines)} entries")
        else:
            print(f"⚠️ Category file not found: {category_file}")

    # Test export functionality
    print("\n📤 Testing export functionality...")
    export_file = "/tmp/test_export.jsonl"
    num_exported = collector.export_training_dataset(
        output_file=export_file, filters={"success": True}
    )
    print(f"✅ Exported {num_exported} records to {export_file}")

    return collector.session_id


if __name__ == "__main__":
    print("🚀 Starting agent conversation logging test...")
    session_id = test_agent_conversation()
    print(f"\n✅ Test completed! Session ID: {session_id}")
