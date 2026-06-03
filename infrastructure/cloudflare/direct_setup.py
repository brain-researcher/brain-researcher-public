#!/usr/bin/env python3
"""
Direct Cloudflare Setup for Brain Researcher
Configures Cloudflare to connect directly to service ports without nginx
"""

import os
from pathlib import Path
import requests
import json


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
SERVER_IP = os.environ["CLOUDFLARE_SERVER_IP"]

# Service ports
SERVICES = {
    "main": 3000,     # Next.js UI
    "api": 8000,      # Agent API
    "kg": 5000,       # BR-KG
    "agent": 8000     # Agent (same as API)
}

# Cloudflare API endpoint
BASE_URL = "https://api.cloudflare.com/client/v4"

headers = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json"
}

def update_dns_with_ports():
    """Update DNS records to point to specific ports"""
    print("📋 Updating DNS records with port configuration...")

    # For direct port access, we need to use Cloudflare's Origin Rules
    # or configure port forwarding at the origin

    # Since Cloudflare proxies HTTP/HTTPS traffic, we need to ensure
    # the services are accessible on standard ports

    dns_configs = [
        {"name": DOMAIN, "port": 3000, "service": "Web UI"},
        {"name": f"api.{DOMAIN}", "port": 8000, "service": "API"},
        {"name": f"kg.{DOMAIN}", "port": 5000, "service": "BR-KG"},
        {"name": f"agent.{DOMAIN}", "port": 8000, "service": "Agent"}
    ]

    for config in dns_configs:
        print(f"  {config['service']}: {config['name']} → {SERVER_IP}:{config['port']}")

    print("\n⚠️  Important: Since nginx is not installed, you need to:")
    print("  1. Configure your services to accept connections from Cloudflare IPs")
    print("  2. Set up port forwarding or use a reverse proxy")
    print("  3. Or use Cloudflare Spectrum (paid) for non-HTTP ports")

def create_origin_rules():
    """Create origin rules for port routing"""
    url = f"{BASE_URL}/zones/{ZONE_ID}/rulesets"

    # Get existing rulesets
    response = requests.get(url, headers=headers)
    rulesets = response.json().get("result", [])

    # Find origin rules ruleset
    origin_ruleset = None
    for ruleset in rulesets:
        if ruleset.get("phase") == "http_request_origin":
            origin_ruleset = ruleset
            break

    if not origin_ruleset:
        # Create new ruleset
        ruleset_data = {
            "name": "Brain Researcher Origin Rules",
            "kind": "zone",
            "phase": "http_request_origin",
            "rules": []
        }
        response = requests.post(url, headers=headers, json=ruleset_data)
        if response.status_code == 200:
            origin_ruleset = response.json()["result"]
        else:
            print("❌ Could not create origin ruleset")
            return

    # Define origin rules for different subdomains
    rules = [
        {
            "action": "route",
            "expression": f'(http.host eq "{DOMAIN}" or http.host eq "www.{DOMAIN}")',
            "description": "Route main domain to port 3000",
            "action_parameters": {
                "origin": {
                    "host": SERVER_IP,
                    "port": 3000
                }
            }
        },
        {
            "action": "route",
            "expression": f'(http.host eq "api.{DOMAIN}")',
            "description": "Route API subdomain to port 8000",
            "action_parameters": {
                "origin": {
                    "host": SERVER_IP,
                    "port": 8000
                }
            }
        },
        {
            "action": "route",
            "expression": f'(http.host eq "kg.{DOMAIN}")',
            "description": "Route KG subdomain to port 5000",
            "action_parameters": {
                "origin": {
                    "host": SERVER_IP,
                    "port": 5000
                }
            }
        }
    ]

    # Update ruleset
    ruleset_url = f"{url}/{origin_ruleset['id']}"
    response = requests.put(ruleset_url, headers=headers, json={"rules": rules})

    if response.status_code == 200:
        print("✅ Created origin routing rules")
    else:
        print(f"⚠️  Could not create origin rules: {response.json()}")

def setup_firewall_for_cloudflare():
    """Generate firewall rules for the origin server"""
    print("\n🔥 Firewall Configuration for Origin Server")
    print("=" * 50)
    print("Run these commands on your server to allow only Cloudflare:")
    print()

    cloudflare_ips_v4 = [
        "173.245.48.0/20",
        "103.21.244.0/22",
        "103.22.200.0/22",
        "103.31.4.0/22",
        "141.101.64.0/18",
        "108.162.192.0/18",
        "190.93.240.0/20",
        "188.114.96.0/20",
        "197.234.240.0/22",
        "198.41.128.0/17",
        "162.158.0.0/15",
        "104.16.0.0/13",
        "104.24.0.0/14",
        "172.64.0.0/13",
        "131.0.72.0/22"
    ]

    print("# UFW firewall rules (if using UFW):")
    for ip in cloudflare_ips_v4:
        print(f"sudo ufw allow from {ip} to any port 3000")
        print(f"sudo ufw allow from {ip} to any port 5000")
        print(f"sudo ufw allow from {ip} to any port 8000")

    print("\n# Or use iptables:")
    print("# Allow Cloudflare IPs")
    for ip in cloudflare_ips_v4:
        print(f"sudo iptables -A INPUT -p tcp --dport 3000 -s {ip} -j ACCEPT")
        print(f"sudo iptables -A INPUT -p tcp --dport 5000 -s {ip} -j ACCEPT")
        print(f"sudo iptables -A INPUT -p tcp --dport 8000 -s {ip} -j ACCEPT")

    print("\n# Block all other IPs from these ports")
    print("sudo iptables -A INPUT -p tcp --dport 3000 -j DROP")
    print("sudo iptables -A INPUT -p tcp --dport 5000 -j DROP")
    print("sudo iptables -A INPUT -p tcp --dport 8000 -j DROP")

    print("\n# Save iptables rules")
    print("sudo iptables-save > /etc/iptables/rules.v4")

def create_spectrum_config():
    """Information about Cloudflare Spectrum for TCP/UDP proxying"""
    print("\n🌐 Alternative: Cloudflare Spectrum (Pro/Business/Enterprise)")
    print("=" * 50)
    print("Cloudflare Spectrum allows proxying of any TCP/UDP port.")
    print("This would let you route traffic directly to your service ports")
    print("without needing nginx or port forwarding.")
    print()
    print("With Spectrum, you could:")
    print("  - Route ${PUBLIC_HOSTNAME}:3000 → Your server:3000")
    print("  - Route api.${PUBLIC_HOSTNAME}:8000 → Your server:8000")
    print("  - Route kg.${PUBLIC_HOSTNAME}:5000 → Your server:5000")
    print()
    print("Learn more: https://www.cloudflare.com/products/cloudflare-spectrum/")

def main():
    print("=" * 60)
    print("🚀 Direct Cloudflare Setup for Brain Researcher")
    print("=" * 60)
    print(f"Domain: {DOMAIN}")
    print(f"Server IP: {SERVER_IP}")
    print()

    # Show current setup
    update_dns_with_ports()

    # Try to create origin rules (may require higher plan)
    print("\n📋 Attempting to create origin routing rules...")
    create_origin_rules()

    # Show firewall configuration
    setup_firewall_for_cloudflare()

    # Show Spectrum information
    create_spectrum_config()

    print("\n" + "=" * 60)
    print("📋 Summary and Next Steps")
    print("=" * 60)
    print()
    print("Since nginx is not available, you have these options:")
    print()
    print("1. **Install nginx locally** (recommended)")
    print("   - Use the provided nginx configuration")
    print("   - Route subdomains to different ports")
    print()
    print("2. **Use a simple reverse proxy**")
    print("   - Install Caddy or HAProxy")
    print("   - Configure routing based on hostname")
    print()
    print("3. **Use Cloudflare Spectrum** (requires paid plan)")
    print("   - Direct TCP proxying to your ports")
    print()
    print("4. **Temporary Solution**: Access services directly")
    print(f"   - Configure services to listen on 0.0.0.0")
    print(f"   - Open firewall for Cloudflare IPs only")
    print(f"   - Services will be at root path of each subdomain")
    print()
    print("To start your services, run:")
    print("  ./start_services.sh")
    print()
    print("Your site will be accessible once services are running!")

if __name__ == "__main__":
    main()