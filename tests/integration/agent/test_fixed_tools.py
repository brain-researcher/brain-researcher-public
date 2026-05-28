#!/usr/bin/env python3
"""Test the tools that were fixed to ensure they're working properly."""

import json
import os
from datetime import datetime

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

# Test cases for the fixed tools
FIXED_TOOLS_TESTS = {
    "task_to_concept_mapping": [
        {
            "name": "Basic n-back test",
            "args": {"task_name": "n-back"},
            "expect_success": True
        },
        {
            "name": "Motor task test",
            "args": {"task_name": "finger tapping"},
            "expect_success": True
        }
    ],
    
    "coordinate_to_concept": [
        {
            "name": "Correct format test",
            "args": {"coordinates": [[-42, -22, 54]], "radius": 10},
            "expect_success": True
        },
        {
            "name": "Auto-correction test (single coord)",
            "args": {"coordinates": [-42, -22, 54], "radius": 10},
            "expect_success": True,
            "note": "Should auto-correct to [[x,y,z]]"
        },
        {
            "name": "Multiple coordinates",
            "args": {"coordinates": [[-42, -22, 54], [0, -2, 48]], "radius": 10},
            "expect_success": True
        }
    ],
    
    "graph_query": [
        {
            "name": "Subgraph query",
            "args": {"query_type": "subgraph", "start_node": "motor"},
            "expect_success": True
        },
        {
            "name": "Neighbors query",
            "args": {"query_type": "neighbors", "start_node": "motor"},
            "expect_success": True
        }
    ],
    
    "concept_literature_search": [
        {
            "name": "Single concept search",
            "args": {"concepts": ["working memory"], "max_results": 5},
            "expect_success": True
        },
        {
            "name": "Multi-concept search",
            "args": {"concepts": ["motor", "cortex"], "max_results": 3},
            "expect_success": True
        }
    ],
    
    "find_related_concepts": [
        {
            "name": "Simple concept",
            "args": {"concept": "motor", "depth": 1, "limit": 5},
            "expect_success": True
        }
    ],
    
    "contrast_analysis": [
        {
            "name": "Mock mode test",
            "args": {"z_map_path": "/nonexistent/file.nii.gz", "contrast_name": "motor_vs_baseline"},
            "expect_success": True,
            "note": "Should use mock mode"
        },
        {
            "name": "With coordinates",
            "args": {
                "z_map_path": "/nonexistent/file.nii.gz",
                "contrast_name": "test_contrast",
                "coordinates": [[-42, -22, 54]]
            },
            "expect_success": True
        }
    ],
    
    "brain_similarity": [
        {
            "name": "Correlation test",
            "args": {
                "dataset1": "/fake/map1.nii.gz",
                "dataset2": "/fake/map2.nii.gz",
                "metric": "correlation"
            },
            "expect_success": True
        },
        {
            "name": "Cosine similarity",
            "args": {
                "dataset1": "/fake/map1.nii.gz",
                "dataset2": "/fake/map2.nii.gz",
                "metric": "cosine"
            },
            "expect_success": True
        }
    ],
    
    "glm_analysis": [
        {
            "name": "Simple contrast",
            "args": {
                "dataset_id": "ds000001",
                "contrasts": {"motor_vs_baseline": [1, -1]}
            },
            "expect_success": True
        },
        {
            "name": "Multiple contrasts",
            "args": {
                "dataset_id": "ds000030",
                "contrasts": {
                    "face_vs_house": [1, -1, 0],
                    "face_vs_baseline": [1, 0, -1]
                }
            },
            "expect_success": True
        }
    ],
    
    "encoding_model": [
        {
            "name": "Visual encoding",
            "args": {
                "dataset_id": "ds000001",
                "feature_type": "visual",
                "model_type": "ridge"
            },
            "expect_success": True
        }
    ]
}


def _run_tool(tool_name, test_case):
    resp = requests.post(
        f"{AGENT_URL}/debug/tool/{tool_name}",
        json={"args": test_case["args"]},
        timeout=10,
    )

    result = {
        "test_name": test_case["name"],
        "expect_success": test_case.get("expect_success", True),
        "note": test_case.get("note", ""),
        "status_code": resp.status_code,
        "success": False,
        "passed": False,
        "error": None,
    }

    if resp.status_code != 200:
        result["error"] = f"HTTP {resp.status_code}"
        return result

    resp_data = resp.json()
    result["success"] = resp_data.get("success", False)
    result["has_data"] = bool(resp_data.get("result", {}).get("data"))
    result["error"] = resp_data.get("result", {}).get("error")
    result["passed"] = result["success"] == result["expect_success"]
    return result


_PARAMS = [
    (tool_name, test_case)
    for tool_name, test_cases in FIXED_TOOLS_TESTS.items()
    for test_case in test_cases
]


@pytest.mark.parametrize(
    "tool_name,test_case",
    _PARAMS,
    ids=[f"{tool}-{case['name']}" for tool, case in _PARAMS],
)
def test_tool(tool_name, test_case):
    """Test a single tool with given test case."""
    result = _run_tool(tool_name, test_case)
    assert result["status_code"] == 200
    assert result["passed"], result.get("error")


def main():
    """Run tests for all fixed tools."""
    print(f"Testing fixed tools at {datetime.now()}")
    print("=" * 80)
    
    all_results = {}
    summary_stats = {
        "total_tests": 0,
        "passed": 0,
        "failed": 0
    }
    
    # Test each fixed tool
    for tool_name, test_cases in FIXED_TOOLS_TESTS.items():
        print(f"\n{'='*60}")
        print(f"Testing {tool_name}")
        print(f"{'='*60}")
        
        tool_results = []
        
        for test_case in test_cases:
            print(f"\n{test_case['name']}")
            if test_case.get('note'):
                print(f"  Note: {test_case['note']}")
            
            result = _run_tool(tool_name, test_case)
            tool_results.append(result)
            
            summary_stats["total_tests"] += 1
            
            if result["passed"]:
                print(f"  ✅ PASSED", end="")
                if "concepts_found" in result:
                    print(f" - Found {result['concepts_found']} concepts")
                elif "mappings_found" in result:
                    print(f" - Found {result['mappings_found']} mappings")
                elif "nodes_found" in result:
                    print(f" - Found {result['nodes_found']} nodes")
                elif "papers_found" in result:
                    print(f" - Found {result['papers_found']} papers")
                else:
                    print()
                summary_stats["passed"] += 1
            else:
                print(f"  ❌ FAILED: {result.get('error', 'Unknown error')}")
                summary_stats["failed"] += 1
        
        all_results[tool_name] = tool_results
    
    # Print summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Total Tests: {summary_stats['total_tests']}")
    print(f"Passed: {summary_stats['passed']}")
    print(f"Failed: {summary_stats['failed']}")
    print(f"Success Rate: {summary_stats['passed']/summary_stats['total_tests']*100:.1f}%")
    
    # List any failures
    if summary_stats['failed'] > 0:
        print("\nFailed Tests:")
        for tool_name, results in all_results.items():
            for result in results:
                if not result.get('passed', False):
                    print(f"  - {tool_name}: {result['test_name']} - {result.get('error', 'Unknown')}")
    
    # Save results
    with open("fixed_tools_test_results.json", "w") as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "summary": summary_stats,
            "detailed_results": all_results
        }, f, indent=2)
    
    print(f"\nDetailed results saved to fixed_tools_test_results.json")


if __name__ == "__main__":
    main()
