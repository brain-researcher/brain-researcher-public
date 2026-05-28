#!/usr/bin/env python3
"""
Cloudflare DNS Update Script for Brain Researcher
Updates DNS records to point to the correct server IP
"""

import requests
import json
import sys

# Configuration
API_TOKEN = "qJ4E1AsWxPtGljVXoFxESCfTA4tIqpKoI3LA5YR7"
DOMAIN = "brain-researcher.com"
CORRECT_IP = "171.64.40.32"  # Your actual server IP

# Cloudflare API endpoint
BASE_URL = "https://api.cloudflare.com/client/v4"

# Headers for API requests
headers = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json"
}

def get_zone_id():
    """Get the Zone ID for the domain"""
    url = f"{BASE_URL}/zones"
    params = {"name": DOMAIN}
    
    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code == 200:
        data = response.json()
        if data["success"] and len(data["result"]) > 0:
            zone_id = data["result"][0]["id"]
            print(f"✅ Found Zone ID: {zone_id}")
            return zone_id
        else:
            print("❌ Domain not found in your Cloudflare account")
            return None
    else:
        print(f"❌ Error getting zone: {response.text}")
        return None

def list_dns_records(zone_id):
    """List all DNS records for the zone"""
    url = f"{BASE_URL}/zones/{zone_id}/dns_records"
    
    response = requests.get(url, headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        return data["result"]
    else:
        print(f"❌ Error listing DNS records: {response.text}")
        return []

def update_dns_record(zone_id, record_id, record_type, name, content, proxied=True):
    """Update a DNS record"""
    url = f"{BASE_URL}/zones/{zone_id}/dns_records/{record_id}"
    
    data = {
        "type": record_type,
        "name": name,
        "content": content,
        "proxied": proxied
    }
    
    response = requests.put(url, headers=headers, json=data)
    
    if response.status_code == 200:
        print(f"✅ Updated {name} → {content}")
        return True
    else:
        print(f"❌ Error updating {name}: {response.text}")
        return False

def create_dns_record(zone_id, record_type, name, content, proxied=True):
    """Create a new DNS record"""
    url = f"{BASE_URL}/zones/{zone_id}/dns_records"
    
    data = {
        "type": record_type,
        "name": name,
        "content": content,
        "proxied": proxied,
        "ttl": 1  # Auto TTL
    }
    
    response = requests.post(url, headers=headers, json=data)
    
    if response.status_code == 200:
        print(f"✅ Created {name} → {content}")
        return True
    else:
        print(f"❌ Error creating {name}: {response.text}")
        return False

def main():
    print("=" * 50)
    print("🚀 Brain Researcher Cloudflare DNS Updater")
    print("=" * 50)
    print(f"Domain: {DOMAIN}")
    print(f"Correct Server IP: {CORRECT_IP}")
    print()
    
    # Get Zone ID
    zone_id = get_zone_id()
    if not zone_id:
        sys.exit(1)
    
    # Get existing DNS records
    print("\n📋 Current DNS Records:")
    records = list_dns_records(zone_id)
    
    # Track which records exist
    existing_records = {}
    for record in records:
        if record["type"] == "A" or record["type"] == "CNAME":
            print(f"  {record['type']} {record['name']} → {record['content']} (Proxied: {record['proxied']})")
            existing_records[record["name"]] = record
    
    # Define required DNS records
    required_records = [
        {"name": DOMAIN, "type": "A", "content": CORRECT_IP},
        {"name": f"api.{DOMAIN}", "type": "A", "content": CORRECT_IP},
        {"name": f"kg.{DOMAIN}", "type": "A", "content": CORRECT_IP},
        {"name": f"agent.{DOMAIN}", "type": "A", "content": CORRECT_IP},
    ]
    
    # Update or create records
    print("\n🔄 Updating DNS Records:")
    
    for req_record in required_records:
        name = req_record["name"]
        
        if name in existing_records:
            record = existing_records[name]
            # Check if update is needed
            if record["content"] != req_record["content"] or not record["proxied"]:
                update_dns_record(
                    zone_id,
                    record["id"],
                    req_record["type"],
                    name,
                    req_record["content"],
                    proxied=True
                )
            else:
                print(f"✅ {name} already correct")
        else:
            # Create new record
            create_dns_record(
                zone_id,
                req_record["type"],
                name,
                req_record["content"],
                proxied=True
            )
    
    # Handle www CNAME separately (should point to root domain)
    www_name = f"www.{DOMAIN}"
    if www_name in existing_records:
        record = existing_records[www_name]
        if record["type"] != "CNAME" or record["content"] != DOMAIN:
            update_dns_record(
                zone_id,
                record["id"],
                "CNAME",
                www_name,
                DOMAIN,
                proxied=True
            )
    else:
        create_dns_record(
            zone_id,
            "CNAME",
            www_name,
            DOMAIN,
            proxied=True
        )
    
    print("\n✅ DNS Update Complete!")
    print("\n📝 Next Steps:")
    print("1. DNS propagation may take 1-5 minutes")
    print("2. Test with: dig brain-researcher.com @1.1.1.1")
    print("3. Configure your server's nginx/reverse proxy")
    print("4. Set up SSL certificates")
    
    print("\n🔍 Verify DNS propagation:")
    print(f"  curl -I https://{DOMAIN}")
    print(f"  nslookup {DOMAIN} 1.1.1.1")

if __name__ == "__main__":
    main()