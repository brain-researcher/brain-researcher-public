#!/bin/bash

# Deploy BR-KG Graph API to Railway

echo "🚀 Deploying BR-KG Graph API to Railway..."

# Check if railway CLI is installed
if ! command -v railway &> /dev/null; then
    echo "❌ Railway CLI is not installed. Please install it first:"
    echo "   npm install -g @railway/cli"
    exit 1
fi

# Check if we're in the correct directory
if [ ! -f "br_kg_graph_export.json" ]; then
    echo "❌ Missing br_kg_graph_export.json. Please run export_graph_data.py first."
    exit 1
fi

# Login to Railway (if not already logged in)
echo "📝 Logging in to Railway..."
railway login

# Deploy the application
echo "🚂 Deploying to Railway..."
railway up

echo "✅ Deployment complete!"
echo ""
echo "📊 To view logs: railway logs"
echo "🌐 To get URL: railway open"
echo ""
echo "📡 Test your deployment:"
echo "   curl https://your-app.railway.app/health"
echo "   curl https://your-app.railway.app/stats"
