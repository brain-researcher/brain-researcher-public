#!/bin/bash

# Test Railway deployment script
# Usage: ./test_railway_deployment.sh YOUR_RAILWAY_URL

RAILWAY_URL=${1:-"https://your-railway-url.up.railway.app"}

echo "🚂 Testing Railway Deployment"
echo "=============================="
echo "URL: $RAILWAY_URL"
echo ""

echo "🏥 Testing Health Check..."
curl -s "$RAILWAY_URL/health" | jq '.' || echo "Failed to get JSON response"
echo ""

echo "📊 Testing API Stats..."
curl -s "$RAILWAY_URL/api/glmfitlins/stats" | jq '.glmfitlins' || echo "Failed to get stats"
echo ""

echo "🧠 Testing Brain Data..."
curl -s "$RAILWAY_URL/api/glmfitlins/constructs?limit=3" | jq '.constructs[0:2]' || echo "Failed to get constructs"
echo ""

echo "🎉 Railway deployment test complete!"
echo ""
echo "📱 Your BR-KG URLs:"
echo "   🏠 Homepage: $RAILWAY_URL"
echo "   🌐 Web UI (if deployed separately): https://${PUBLIC_HOSTNAME}/en/kg/explore"
echo "   🔌 API: $RAILWAY_URL/api/glmfitlins/"
echo ""
echo "🌐 Ready for ${PUBLIC_HOSTNAME} CNAME setup!"
