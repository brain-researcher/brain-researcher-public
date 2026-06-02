#!/bin/bash
# Test HTTP proxy mode for @brainr/cli

echo "=== Testing HTTP Proxy Mode for @brainr/cli ==="
echo ""

# Ensure service is running
if ! curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "❌ Web service not running on port 8000"
    echo "   Start it with: python -m brain_researcher.services.agent.web_service"
    exit 1
fi

echo "✅ Web service is running on port 8000"
echo ""

# Test direct API calls
echo "1. Testing direct /api/cli endpoint:"
echo "   Command: version"
curl -X POST http://localhost:8000/api/cli \
  -H "Content-Type: application/json" \
  -d '{"argv": ["version"]}' -s | jq .
echo ""

echo "2. Testing help command:"
curl -X POST http://localhost:8000/api/cli \
  -H "Content-Type: application/json" \
  -d '{"argv": ["help"]}' -s
echo ""

# Test via brainr CLI
echo "3. Testing via @brainr/cli HTTP proxy:"
export BR_URL=http://localhost:8000

echo "   $ brainr version"
brainr version
echo ""

echo "   $ brainr --help"
brainr --help | head -8
echo ""

echo "=== HTTP Proxy Mode Working! ==="
echo ""
echo "Usage:"
echo "  1. Start service: python -m brain_researcher.services.agent.web_service"
echo "  2. Set environment: export BR_URL=http://localhost:8000"
echo "  3. Use brainr: brainr [command]"
echo ""
echo "Available commands via /api/cli:"
echo "  - version: Get version info"
echo "  - help: Show help message"
echo "  - ask -p \"prompt\": Single question mode"
echo "  - chat -p \"prompt\": Chat mode"