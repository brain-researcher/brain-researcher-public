#!/bin/bash

# Cloudflare Setup Script for Brain Researcher
# This script helps configure Cloudflare for your domain

set -e

echo "==================================="
echo "Brain Researcher Cloudflare Setup"
echo "==================================="
echo ""

# Check for required tools
check_requirements() {
    echo "Checking requirements..."
    
    if ! command -v terraform &> /dev/null; then
        echo "❌ Terraform not found. Installing..."
        curl -fsSL https://apt.releases.hashicorp.com/gpg | sudo apt-key add -
        sudo apt-add-repository "deb [arch=amd64] https://apt.releases.hashicorp.com $(lsb_release -cs) main"
        sudo apt-get update && sudo apt-get install terraform
    else
        echo "✅ Terraform found"
    fi
    
    if ! command -v wrangler &> /dev/null; then
        echo "❌ Wrangler not found. Installing..."
        npm install -g wrangler
    else
        echo "✅ Wrangler found"
    fi
    
    if ! command -v jq &> /dev/null; then
        echo "❌ jq not found. Installing..."
        sudo apt-get install -y jq
    else
        echo "✅ jq found"
    fi
}

# Get Cloudflare credentials
get_credentials() {
    echo ""
    echo "=== Cloudflare Credentials ==="
    echo "Get these from: https://dash.cloudflare.com/profile/api-tokens"
    echo ""
    
    read -p "Enter your Cloudflare API Token: " CF_API_TOKEN
    read -p "Enter your Cloudflare Zone ID: " CF_ZONE_ID
    read -p "Enter your domain (e.g., ${PUBLIC_HOSTNAME}): " DOMAIN
    read -p "Enter your origin server IP: " ORIGIN_IP
    
    # Save to terraform.tfvars
    cat > terraform/terraform.tfvars <<EOF
cloudflare_api_token = "${CF_API_TOKEN}"
cloudflare_zone_id = "${CF_ZONE_ID}"
domain = "${DOMAIN}"
origin_server_ip = "${ORIGIN_IP}"
EOF
    
    echo "✅ Credentials saved to terraform/terraform.tfvars"
}

# Initialize Terraform
init_terraform() {
    echo ""
    echo "=== Initializing Terraform ==="
    cd terraform
    terraform init
    echo "✅ Terraform initialized"
}

# Plan Terraform changes
plan_terraform() {
    echo ""
    echo "=== Planning Cloudflare Configuration ==="
    terraform plan -out=tfplan
    echo ""
    read -p "Review the plan above. Apply changes? (y/n): " CONFIRM
    
    if [[ $CONFIRM == "y" ]]; then
        terraform apply tfplan
        echo "✅ Cloudflare configuration applied"
    else
        echo "⚠️ Skipping apply"
    fi
    cd ..
}

# Setup Workers
setup_workers() {
    echo ""
    echo "=== Setting up Cloudflare Workers ==="
    
    # Login to Cloudflare
    wrangler login
    
    # Create KV namespace
    echo "Creating KV namespace for caching..."
    KV_ID=$(wrangler kv:namespace create "CACHE" --preview false | grep -oP 'id = "\K[^"]+')
    
    # Update wrangler.toml with KV ID
    sed -i "s/YOUR_KV_NAMESPACE_ID/${KV_ID}/g" wrangler.toml
    sed -i "s/YOUR_ZONE_ID/${CF_ZONE_ID}/g" wrangler.toml
    sed -i "s/YOUR_ACCOUNT_ID/$(wrangler whoami | grep 'Account ID' | awk '{print $3}')/g" wrangler.toml
    
    # Deploy worker
    echo "Deploying edge optimizer worker..."
    wrangler publish --env production
    
    echo "✅ Workers deployed"
}

# Configure page rules via API
configure_page_rules() {
    echo ""
    echo "=== Configuring Page Rules ==="
    
    # API endpoint
    API_URL="https://api.cloudflare.com/client/v4/zones/${CF_ZONE_ID}/pagerules"
    
    # Static assets rule
    curl -X POST "${API_URL}" \
        -H "Authorization: Bearer ${CF_API_TOKEN}" \
        -H "Content-Type: application/json" \
        --data '{
            "targets": [{"target": "url", "constraint": {"operator": "matches", "value": "'${DOMAIN}'/_next/static/*"}}],
            "actions": [
                {"id": "cache_level", "value": "cache_everything"},
                {"id": "edge_cache_ttl", "value": 31536000},
                {"id": "browser_cache_ttl", "value": 31536000}
            ],
            "priority": 1
        }'
    
    echo "✅ Page rules configured"
}

# Test configuration
test_configuration() {
    echo ""
    echo "=== Testing Configuration ==="
    
    # Test DNS
    echo "Testing DNS resolution..."
    dig +short ${DOMAIN} @1.1.1.1
    
    # Test HTTPS
    echo "Testing HTTPS..."
    curl -I https://${DOMAIN} 2>/dev/null | head -n 1
    
    # Test caching headers
    echo "Testing cache headers..."
    curl -I https://${DOMAIN}/_next/static/test.js 2>/dev/null | grep -i cache-control
    
    echo "✅ Configuration tests complete"
}

# Generate nginx config for origin
generate_origin_config() {
    echo ""
    echo "=== Generating Origin Server Configuration ==="
    
    cat > nginx-origin.conf <<'EOF'
# Nginx configuration for origin server behind Cloudflare

server {
    listen 80;
    listen 443 ssl http2;
    server_name ${PUBLIC_HOSTNAME} www.${PUBLIC_HOSTNAME};
    
    # SSL configuration (use Cloudflare Origin CA certificate)
    ssl_certificate /etc/nginx/ssl/cloudflare-origin.pem;
    ssl_certificate_key /etc/nginx/ssl/cloudflare-origin-key.pem;
    
    # Only allow Cloudflare IPs
    include /etc/nginx/cloudflare-ips.conf;
    deny all;
    
    # Restore real visitor IP
    set_real_ip_from 173.245.48.0/20;
    set_real_ip_from 103.21.244.0/22;
    set_real_ip_from 103.22.200.0/22;
    set_real_ip_from 103.31.4.0/22;
    set_real_ip_from 141.101.64.0/18;
    set_real_ip_from 108.162.192.0/18;
    set_real_ip_from 190.93.240.0/20;
    set_real_ip_from 188.114.96.0/20;
    set_real_ip_from 197.234.240.0/22;
    set_real_ip_from 198.41.128.0/17;
    set_real_ip_from 162.158.0.0/15;
    set_real_ip_from 104.16.0.0/12;
    set_real_ip_from 172.64.0.0/13;
    set_real_ip_from 131.0.72.0/22;
    real_ip_header CF-Connecting-IP;
    
    # Next.js app
    location / {
        proxy_pass http://localhost:3000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        proxy_cache_bypass $http_upgrade;
    }
    
    # API endpoints
    location /api {
        proxy_pass http://localhost:8080;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
EOF
    
    echo "✅ Origin server configuration generated"
}

# Main execution
main() {
    echo "Starting Cloudflare setup..."
    
    check_requirements
    get_credentials
    init_terraform
    plan_terraform
    setup_workers
    configure_page_rules
    generate_origin_config
    test_configuration
    
    echo ""
    echo "==================================="
    echo "✅ Cloudflare Setup Complete!"
    echo "==================================="
    echo ""
    echo "Next steps:"
    echo "1. Update your domain's nameservers to Cloudflare's"
    echo "2. Configure your origin server with nginx-origin.conf"
    echo "3. Generate Cloudflare Origin CA certificate"
    echo "4. Monitor performance at: https://dash.cloudflare.com"
    echo ""
    echo "Useful commands:"
    echo "  terraform plan     - Preview changes"
    echo "  terraform apply    - Apply changes"
    echo "  wrangler tail      - Monitor worker logs"
    echo "  wrangler dev       - Test worker locally"
}

# Run main function
main "$@"