#!/bin/bash

# Install nginx configuration for Brain Researcher
# Run this script with sudo

set -e

echo "===================================="
echo "🚀 Installing Nginx Configuration"
echo "===================================="
echo ""

# Check if running with sudo
if [ "$EUID" -ne 0 ]; then 
    echo "❌ Please run this script with sudo:"
    echo "   sudo ./install_nginx_config.sh"
    exit 1
fi

# Backup existing default config if it exists
if [ -f /etc/nginx/sites-enabled/default ]; then
    echo "📋 Backing up existing default configuration..."
    cp /etc/nginx/sites-enabled/default /etc/nginx/sites-enabled/default.backup.$(date +%Y%m%d-%H%M%S)
    echo "✅ Backup created"
fi

# Copy the configuration file
echo "📝 Installing Brain Researcher nginx configuration..."
cp ${BR_REPO_ROOT}/infrastructure/nginx/brain-researcher.conf /etc/nginx/sites-available/brain-researcher

# Enable the site
echo "🔗 Enabling Brain Researcher site..."
ln -sf /etc/nginx/sites-available/brain-researcher /etc/nginx/sites-enabled/brain-researcher

# Remove default site to avoid conflicts
if [ -L /etc/nginx/sites-enabled/default ]; then
    echo "🔧 Disabling default site to avoid conflicts..."
    rm /etc/nginx/sites-enabled/default
fi

# Test the configuration
echo "🧪 Testing nginx configuration..."
nginx -t

if [ $? -eq 0 ]; then
    echo "✅ Configuration test passed!"
    
    # Reload nginx
    echo "🔄 Reloading nginx..."
    systemctl reload nginx
    
    # Check nginx status
    echo "📊 Checking nginx status..."
    systemctl status nginx --no-pager | head -10
    
    echo ""
    echo "===================================="
    echo "✅ Nginx Configuration Complete!"
    echo "===================================="
    echo ""
    echo "Your Brain Researcher platform will be accessible at:"
    echo ""
    echo "  🌐 https://brain-researcher.com - Web UI"
    echo "  🔌 https://api.brain-researcher.com - API"
    echo "  🧠 https://kg.brain-researcher.com - Knowledge Graph"
    echo "  🤖 https://agent.brain-researcher.com - Agent Service"
    echo ""
    echo "Make sure your services are running:"
    echo "  cd ${BR_REPO_ROOT}"
    echo "  ./start_services.sh"
    echo ""
else
    echo "❌ Configuration test failed!"
    echo "Please check the configuration file for errors."
    exit 1
fi