#!/usr/bin/env python3
"""
Cloudflare Configuration Script for Brain Researcher
Configures page rules, caching, security, and performance settings
"""

import os
from pathlib import Path
import requests
import json
import time


def _load_dotenv_if_available():
    try:
        import dotenv  # type: ignore

        env_path = Path(__file__).resolve().parents[2] / ".env"
        if env_path.exists():
            dotenv.load_dotenv(env_path)
    except Exception:
        pass


_load_dotenv_if_available()

# Configuration — supplied via environment, never hardcoded.
API_TOKEN = os.environ["CLOUDFLARE_API_TOKEN"]
ZONE_ID = os.environ["CLOUDFLARE_ZONE_ID"]
DOMAIN = os.environ.get("CLOUDFLARE_DOMAIN", "${PUBLIC_HOSTNAME}")

# Cloudflare API endpoint
BASE_URL = "https://api.cloudflare.com/client/v4"

# Headers for API requests
headers = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json"
}

def create_page_rule(target, actions, priority=1):
    """Create a page rule"""
    url = f"{BASE_URL}/zones/{ZONE_ID}/pagerules"

    data = {
        "targets": [{"target": "url", "constraint": {"operator": "matches", "value": target}}],
        "actions": actions,
        "priority": priority,
        "status": "active"
    }

    response = requests.post(url, headers=headers, json=data)

    if response.status_code == 200:
        print(f"✅ Created page rule for: {target}")
        return True
    else:
        error = response.json()
        if "already exists" in str(error):
            print(f"ℹ️ Page rule already exists for: {target}")
        else:
            print(f"❌ Error creating page rule: {error}")
        return False

def update_zone_settings():
    """Update zone-wide settings"""
    url = f"{BASE_URL}/zones/{ZONE_ID}/settings"

    settings = [
        # SSL/TLS
        {"id": "ssl", "value": "flexible"},  # Use flexible since origin is HTTP
        {"id": "always_use_https", "value": "on"},
        {"id": "automatic_https_rewrites", "value": "on"},
        {"id": "min_tls_version", "value": "1.2"},
        {"id": "tls_1_3", "value": "on"},

        # Security
        {"id": "security_level", "value": "medium"},
        {"id": "browser_check", "value": "on"},
        {"id": "challenge_ttl", "value": 1800},

        # Performance
        {"id": "brotli", "value": "on"},
        {"id": "minify", "value": {"css": "on", "html": "on", "js": "on"}},
        {"id": "rocket_loader", "value": "on"},
        {"id": "mirage", "value": "on"},
        {"id": "polish", "value": "lossless"},
        {"id": "webp", "value": "on"},
        {"id": "h2_prioritization", "value": "on"},
        {"id": "http2", "value": "on"},
        {"id": "http3", "value": "on"},
        {"id": "websockets", "value": "on"},
        {"id": "opportunistic_encryption", "value": "on"},

        # Caching
        {"id": "browser_cache_ttl", "value": 14400},
        {"id": "always_online", "value": "on"},
        {"id": "development_mode", "value": "off"},

        # Network
        {"id": "ipv6", "value": "on"},
        {"id": "ip_geolocation", "value": "on"},
        {"id": "opportunistic_onion", "value": "on"}
    ]

    success_count = 0
    for setting in settings:
        setting_url = f"{url}/{setting['id']}"
        response = requests.patch(setting_url, headers=headers, json={"value": setting["value"]})

        if response.status_code == 200:
            print(f"✅ Updated setting: {setting['id']}")
            success_count += 1
        else:
            error = response.json()
            print(f"⚠️ Could not update {setting['id']}: {error.get('errors', [{}])[0].get('message', 'Unknown error')}")

        time.sleep(0.2)  # Rate limiting

    return success_count

def create_firewall_rules():
    """Create firewall rules for security"""
    url = f"{BASE_URL}/zones/{ZONE_ID}/firewall/rules"

    rules = [
        {
            "filter": {
                "expression": '(cf.threat_score gt 30)',
                "description": "Block high threat score requests"
            },
            "action": "challenge",
            "description": "Challenge suspicious visitors"
        },
        {
            "filter": {
                "expression": '(http.request.uri.path contains "wp-admin" or http.request.uri.path contains "xmlrpc.php")',
                "description": "Block WordPress attacks"
            },
            "action": "block",
            "description": "Block common attack vectors"
        },
        {
            "filter": {
                "expression": '(http.request.uri.query contains "script" and http.request.uri.query contains "alert")',
                "description": "Block XSS attempts"
            },
            "action": "block",
            "description": "Block XSS attacks"
        }
    ]

    for rule in rules:
        # First create the filter
        filter_url = f"{BASE_URL}/zones/{ZONE_ID}/filters"
        filter_response = requests.post(filter_url, headers=headers, json=[rule["filter"]])

        if filter_response.status_code == 200:
            filter_id = filter_response.json()["result"][0]["id"]

            # Then create the firewall rule
            rule_data = [{
                "filter": {"id": filter_id},
                "action": rule["action"],
                "description": rule["description"]
            }]

            rule_response = requests.post(url, headers=headers, json=rule_data)

            if rule_response.status_code == 200:
                print(f"✅ Created firewall rule: {rule['description']}")
            else:
                print(f"⚠️ Could not create firewall rule: {rule['description']}")
        else:
            print(f"⚠️ Could not create filter for: {rule['description']}")

        time.sleep(0.5)

def create_rate_limiting_rules():
    """Create rate limiting rules"""
    url = f"{BASE_URL}/zones/{ZONE_ID}/rate_limits"

    rules = [
        {
            "threshold": 100,
            "period": 60,
            "match": {
                "request": {
                    "url_pattern": f"*{DOMAIN}/api/*",
                    "methods": ["POST", "PUT", "DELETE"]
                }
            },
            "action": {
                "mode": "challenge",
                "timeout": 600
            },
            "description": "Rate limit API mutations"
        },
        {
            "threshold": 1000,
            "period": 60,
            "match": {
                "request": {
                    "url_pattern": f"*{DOMAIN}/*"
                }
            },
            "action": {
                "mode": "challenge",
                "timeout": 300
            },
            "description": "General rate limiting"
        }
    ]

    for rule in rules:
        response = requests.post(url, headers=headers, json=rule)

        if response.status_code == 200:
            print(f"✅ Created rate limit: {rule['description']}")
        else:
            error = response.json()
            print(f"⚠️ Could not create rate limit: {error}")

        time.sleep(0.5)

def create_cache_rules():
    """Create cache rules using the new Cache Rules API"""
    url = f"{BASE_URL}/zones/{ZONE_ID}/rulesets"

    # Get existing rulesets
    response = requests.get(url, headers=headers)
    rulesets = response.json().get("result", [])

    # Find or create cache ruleset
    cache_ruleset = None
    for ruleset in rulesets:
        if ruleset.get("phase") == "http_request_cache_settings":
            cache_ruleset = ruleset
            break

    if cache_ruleset:
        ruleset_url = f"{url}/{cache_ruleset['id']}"
    else:
        # Create new ruleset
        ruleset_data = {
            "name": "Brain Researcher Cache Rules",
            "kind": "zone",
            "phase": "http_request_cache_settings",
            "rules": []
        }
        response = requests.post(url, headers=headers, json=ruleset_data)
        if response.status_code == 200:
            cache_ruleset = response.json()["result"]
            ruleset_url = f"{url}/{cache_ruleset['id']}"
        else:
            print("❌ Could not create cache ruleset")
            return

    # Define cache rules
    rules = [
        {
            "action": "set_cache_settings",
            "expression": '(http.request.uri.path matches "^/_next/static/")',
            "description": "Cache static assets for 1 year",
            "action_parameters": {
                "edge_ttl": {
                    "mode": "override_origin",
                    "default": 31536000
                },
                "browser_ttl": {
                    "mode": "override_origin",
                    "default": 31536000
                },
                "cache_key": {
                    "cache_deception_armor": True,
                    "ignore_query_strings_order": True
                }
            }
        },
        {
            "action": "set_cache_settings",
            "expression": '(http.request.uri.path matches "\\.(jpg|jpeg|png|gif|svg|webp|ico|woff|woff2|ttf|otf)$")',
            "description": "Cache images and fonts",
            "action_parameters": {
                "edge_ttl": {
                    "mode": "override_origin",
                    "default": 2592000  # 30 days
                },
                "browser_ttl": {
                    "mode": "override_origin",
                    "default": 604800  # 7 days
                }
            }
        },
        {
            "action": "set_cache_settings",
            "expression": '(http.request.uri.path matches "^/api/datasets/" and http.request.method eq "GET")',
            "description": "Cache dataset API responses",
            "action_parameters": {
                "edge_ttl": {
                    "mode": "override_origin",
                    "default": 3600  # 1 hour
                },
                "cache_key": {
                    "custom_key": {
                        "query_string": {
                            "include": ["*"]
                        }
                    }
                }
            }
        },
        {
            "action": "set_cache_settings",
            "expression": '(http.request.uri.path matches "\\.nii(\\.gz)?$")',
            "description": "Cache brain imaging files",
            "action_parameters": {
                "edge_ttl": {
                    "mode": "override_origin",
                    "default": 86400  # 1 day
                },
                "browser_ttl": {
                    "mode": "override_origin",
                    "default": 3600  # 1 hour
                }
            }
        }
    ]

    # Update ruleset with new rules
    ruleset_data = {
        "rules": rules
    }

    response = requests.put(ruleset_url, headers=headers, json=ruleset_data)

    if response.status_code == 200:
        print(f"✅ Created {len(rules)} cache rules")
    else:
        print(f"⚠️ Could not create cache rules: {response.json()}")

def setup_custom_error_pages():
    """Setup custom error pages"""
    url = f"{BASE_URL}/zones/{ZONE_ID}/custom_pages"

    error_pages = [
        {
            "url": f"https://{DOMAIN}/500.html",
            "state": "customized",
            "id": "5xx_errors"
        },
        {
            "url": f"https://{DOMAIN}/maintenance.html",
            "state": "customized",
            "id": "always_online"
        }
    ]

    for page in error_pages:
        page_url = f"{url}/{page['id']}"
        response = requests.put(page_url, headers=headers, json={"url": page["url"], "state": page["state"]})

        if response.status_code == 200:
            print(f"✅ Configured custom error page: {page['id']}")
        else:
            print(f"⚠️ Could not configure error page: {page['id']}")

def create_page_rules():
    """Create page rules for specific paths"""
    rules = [
        # Static assets - cache everything
        {
            "target": f"*{DOMAIN}/_next/static/*",
            "actions": [
                {"id": "cache_level", "value": "cache_everything"},
                {"id": "edge_cache_ttl", "value": 31536000},
                {"id": "browser_cache_ttl", "value": 31536000}
            ],
            "priority": 1
        },
        # Images - cache with optimization
        {
            "target": f"*{DOMAIN}/images/*",
            "actions": [
                {"id": "cache_level", "value": "cache_everything"},
                {"id": "edge_cache_ttl", "value": 2592000},
                {"id": "browser_cache_ttl", "value": 604800},
                {"id": "polish", "value": "lossless"},
                {"id": "mirage", "value": "on"}
            ],
            "priority": 2
        },
        # API - smart caching
        {
            "target": f"api.{DOMAIN}/datasets/*",
            "actions": [
                {"id": "cache_level", "value": "cache_everything"},
                {"id": "edge_cache_ttl", "value": 3600},
                {"id": "origin_error_page_pass_thru", "value": "on"}
            ],
            "priority": 3
        },
        # Admin/Auth - bypass cache
        {
            "target": f"*{DOMAIN}/admin/*",
            "actions": [
                {"id": "cache_level", "value": "bypass"},
                {"id": "disable_apps", "value": True}
            ],
            "priority": 4
        }
    ]

    for rule in rules:
        create_page_rule(rule["target"], rule["actions"], rule["priority"])
        time.sleep(0.5)

def main():
    print("=" * 60)
    print("🚀 Cloudflare Configuration for Brain Researcher")
    print("=" * 60)
    print(f"Domain: {DOMAIN}")
    print(f"Zone ID: {ZONE_ID}")
    print()

    # 1. Update zone settings
    print("\n📋 Updating Zone Settings...")
    settings_count = update_zone_settings()
    print(f"Updated {settings_count} settings")

    # 2. Create page rules
    print("\n📄 Creating Page Rules...")
    create_page_rules()

    # 3. Create cache rules
    print("\n💾 Creating Cache Rules...")
    create_cache_rules()

    # 4. Create firewall rules
    print("\n🔥 Creating Firewall Rules...")
    create_firewall_rules()

    # 5. Create rate limiting
    print("\n⏱️ Creating Rate Limiting Rules...")
    create_rate_limiting_rules()

    # 6. Setup error pages
    print("\n📝 Setting up Custom Error Pages...")
    setup_custom_error_pages()

    print("\n" + "=" * 60)
    print("✅ Cloudflare configuration complete!")
    print("\n📊 Summary:")
    print("- SSL/TLS: Flexible mode (works with HTTP origin)")
    print("- Performance: Brotli, minification, image optimization enabled")
    print("- Security: Firewall rules and rate limiting configured")
    print("- Caching: Optimized for static assets and API responses")
    print("\nYour site should now be faster and more secure!")
    print(f"\nVisit: https://{DOMAIN}")

if __name__ == "__main__":
    main()