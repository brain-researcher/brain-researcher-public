#!/usr/bin/env python3
"""
Test script for OAuth authentication flow in Brain Researcher.

Usage:
    python tests/test_oauth_flow.py --provider google
    python tests/test_oauth_flow.py --provider microsoft
    python tests/test_oauth_flow.py --provider github
    python tests/test_oauth_flow.py --test-magic-link --email test@example.com
"""

import argparse
import json
from urllib.parse import parse_qs, urlparse

import requests

# Configuration
ORCHESTRATOR_URL = "http://localhost:3004"
FRONTEND_URL = "http://localhost:3000"


def test_oauth_authorize(provider: str):
    """Test OAuth authorization redirect"""
    print(f"\n{'='*60}")
    print(f"Testing {provider.upper()} OAuth Authorization Flow")
    print(f"{'='*60}\n")

    url = f"{ORCHESTRATOR_URL}/auth/oauth/{provider}/authorize"
    print(f"Step 1: GET {url}")

    try:
        # Don't follow redirects so we can see where it wants to send us
        response = requests.get(url, allow_redirects=False)

        if response.status_code == 307 or response.status_code == 302:
            redirect_url = response.headers.get("Location")
            print(f"✅ Got redirect (status {response.status_code})")
            print(f"   Redirect URL: {redirect_url[:100]}...")

            # Parse the redirect URL to check parameters
            parsed = urlparse(redirect_url)
            params = parse_qs(parsed.query)

            print(f"\n   Provider: {parsed.netloc}")
            print(f"   State: {params.get('state', ['N/A'])[0][:20]}...")
            print(f"   Scopes: {params.get('scope', ['N/A'])[0]}")
            print(f"   Client ID configured: {'client_id' in params}")

            print("\n✅ OAuth authorization endpoint working correctly!")
            print("   Next step: User would log in at the provider")
            print(f"   Then provider redirects to: /auth/oauth/{provider}/callback")

            return True
        else:
            print(f"❌ Unexpected status code: {response.status_code}")
            print(f"   Response: {response.text[:200]}")
            return False

    except requests.exceptions.ConnectionError:
        print("❌ Connection failed. Is the orchestrator running?")
        print("   Start it with: br serve orchestrator")
        print("   Or: python -m brain_researcher.services.orchestrator.main_enhanced")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def test_magic_link_send(email: str):
    """Test magic link email sending"""
    print(f"\n{'='*60}")
    print("Testing Magic Link Authentication")
    print(f"{'='*60}\n")

    url = f"{ORCHESTRATOR_URL}/auth/oauth/magic-link/send"
    print(f"Step 1: POST {url}")
    print(f"   Email: {email}")

    try:
        response = requests.post(
            url, json={"email": email}, headers={"Content-Type": "application/json"}
        )

        if response.status_code == 200:
            data = response.json()
            print("✅ Magic link sent successfully!")
            print(f"   Response: {json.dumps(data, indent=2)}")
            print("\n   Check your email for the magic link")
            print(f"   Link format: {FRONTEND_URL}/auth/magic-link?token=...")
            return True
        else:
            print(f"❌ Failed with status {response.status_code}")
            print(f"   Response: {response.text}")
            return False

    except requests.exceptions.ConnectionError:
        print("❌ Connection failed. Is the orchestrator running?")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def check_environment_variables(provider: str):
    """Check if required environment variables are set"""
    print(f"\n📋 Environment Variables Check for {provider.upper()}:")
    print("-" * 60)

    required_vars = {
        "google": ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"],
        "microsoft": [
            "AZURE_AD_CLIENT_ID",
            "AZURE_AD_CLIENT_SECRET",
            "AZURE_AD_TENANT_ID",
        ],
        "github": ["GITHUB_CLIENT_ID", "GITHUB_CLIENT_SECRET"],
        "magic_link": [
            "EMAIL_SERVER_HOST",
            "EMAIL_SERVER_USER",
            "EMAIL_SERVER_PASSWORD",
        ],
    }

    common_vars = ["JWT_SECRET_KEY", "FRONTEND_URL"]

    vars_to_check = required_vars.get(provider, []) + common_vars

    import os

    all_set = True
    for var in vars_to_check:
        value = os.getenv(var)
        if value:
            # Show only first few characters for security
            masked = value[:4] + "***" if len(value) > 4 else "***"
            print(f"   ✅ {var}: {masked}")
        else:
            print(f"   ❌ {var}: Not set")
            all_set = False

    print("-" * 60)
    if not all_set:
        print("⚠️  Some environment variables are missing")
        print("   Set them in your .env file or export them")

    return all_set


def test_health():
    """Test if orchestrator is running"""
    try:
        response = requests.get(f"{ORCHESTRATOR_URL}/health", timeout=2)
        if response.status_code == 200:
            print("✅ Orchestrator service is running")
            return True
    except:
        pass

    print("❌ Orchestrator service is not responding")
    print(f"   Expected at: {ORCHESTRATOR_URL}")
    print("\n   Start it with one of:")
    print("   • br serve orchestrator")
    print("   • python -m brain_researcher.services.orchestrator.main_enhanced")
    print(
        "   • uvicorn brain_researcher.services.orchestrator.main_enhanced:app --reload --port 8080"
    )
    return False


def main():
    parser = argparse.ArgumentParser(description="Test OAuth authentication flow")
    parser.add_argument(
        "--provider",
        choices=["google", "microsoft", "github"],
        help="OAuth provider to test",
    )
    parser.add_argument(
        "--test-magic-link", action="store_true", help="Test magic link authentication"
    )
    parser.add_argument("--email", help="Email address for magic link test")
    parser.add_argument(
        "--skip-health-check", action="store_true", help="Skip health check"
    )

    args = parser.parse_args()

    print("\n" + "=" * 60)
    print("Brain Researcher OAuth Authentication Test")
    print("=" * 60)

    # Health check
    if not args.skip_health_check:
        if not test_health():
            return 1

    # Test magic link
    if args.test_magic_link:
        if not args.email:
            print("❌ --email is required for magic link test")
            return 1

        check_environment_variables("magic_link")
        success = test_magic_link_send(args.email)
        return 0 if success else 1

    # Test OAuth provider
    if args.provider:
        check_environment_variables(args.provider)
        success = test_oauth_authorize(args.provider)
        return 0 if success else 1

    # No test specified
    print("\n❌ Please specify either --provider or --test-magic-link")
    parser.print_help()
    return 1


if __name__ == "__main__":
    exit(main())
