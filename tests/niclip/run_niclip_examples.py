#!/usr/bin/env python3
"""Simple examples of using NiCLIP with the Brain Researcher agent."""

import json

import requests


def run_examples():
    """Run simple examples using the debug endpoint."""
    base_url = "http://localhost:8000"

    print("🧠 Brain Researcher NiCLIP Examples")
    print("=" * 50)
    print("\n✅ Testing task_to_concept_mapping tool directly...\n")

    # Example tasks to test
    test_tasks = [
        ("n-back task", "Classic working memory task"),
        ("stroop task", "Cognitive control and interference"),
        ("emotional faces task", "Emotion processing"),
        ("finger tapping", "Motor control"),
        ("face recognition", "Visual perception"),
        ("language fMRI task paradigm", "Language processing"),
        ("go/no-go task", "Response inhibition"),
        ("gambling task", "Decision making and reward"),
        ("rest", "Resting state baseline"),
        ("2-back", "Working memory variant"),
    ]

    for task_name, description in test_tasks:
        print(f"\n📋 Task: {task_name}")
        print(f"   Description: {description}")

        try:
            # Call the tool
            response = requests.post(
                f"{base_url}/debug/tool/task_to_concept_mapping",
                json={"args": {"task_name": task_name, "include_synonyms": True}},
                timeout=10,
            )

            if response.status_code == 200:
                result = response.json()

                if result and isinstance(result, dict):
                    # Extract data from nested result
                    result_data = result.get("result", {})
                    data = result_data.get("data", {})
                    status = result_data.get("status", "unknown")

                    if status == "success" and data:
                        concepts = data.get("concepts", [])
                        process = data.get("primary_process", "Not mapped")
                        source = data.get("source", "unknown")
                        matched_task = data.get("matched_task", task_name)

                        print(f"   ✓ Status: {status}")
                        if matched_task != task_name:
                            print(f"   → Matched to: {matched_task}")
                        print(
                            f"   → Concepts: {', '.join(concepts) if concepts else 'None'}"
                        )
                        print(f"   → Cognitive Process: {process}")
                        print(f"   → Data Source: {source}")
                    else:
                        error = result_data.get("error", "Unknown error")
                        print(f"   ✗ Status: {status}")
                        print(f"   → Error: {error}")
                else:
                    print(f"   ✗ Invalid response format")
            else:
                print(f"   ✗ HTTP Error: {response.status_code}")

        except Exception as e:
            print(f"   ✗ Exception: {str(e)}")

    # Show statistics
    print("\n" + "=" * 50)
    print("📊 NiCLIP Dataset Info:")
    print("- 88 validated cognitive tasks")
    print("- 148 unique concepts")
    print("- 6 cognitive process categories")
    print("- Based on neuroimaging literature")

    print("\n💡 Notes:")
    print("- Tasks with 'Not mapped' process have concepts without process mappings")
    print("- Some tasks fall back to old classification if not in NiCLIP")
    print("- NiCLIP provides scientifically validated mappings")


if __name__ == "__main__":
    print("Checking if agent service is running...")
    try:
        health = requests.get("http://localhost:8000/health", timeout=2)
        if health.status_code == 200:
            print("✓ Agent service is running\n")
            run_examples()
        else:
            print("✗ Agent service is not healthy")
    except:
        print("✗ Cannot connect to agent service on port 8000")
        print("Please start the service with:")
        print(
            "BR_KG_API_URL=http://localhost:5005 python -m brain_researcher.services.agent.web_service"
        )
