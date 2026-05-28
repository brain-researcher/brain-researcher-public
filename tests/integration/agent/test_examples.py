#!/usr/bin/env python3
"""Quick examples of testing specific tools."""

import json
import os

import pytest
import requests

AGENT_URL = os.environ.get("AGENT_BASE_URL", "http://127.0.0.1:8000")


def _agent_reachable() -> bool:
    try:
        resp = requests.get(f"{AGENT_URL}/healthz", timeout=2)
        return resp.status_code == 200
    except Exception:
        return False


if not _agent_reachable():
    pytest.skip(f"Agent service not reachable at {AGENT_URL}", allow_module_level=True)

# Example test cases to demonstrate
EXAMPLE_TESTS = {
    "task_to_concept_mapping": {
        "name": "Map n-back task",
        "args": {"task_name": "n-back"}
    },
    "find_related_concepts": {
        "name": "Find motor cortex relations", 
        "args": {"concept": "motor cortex", "depth": 2, "limit": 5}
    },
    "glm_analysis": {
        "name": "Basic GLM test",
        "args": {
            "dataset_id": "ds000001",
            "contrasts": {"motor_vs_baseline": [1, -1]}
        }
    },
    "coordinate_to_concept": {
        "name": "Map coordinates",
        "args": {
            "coordinates": [[-42, -22, 54]],
            "radius": 10
        }
    }
}


@pytest.mark.parametrize(
    "tool_name,test_case",
    list(EXAMPLE_TESTS.items()),
    ids=[name for name in EXAMPLE_TESTS.keys()],
)
def test_tool(tool_name, test_case):
    """Test a single tool."""
    resp = requests.post(
        f"{AGENT_URL}/debug/tool/{tool_name}",
        json={"args": test_case["args"]},
        timeout=10,
    )

    assert resp.status_code == 200
    result = resp.json()
    assert "success" in result


def main():
    print("Running example tool tests")
    print("=" * 80)
    
    for tool_name, test_case in EXAMPLE_TESTS.items():
        test_tool(tool_name, test_case)
    
    print("\n" + "=" * 80)
    print("Example tests completed!")
    print("\nTo run comprehensive tests for all tools, execute:")
    print("  python comprehensive_tool_tests.py")


if __name__ == "__main__":
    main()
