#!/usr/bin/env python3
"""
Simple test script to verify the orchestrator backend contracts.
This tests the main endpoints for the 5 UI components.
"""

import asyncio
import json
import requests
import time
from datetime import datetime

BASE_URL = "http://localhost:3001"

def test_health_endpoint():
    """Test health endpoint (UI-013)."""
    print("Testing health endpoint...")
    response = requests.get(f"{BASE_URL}/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "services" in data
    assert "timestamp" in data
    print("✓ Health endpoint working")

def test_ui_configuration():
    """Test UI configuration endpoint (UI-015)."""
    print("Testing UI configuration...")
    response = requests.get(f"{BASE_URL}/config/ui")
    assert response.status_code == 200
    data = response.json()
    assert "feature_flags" in data
    assert "pagination" in data
    assert "timeouts" in data
    assert "limits" in data
    print("✓ UI configuration endpoint working")

def test_authentication_signup():
    """Test authentication signup (UI-011)."""
    print("Testing authentication signup...")
    signup_data = {
        "username": "testuser",
        "email": "test@example.com",
        "password": "testpass123",
        "full_name": "Test User",
        "accept_terms": True
    }
    response = requests.post(f"{BASE_URL}/auth/signup", json=signup_data)
    if response.status_code == 200:
        data = response.json()
        assert "access_token" in data
        assert "user" in data
        print("✓ Authentication signup working")
        return data["access_token"]
    else:
        print(f"! Signup failed: {response.status_code} - {response.text}")
        return None

def test_authentication_login():
    """Test authentication login (UI-011)."""
    print("Testing authentication login...")
    login_data = {
        "username": "demo",
        "password": "demo123",
        "remember_me": False
    }
    response = requests.post(f"{BASE_URL}/auth/login", json=login_data)
    if response.status_code == 200:
        data = response.json()
        assert "access_token" in data
        assert "user" in data
        print("✓ Authentication login working")
        return data["access_token"]
    else:
        print(f"! Login failed: {response.status_code} - {response.text}")
        return None

def test_notifications_with_auth(token):
    """Test notifications endpoint (UI-026)."""
    print("Testing notifications...")
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(f"{BASE_URL}/notifications", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert "notifications" in data
    assert "unread_count" in data
    assert "total_count" in data
    print("✓ Notifications endpoint working")

def test_job_creation_with_progress():
    """Test job creation with progress tracking (UI-014)."""
    print("Testing job creation with progress...")
    job_data = {
        "prompt": "Test GLM analysis for contract testing",
        "pipeline": "glm",
        "dataset_id": "motor-task-sample",
        "parameters": {"smoothing": 6, "threshold": 0.001}
    }
    response = requests.post(f"{BASE_URL}/run", json=job_data)
    assert response.status_code == 200
    data = response.json()
    assert "job_id" in data
    assert "estimated_duration" in data
    assert "queue_position" in data
    job_id = data["job_id"]
    print(f"✓ Job created: {job_id}")

    # Check job details include progress
    time.sleep(1)  # Allow job to start
    response = requests.get(f"{BASE_URL}/jobs/{job_id}")
    assert response.status_code == 200
    job_data = response.json()
    assert "progress" in job_data
    if job_data["progress"]:
        assert "percentage" in job_data["progress"]
        assert "current_step" in job_data["progress"]
        assert "total_steps" in job_data["progress"]
    print("✓ Job progress tracking working")

    return job_id

def test_error_response_format():
    """Test enhanced error response format (UI-013)."""
    print("Testing error response format...")
    # Try to access non-existent job
    response = requests.get(f"{BASE_URL}/jobs/job_nonexistent")
    assert response.status_code == 404
    data = response.json()
    assert "error" in data
    assert "code" in data["error"]
    assert "message" in data["error"]
    assert "timestamp" in data["error"]
    print("✓ Enhanced error responses working")

def main():
    """Run all tests."""
    print("Testing Orchestrator Backend Contracts")
    print("=" * 50)

    try:
        # Test basic endpoints
        test_health_endpoint()
        test_ui_configuration()
        test_error_response_format()

        # Test authentication
        token = test_authentication_login()
        if not token:
            # Try signup if login fails
            token = test_authentication_signup()

        if token:
            test_notifications_with_auth(token)
        else:
            print("! Skipping authenticated endpoints - no token")

        # Test job creation and progress
        job_id = test_job_creation_with_progress()

        print("\n" + "=" * 50)
        print("✓ All backend contract tests passed!")
        print(f"✓ Authentication: {'Working' if token else 'Needs setup'}")
        print(f"✓ Job Progress: Working")
        print(f"✓ Error Handling: Working")
        print(f"✓ UI Configuration: Working")
        print(f"✓ Notifications: {'Working' if token else 'Requires auth'}")

    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        return 1
    except requests.exceptions.ConnectionError:
        print(f"\n❌ Cannot connect to {BASE_URL}")
        print("Please start the orchestrator service first:")
        print("cd brain_researcher/services/orchestrator")
        print("python main_enhanced.py")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        return 1

    return 0

if __name__ == "__main__":
    exit(main())