#!/usr/bin/env python3
"""
Simple test to verify LLM can process queries with the new Nilearn tools.
Tests the /act endpoint to see if Gemini receives tool schemas.
"""

import json

import requests


def test_llm_tool_selection():
    """Test if LLM sees and can select Nilearn tools."""

    queries = [
        "I need to extract time series from fMRI data with smoothing",
        "Compute connectivity matrix from brain signals",
        "Run GLM analysis on motor task data",
        "Visualize a statistical map",
        "Extract ROI signals using AAL atlas",
    ]

    print("=" * 70)
    print("TESTING LLM TOOL SELECTION WITH NILEARN TOOLS")
    print("=" * 70)

    for query in queries:
        print(f"\nQuery: {query}")
        print("-" * 50)

        try:
            response = requests.post(
                "http://localhost:8000/act", json={"query": query}, timeout=10
            )

            print(f"Status: {response.status_code}")

            if response.status_code == 200:
                try:
                    result = response.json()

                    # Check what was returned
                    if "action" in result:
                        print(f"✓ Action: {result['action']}")

                    if "tool" in result:
                        print(f"✓ Tool selected: {result['tool']}")

                    if "params" in result:
                        params = result.get("params", {})
                        print(f"✓ Parameters: {list(params.keys())[:5]}...")

                    if "error" in result:
                        print(f"✗ Error: {result['error']}")

                except json.JSONDecodeError:
                    print(f"Response text: {response.text[:200]}")
            else:
                error_text = response.text[:200] if response.text else "No error text"
                print(f"✗ HTTP {response.status_code}: {error_text}")

        except Exception as e:
            print(f"✗ Exception: {str(e)}")


if __name__ == "__main__":
    test_llm_tool_selection()
