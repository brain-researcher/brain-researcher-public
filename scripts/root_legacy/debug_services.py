#!/usr/bin/env python3
"""Legacy debug script for testing individual services and tools."""

import json
import requests
from datetime import datetime

# Base URLs
AGENT_URL = "http://localhost:8000"
BR_KG_URL = "http://localhost:5005"

def test_service_health():
    """Test if services are running"""
    print("=" * 50)
    print("SERVICE HEALTH CHECKS")
    print("=" * 50)

    # Test Agent service
    try:
        resp = requests.get(f"{AGENT_URL}/health")
        if resp.status_code == 200:
            print(f"✅ Agent Service: {resp.json()}")
        else:
            print(f"❌ Agent Service: Status {resp.status_code}")
    except Exception as e:
        print(f"❌ Agent Service: {e}")

    # Test BR-KG service
    try:
        resp = requests.get(f"{BR_KG_URL}/health")
        if resp.status_code == 200:
            print(f"✅ BR-KG Service: {resp.json()}")
        else:
            print(f"❌ BR-KG Service: Status {resp.status_code}")
    except Exception as e:
        print(f"❌ BR-KG Service: {e}")

    print()

def test_tool_directly(tool_name, args):
    """Test a specific tool through the debug endpoint"""
    print(f"Testing tool: {tool_name}")
    print(f"Arguments: {json.dumps(args, indent=2)}")

    try:
        resp = requests.post(
            f"{AGENT_URL}/debug/tool/{tool_name}",
            json={"args": args}
        )

        if resp.status_code == 200:
            result = resp.json()
            print(f"✅ Success: {result.get('success')}")
            print(f"Result: {json.dumps(result.get('result'), indent=2)}")
        else:
            print(f"❌ Error: Status {resp.status_code}")
            print(resp.text)
    except Exception as e:
        print(f"❌ Exception: {e}")

    print("-" * 50)

def test_preprocessing():
    """Test preprocessing capabilities"""
    print("=" * 50)
    print("TESTING PREPROCESSING")
    print("=" * 50)

    # Test if dataset exists
    test_tool_directly("list_datasets", {})

    # Test preprocessing on a dataset
    test_tool_directly("preprocess_dataset", {
        "dataset_id": "ds000001",
        "task": "motor"
    })

def test_glm_analysis():
    """Test GLM analysis"""
    print("=" * 50)
    print("TESTING GLM ANALYSIS")
    print("=" * 50)

    # Test GLM on a dataset
    test_tool_directly("glm_analysis", {
        "dataset_id": "ds000001",
        "contrasts": {
            "motor_vs_baseline": [1, -1]
        },
        "task": "motor"
    })

def test_encoding_model():
    """Test encoding model"""
    print("=" * 50)
    print("TESTING ENCODING MODEL")
    print("=" * 50)

    test_tool_directly("encoding_model", {
        "dataset_id": "ds000001",
        "feature_type": "visual",
        "model_type": "ridge"
    })

def test_coordinate_lookup():
    """Test coordinate to concept mapping"""
    print("=" * 50)
    print("TESTING COORDINATE LOOKUP")
    print("=" * 50)

    test_tool_directly("coordinate_to_concept", {
        "coordinates": [-42, -22, 54],
        "radius": 10
    })

def test_br_kg_query():
    """Test direct BR-KG queries"""
    print("=" * 50)
    print("TESTING BR_KG DIRECT QUERIES")
    print("=" * 50)

    # Test graph stats
    try:
        resp = requests.get(f"{BR_KG_URL}/graph/stats")
        if resp.status_code == 200:
            print(f"✅ Graph Stats: {json.dumps(resp.json(), indent=2)}")
        else:
            print(f"❌ Graph Stats: Status {resp.status_code}")
    except Exception as e:
        print(f"❌ Graph Stats: {e}")

    print()

    # Test concept search
    try:
        resp = requests.get(f"{BR_KG_URL}/concepts/search?q=motor")
        if resp.status_code == 200:
            results = resp.json()
            print(f"✅ Concept Search (motor): Found {len(results)} results")
            if results:
                print(f"   First result: {results[0]}")
        else:
            print(f"❌ Concept Search: Status {resp.status_code}")
    except Exception as e:
        print(f"❌ Concept Search: {e}")

def test_full_agent_query():
    """Test a full agent query"""
    print("=" * 50)
    print("TESTING FULL AGENT QUERY")
    print("=" * 50)

    query = "What is the n-back task?"

    try:
        resp = requests.post(
            f"{AGENT_URL}/query",
            json={"query": query}
        )

        if resp.status_code == 200:
            result = resp.json()
            print(f"✅ Query processed successfully")
            print(f"Selected tools: {result.get('selected_tools')}")
            print(f"Synthesis: {result.get('synthesis', {}).get('summary')}")
        else:
            print(f"❌ Error: Status {resp.status_code}")
            print(resp.text)
    except Exception as e:
        print(f"❌ Exception: {e}")

def main():
    """Run all tests"""
    print(f"Starting service debug tests at {datetime.now()}")
    print()

    # 1. Check service health
    test_service_health()

    # 2. Test individual tools
    print("\n" + "=" * 70)
    print("INDIVIDUAL TOOL TESTS")
    print("=" * 70 + "\n")

    # Test preprocessing
    test_preprocessing()

    # Test GLM
    test_glm_analysis()

    # Test encoding model
    test_encoding_model()

    # Test coordinate lookup
    test_coordinate_lookup()

    # 3. Test BR-KG directly
    test_br_kg_query()

    # 4. Test full agent
    test_full_agent_query()

    print("\n" + "=" * 70)
    print("Debug tests completed!")

if __name__ == "__main__":
    main()
