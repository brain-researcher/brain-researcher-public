#!/bin/bash

# Brain Researcher Smoke Test Runner
# Quick validation test to verify basic functionality

set -e

echo "🧠 Brain Researcher - Smoke Test"
echo "=================================="

# Check if k6 is installed
if ! command -v k6 &> /dev/null; then
    echo "❌ k6 is not installed. Please install k6 first:"
    echo "   Installation instructions: https://k6.io/docs/get-started/installation/"
    exit 1
fi

# Set environment variables
export TEST_SCENARIO="smoke"
export TEST_START_TIME=$(date +%s%3N)

# Service URLs (can be overridden by environment)
export ORCHESTRATOR_URL=${ORCHESTRATOR_URL:-"http://localhost:3001"}
export BR_KG_URL=${BR_KG_URL:-"http://localhost:5000"}
export AGENT_URL=${AGENT_URL:-"http://localhost:8000"}

echo "🔧 Configuration:"
echo "   Orchestrator: $ORCHESTRATOR_URL"
echo "   BR-KG:      $BR_KG_URL"
echo "   Agent:        $AGENT_URL"
echo ""

# Create reports directory
mkdir -p reports

# Check if services are running
echo "🔍 Checking service availability..."

check_service() {
    local service_name=$1
    local service_url=$2

    if curl -f -s --max-time 5 "$service_url/health" > /dev/null 2>&1; then
        echo "   ✅ $service_name is available"
        return 0
    else
        echo "   ❌ $service_name is not available at $service_url"
        return 1
    fi
}

services_available=0

if check_service "Orchestrator" "$ORCHESTRATOR_URL"; then
    ((services_available++))
fi

if check_service "BR-KG" "$BR_KG_URL"; then
    ((services_available++))
fi

if check_service "Agent" "$AGENT_URL"; then
    ((services_available++))
fi

if [ $services_available -lt 2 ]; then
    echo ""
    echo "❌ Insufficient services available ($services_available/3)"
    echo "   At least 2 services must be running for smoke testing"
    echo ""
    echo "💡 To start services:"
    echo "   br serve orchestrator  # Port 3001"
    echo "   br serve kg            # Port 5000"
    echo "   br serve agent         # Port 8000"
    exit 1
fi

echo ""
echo "🚀 Starting smoke test (should complete in ~30 seconds)..."
echo ""

# Run the smoke test
k6 run \
    --out json=reports/smoke-test-results.json \
    --summary-export=reports/smoke-test-summary.json \
    run-performance-tests.js

echo ""
echo "✅ Smoke test completed!"
echo ""
echo "📊 Results:"
echo "   JSON Report:    reports/smoke-test-results.json"
echo "   Summary:        reports/smoke-test-summary.json"
echo "   HTML Report:    reports/smoke_test_*.html"
echo ""
echo "💡 Next steps:"
echo "   - Review the HTML report for detailed analysis"
echo "   - If smoke test passes, run load tests: ./scripts/run-load-test.sh"
echo "   - For stress testing: ./scripts/run-stress-test.sh"
