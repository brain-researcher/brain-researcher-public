#!/bin/bash

# BR-KG GLM FitLins Deployment Script
# This script prepares the application for deployment

set -e

echo "🚀 BR-KG GLM FitLins Deployment Script"
echo "========================================"

# Check if we're in the right directory
if [ ! -f "app.py" ]; then
    echo "❌ Error: app.py not found. Please run this script from the neurokg directory."
    exit 1
fi

# Check if JSON export exists
if [ ! -f "neurokg_glmfitlins_export.json" ]; then
    echo "📊 Creating database export..."
    python export_data.py

    if [ ! -f "neurokg_glmfitlins_export.json" ]; then
        echo "❌ Error: Failed to create database export."
        exit 1
    fi
else
    echo "✅ Database export found"
fi

# Test the application locally
echo "🧪 Testing application locally..."
export NEUROKG_GLMFITLINS_DB_PATH=neurokg_glmfitlins_export.json
export FLASK_ENV=production

# Kill any existing process on port 5000
pkill -f "python app.py" 2>/dev/null || true

# Start the app in background
python app.py &
APP_PID=$!

# Wait for app to start
sleep 5

# Test health endpoint
echo "🏥 Testing health endpoint..."
if curl -s http://localhost:5000/health | grep -q "healthy"; then
    echo "✅ Health check passed"
else
    echo "❌ Health check failed"
    kill $APP_PID
    exit 1
fi

# Test API endpoints
echo "🔌 Testing API endpoints..."
if curl -s http://localhost:5000/api/glmfitlins/stats | grep -q "datasets"; then
    echo "✅ API endpoints working"
else
    echo "❌ API endpoints failed"
    kill $APP_PID
    exit 1
fi

# Stop the test app
kill $APP_PID

echo ""
echo "🎉 Application ready for deployment!"
echo ""
echo "📋 Next steps:"
echo "1. Push your code to GitHub"
echo "2. Connect to Railway: https://railway.app"
echo "3. Deploy from GitHub repository"
echo "4. Set environment variables:"
echo "   - NEUROKG_GLMFITLINS_DB_PATH=neurokg_glmfitlins_export.json"
echo "   - FLASK_ENV=production"
echo "5. Optional: Configure custom domain with Cloudflare"
echo ""
echo "📖 Full deployment guide: see DEPLOYMENT.md"
echo ""
echo "✨ Your BR-KG GLM FitLins app is ready for the world!"
