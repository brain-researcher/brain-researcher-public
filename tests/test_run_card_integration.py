#!/usr/bin/env python3
"""
Integration test for UI-004 Run Card Export functionality
Tests the complete end-to-end flow from backend to frontend
"""

import requests
import json
import sys
import time
from pathlib import Path

# Configuration
BASE_URL = "http://localhost:3001"  # Orchestrator service
TEST_JOB_ID = "test_ui004_integration"

def test_run_card_api():
    """Test the Run Card API endpoints"""
    print("🧪 Testing UI-004: Run Card Export Integration")
    print("=" * 50)

    try:
        # Test 1: Get Run Card
        print("1️⃣ Testing GET /api/evidence/jobs/{job_id}/runcard")
        response = requests.get(f"{BASE_URL}/api/evidence/jobs/{TEST_JOB_ID}/runcard")

        if response.status_code == 200:
            run_card = response.json()
            print("   ✅ Run Card retrieved successfully")
            print(f"   📋 Run Card ID: {run_card['id']}")
            print(f"   🏷️  Title: {run_card['title']}")
            print(f"   ⏱️  Duration: {run_card['execution']['duration_seconds']}s")
            print(f"   🔬 Tools: {len(run_card['provenance']['tools'])}")
            print(f"   📊 Reproducibility Score: {run_card.get('reproducibility_score', 'N/A')}")
        else:
            print(f"   ❌ Failed to get Run Card: {response.status_code}")
            return False

        # Test 2: Export as JSON
        print("\n2️⃣ Testing JSON Export")
        response = requests.get(f"{BASE_URL}/api/evidence/jobs/{TEST_JOB_ID}/runcard/export?format=json")

        if response.status_code == 200:
            print("   ✅ JSON export successful")
            print(f"   📦 Content-Type: {response.headers.get('content-type')}")

            # Verify it's valid JSON
            try:
                exported_data = json.loads(response.text)
                print(f"   ✅ Valid JSON with {len(exported_data)} top-level keys")
            except json.JSONDecodeError:
                print("   ❌ Invalid JSON response")
                return False
        else:
            print(f"   ❌ JSON export failed: {response.status_code}")
            return False

        # Test 3: Export as YAML
        print("\n3️⃣ Testing YAML Export")
        response = requests.get(f"{BASE_URL}/api/evidence/jobs/{TEST_JOB_ID}/runcard/export?format=yaml")

        if response.status_code == 200:
            print("   ✅ YAML export successful")
            print(f"   📦 Content-Type: {response.headers.get('content-type')}")

            # Basic YAML validation
            if "version:" in response.text and "id:" in response.text:
                print("   ✅ Valid YAML structure")
            else:
                print("   ❌ Invalid YAML structure")
                return False
        else:
            print(f"   ❌ YAML export failed: {response.status_code}")
            return False

        # Test 4: Export with options
        print("\n4️⃣ Testing Export with Options")
        response = requests.get(
            f"{BASE_URL}/api/evidence/jobs/{TEST_JOB_ID}/runcard/export"
            f"?format=json&includeArtifacts=false&includeEnvironment=false"
        )

        if response.status_code == 200:
            filtered_data = json.loads(response.text)
            print("   ✅ Filtered export successful")
            print(f"   🗂️  Artifacts excluded: {len(filtered_data['outputs']['artifacts']) == 0}")
            print(f"   🖥️  Environment excluded: {len(filtered_data['execution']['environment']) == 0}")
        else:
            print(f"   ❌ Filtered export failed: {response.status_code}")
            return False

        # Test 5: Create Share Link
        print("\n5️⃣ Testing Share Link Creation")
        share_request = {
            "jobId": TEST_JOB_ID,
            "format": "json",
            "expires_in_hours": 24
        }

        response = requests.post(f"{BASE_URL}/api/evidence/share", json=share_request)

        if response.status_code == 200:
            share_data = response.json()
            print("   ✅ Share link created successfully")
            print(f"   🔗 Share ID: {share_data['share_id']}")
            print(f"   🌐 Share URL: {share_data['share_url']}")
            print(f"   ⏰ Expires: {share_data['expires_at']}")

            # Test accessing the shared run card
            share_id = share_data['share_id']
            response = requests.get(f"{BASE_URL}/api/evidence/share/{share_id}")

            if response.status_code == 200:
                shared_data = response.json()
                print("   ✅ Shared Run Card accessible")
                print(f"   📋 Shared ID: {shared_data['run_card']['id']}")
            else:
                print(f"   ❌ Failed to access shared Run Card: {response.status_code}")
                return False
        else:
            print(f"   ❌ Share link creation failed: {response.status_code}")
            return False

        # Test 6: PDF Export (optional - may not have reportlab)
        print("\n6️⃣ Testing PDF Export")
        response = requests.get(f"{BASE_URL}/api/evidence/jobs/{TEST_JOB_ID}/runcard/export?format=pdf")

        if response.status_code == 200:
            print("   ✅ PDF export successful")
            print(f"   📦 Content-Type: {response.headers.get('content-type')}")
            print(f"   📄 PDF Size: {len(response.content)} bytes")
        elif response.status_code == 500 and "reportlab" in response.text:
            print("   ⚠️  PDF export unavailable (reportlab not installed)")
        else:
            print(f"   ❌ PDF export failed: {response.status_code}")
            return False

        print("\n🎉 All Run Card Export tests passed!")
        return True

    except requests.exceptions.RequestException as e:
        print(f"❌ Connection error: {e}")
        print("💡 Make sure the orchestrator service is running on port 3001")
        return False
    except Exception as e:
        print(f"❌ Test error: {e}")
        return False

def test_file_storage():
    """Test that Run Cards are being stored correctly"""
    print("\n📁 Testing Run Card Storage")
    print("=" * 30)

    run_cards_dir = Path("/app/brain_researcher/data/run_cards")

    if run_cards_dir.exists():
        run_card_files = list(run_cards_dir.glob("*.json"))
        print(f"   📊 Found {len(run_card_files)} stored Run Cards")

        if run_card_files:
            latest_file = max(run_card_files, key=lambda p: p.stat().st_mtime)
            print(f"   📄 Latest: {latest_file.name}")
            print(f"   💾 Size: {latest_file.stat().st_size} bytes")

            # Verify structure
            try:
                with open(latest_file) as f:
                    data = json.load(f)
                print(f"   ✅ Valid JSON structure")
                print(f"   🏷️  ID: {data.get('id', 'Unknown')}")
            except:
                print(f"   ❌ Invalid JSON in stored file")
                return False

        return True
    else:
        print("   ❌ Run cards directory not found")
        return False

if __name__ == "__main__":
    print("🚀 Starting UI-004 Integration Tests")
    print("Testing Run Card Export functionality...\n")

    # Test API functionality
    api_success = test_run_card_api()

    # Test storage functionality
    storage_success = test_file_storage()

    print("\n" + "=" * 50)
    if api_success and storage_success:
        print("🎉 All UI-004 tests completed successfully!")
        print("✅ Run Card Export functionality is working correctly")
        sys.exit(0)
    else:
        print("❌ Some tests failed")
        print("Please check the error messages above")
        sys.exit(1)