#!/bin/bash

# Setup script for nginx configuration
# This configures nginx to route subdomains to Brain Researcher services

set -e

echo "=================================="
echo "🚀 Brain Researcher Nginx Setup"
echo "=================================="
echo ""

# Check if nginx is installed
if ! command -v nginx &> /dev/null; then
    echo "❌ Nginx not found. Installing..."
    sudo apt update
    sudo apt install -y nginx
else
    echo "✅ Nginx is installed"
fi

# Backup existing configuration
if [ -f /etc/nginx/sites-enabled/default ]; then
    echo "📋 Backing up existing configuration..."
    sudo cp /etc/nginx/sites-enabled/default /etc/nginx/sites-enabled/default.backup.$(date +%Y%m%d)
fi

# Copy the configuration
echo "📝 Installing Brain Researcher nginx configuration..."
sudo cp brain-researcher.conf /etc/nginx/sites-available/brain-researcher

# Create symbolic link
echo "🔗 Enabling site..."
sudo ln -sf /etc/nginx/sites-available/brain-researcher /etc/nginx/sites-enabled/

# Disable default site to avoid conflicts
if [ -f /etc/nginx/sites-enabled/default ]; then
    echo "🔧 Disabling default site..."
    sudo rm -f /etc/nginx/sites-enabled/default
fi

# Test nginx configuration
echo "🧪 Testing nginx configuration..."
sudo nginx -t

if [ $? -eq 0 ]; then
    echo "✅ Configuration test passed"
    
    # Reload nginx
    echo "🔄 Reloading nginx..."
    sudo systemctl reload nginx
    
    echo ""
    echo "=================================="
    echo "✅ Nginx Setup Complete!"
    echo "=================================="
    echo ""
    echo "Your services are now accessible at:"
    echo "  🌐 https://${PUBLIC_HOSTNAME} - Web UI"
    echo "  🔌 https://api.${PUBLIC_HOSTNAME} - API"
    echo "  🧠 https://kg.${PUBLIC_HOSTNAME} - Knowledge Graph"
    echo "  🤖 https://agent.${PUBLIC_HOSTNAME} - Agent Service"
    echo ""
    echo "Note: Cloudflare is handling SSL, so these work over HTTPS!"
else
    echo "❌ Configuration test failed. Please check the configuration."
    exit 1
fi

# Check service status
echo "📊 Service Status:"
echo ""
echo "Checking services..."
curl -s http://localhost:3000 > /dev/null 2>&1 && echo "✅ Web UI (port 3000) is running" || echo "⚠️ Web UI (port 3000) is not responding"
curl -s http://localhost:8000 > /dev/null 2>&1 && echo "✅ API (port 8000) is running" || echo "⚠️ API (port 8000) is not responding"
curl -s http://localhost:5000 > /dev/null 2>&1 && echo "✅ BR-KG (port 5000) is running" || echo "⚠️ BR-KG (port 5000) is not responding"

echo ""
echo "🔍 Test your setup:"
echo "  curl -I https://${PUBLIC_HOSTNAME}"
echo "  curl https://api.${PUBLIC_HOSTNAME}/health"
echo "  curl https://kg.${PUBLIC_HOSTNAME}/api/stats"