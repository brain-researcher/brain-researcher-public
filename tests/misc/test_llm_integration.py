#!/usr/bin/env python3
"""
Test LLM integration with Nilearn tools through the web service.
This tests if Gemini can properly receive and use the tool schemas.
"""

import time

import requests

# Agent service endpoint
AGENT_URL = "http://localhost:8000/act"


def test_tool_discovery():
    """Test if LLM can discover and use Nilearn tools."""

    test_queries = [
        {
            "query": "Extract signals from the motor task fMRI at /app/data/openneuro/ds000114/sub-06/ses-test/func/sub-06_ses-test_task-fingerfootlips_bold.nii.gz using masking and save to /tmp/test_signals.npy",
            "expected_tool": "nifti_masker",
        },
        {
            "query": "Compute functional connectivity matrix from ROI signals with correlation method",
            "expected_tool": "connectivity_matrix",
        },
        {
            "query": "Create a visualization of a statistical map with MNI152 background",
            "expected_tool": "viz_stat_maps",
        },
        {
            "query": "Run GLM analysis on task fMRI data with SPM HRF model",
            "expected_tool": "glm_first_level",
        },
        {
            "query": "Extract ROI signals using AAL atlas from brain imaging data",
            "expected_tool": "roi_extraction",
        },
    ]

    print("=" * 70)
    print("TESTING LLM INTEGRATION WITH NILEARN TOOLS")
    print("=" * 70)

    for i, test in enumerate(test_queries, 1):
        print(f"\n[Test {i}] {test['expected_tool']}")
        print(f"Query: {test['query']}")
        print("-" * 50)

        try:
            # Send request to agent
            response = requests.post(
                AGENT_URL, json={"query": test["query"]}, timeout=30
            )

            if response.status_code == 200:
                result = response.json()

                # Check if the correct tool was selected
                if "selected_tools" in result:
                    tools = result["selected_tools"]
                    print(f"✓ Tools discovered: {len(tools)}")

                    # Display top tools with scores
                    for j, tool in enumerate(tools[:3], 1):
                        print(
                            f"  {j}. {tool.get('name', 'Unknown')} (score: {tool.get('score', 0):.2f})"
                        )
                        if tool.get("name") == test["expected_tool"]:
                            print("     ✓ Expected tool found!")

                        # Show if schema was included
                        if "args_schema" in tool:
                            params = list(
                                tool["args_schema"].get("properties", {}).keys()
                            )[:5]
                            print(f"     Schema params: {', '.join(params)}...")

                # Check execution result
                if "result" in result:
                    exec_result = result["result"]
                    if exec_result.get("status") == "success":
                        print("✓ Execution successful")
                    else:
                        print(
                            f"✗ Execution failed: {exec_result.get('error', 'Unknown error')}"
                        )

            else:
                print(f"✗ Request failed: HTTP {response.status_code}")
                print(f"   Error: {response.text[:200]}")

        except requests.exceptions.RequestException as e:
            print(f"✗ Connection error: {str(e)}")
        except Exception as e:
            print(f"✗ Unexpected error: {str(e)}")

        time.sleep(1)  # Rate limiting


def test_parameter_resolution():
    """Test if LLM can properly resolve parameters with synonyms."""

    print("\n" + "=" * 70)
    print("TESTING PARAMETER RESOLUTION")
    print("=" * 70)

    # Test with parameter synonyms
    test_cases = [
        {
            "query": "Run GLM with TR=2.5 seconds and fwhm smoothing of 6mm",
            "check_params": ["t_r", "smoothing_fwhm"],
        },
        {
            "query": "Extract signals with zscore normalization and highpass filter at 0.01 Hz",
            "check_params": ["standardize", "high_pass"],
        },
    ]

    for i, test in enumerate(test_cases, 1):
        print(f"\n[Param Test {i}]")
        print(f"Query: {test['query']}")
        print(f"Expected params: {test['check_params']}")
        print("-" * 50)

        try:
            response = requests.post(
                AGENT_URL, json={"query": test["query"]}, timeout=30
            )

            if response.status_code == 200:
                result = response.json()

                if "resolved_params" in result:
                    params = result["resolved_params"]
                    print("✓ Parameters resolved:")
                    for param in test["check_params"]:
                        if param in params:
                            print(f"  ✓ {param}: {params[param]}")
                        else:
                            print(f"  ✗ {param}: Not found")
                else:
                    print("✗ No parameters resolved in response")

        except Exception as e:
            print(f"✗ Error: {str(e)}")


def check_service_status():
    """Check if the agent service is running."""
    try:
        response = requests.get("http://localhost:8000/health", timeout=5)
        if response.status_code == 200:
            print("✓ Agent service is running")
            return True
    except:
        pass

    print("✗ Agent service is not responding on port 8000")
    print("  Please ensure the service is running with:")
    print("  python -m brain_researcher.services.agent.web_service")
    return False


if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("LLM NILEARN TOOLS INTEGRATION TEST")
    print("=" * 70)

    # Check service status first
    if not check_service_status():
        print("\nPlease start the agent service first!")
        exit(1)

    # Run tests
    test_tool_discovery()
    test_parameter_resolution()

    print("\n" + "=" * 70)
    print("TEST COMPLETE")
    print("=" * 70)
