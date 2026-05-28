#!/usr/bin/env python
"""Test real-time GLM tool with fixture data."""

import requests
import json
import sys
from pathlib import Path
import pytest

print("Testing Real-time GLM Tool")
print("-" * 40)

# Configuration
BASE_URL = "http://localhost:8000"
fixture_dir = Path("tests/fixtures/realtime_fmri")

# Verify fixtures exist
if not fixture_dir.exists():
    pytest.skip(f"Fixture directory not found: {fixture_dir}", allow_module_level=True)

# Test request with actual fixture files
request = {
    "query": "run realtime GLM analysis with the provided data files",
    "params": {
        "data_file": str(fixture_dir / "test_data.npy"),
        "design_matrix_file": str(fixture_dir / "test_design.npy"),
        "contrast_file": str(fixture_dir / "test_contrast.npy"),
        "output_dir": str(fixture_dir / "outputs" / "glm")
    }
}

try:
    requests.get(f"{BASE_URL}/healthz", timeout=2)
except Exception:
    pytest.skip("Agent service not reachable at %s" % BASE_URL, allow_module_level=True)

results = {}

# Test both endpoints
for endpoint in ["/act", "/act_llm"]:
    print(f"\nTesting {endpoint}...")
    try:
        response = requests.post(
            f"{BASE_URL}{endpoint}", 
            json=request,
            timeout=15
        )
        
        if response.status_code == 200:
            data = response.json()
            
            # Check for tool execution
            if endpoint == "/act":
                tool_calls = data.get("tool_calls", [])
                if tool_calls:
                    tool_name = tool_calls[0].get("name", "unknown")
                    status = tool_calls[0].get("status", "unknown")
                    print(f"  ✅ Status: {response.status_code}")
                    print(f"  📊 Tool selected: {tool_name}")
                    print(f"  📊 Execution status: {status}")
                    results[endpoint] = "PASSED"
                else:
                    print(f"  ⚠️  No tools executed")
                    results[endpoint] = "NO_TOOLS"
            else:  # /act_llm
                if "error" not in data:
                    print(f"  ✅ Status: {response.status_code}")
                    print(f"  📊 Response received successfully")
                    results[endpoint] = "PASSED"
                else:
                    print(f"  ❌ Error in response")
                    results[endpoint] = "ERROR"
        else:
            error_data = response.json() if response.headers.get('content-type') == 'application/json' else {}
            error_msg = error_data.get('error', {}).get('message', 'Unknown error')
            print(f"  ❌ Status: {response.status_code}")
            print(f"  ❌ Error: {error_msg[:100]}...")
            results[endpoint] = "FAILED"
            
    except requests.exceptions.Timeout:
        print(f"  ❌ Request timed out")
        results[endpoint] = "TIMEOUT"
    except Exception as e:
        print(f"  ❌ Error: {e}")
        results[endpoint] = "ERROR"

# Summary
print("\n" + "=" * 40)
print("SUMMARY")
print("=" * 40)
for endpoint, result in results.items():
    status_icon = "✅" if result == "PASSED" else "❌"
    print(f"{endpoint:10} : {status_icon} {result}")

# Exit code
if all(r == "PASSED" for r in results.values()):
    print("\n✅ All tests passed!")
    sys.exit(0)
else:
    print("\n⚠️  Some tests failed or had issues")
    sys.exit(1)