#!/usr/bin/env python3
"""
Test script for BR-KG deployment on brain-researcher.com
"""

import requests

# Configuration
BASE_URL = "https://neurokg.brain-researcher.com"
# For testing before DNS setup, use Railway URL:
# BASE_URL = "https://your-railway-app.up.railway.app"


def test_endpoint(url, description):
    """Test an endpoint and display results"""
    print(f"\n🧪 Testing {description}")
    print(f"URL: {url}")

    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            print(f"✅ SUCCESS ({response.status_code})")

            # Try to parse JSON
            try:
                data = response.json()
                if isinstance(data, dict):
                    for key, value in list(data.items())[:3]:  # Show first 3 items
                        print(f"   {key}: {value}")
                    if len(data) > 3:
                        print(f"   ... and {len(data)-3} more fields")
                elif isinstance(data, list):
                    print(f"   Array with {len(data)} items")
                    if data:
                        print(f"   First item: {data[0]}")
            except:
                print(f"   Response: {response.text[:100]}...")

        else:
            print(f"❌ FAILED ({response.status_code})")
            print(f"   Error: {response.text[:200]}")

    except requests.exceptions.RequestException as e:
        print(f"❌ CONNECTION ERROR: {e}")


def main():
    """Test the BR-KG brain research platform"""

    print("🧠 BR-KG Brain Research Platform Test")
    print("=" * 50)
    print(f"Testing deployment at: {BASE_URL}")

    # Test endpoints
    endpoints = [
        ("/health", "Health Check"),
        ("/", "Homepage"),
        ("/api/glmfitlins/stats", "Database Statistics"),
        ("/api/glmfitlins/datasets", "Brain Imaging Datasets"),
        ("/api/glmfitlins/constructs?limit=5", "Cognitive Constructs"),
        ("/api/glmfitlins/search?q=working%20memory", "Search: Working Memory"),
        ("/api/glmfitlins/search?q=cognitive%20control", "Search: Cognitive Control"),
        ("/dashboard/", "Interactive Dashboard"),
    ]

    for endpoint, description in endpoints:
        test_endpoint(f"{BASE_URL}{endpoint}", description)

    print("\n" + "=" * 50)
    print("🎉 Brain Research Platform Test Complete!")
    print("\n📊 Key URLs for brain-researcher.com:")
    print(f"   🏠 Homepage: {BASE_URL}")
    print(f"   📈 Dashboard: {BASE_URL}/dashboard/")
    print(f"   🔬 API Docs: {BASE_URL}/api/glmfitlins/")
    print(f"   🧠 Research Data: {BASE_URL}/api/glmfitlins/stats")


if __name__ == "__main__":
    main()
