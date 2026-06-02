#!/bin/bash

# Brain Researcher Load Test Runner
# Tests normal production load patterns

set -e

echo "🧠 Brain Researcher - Load Test"
echo "==============================="

# Check if k6 is installed
if ! command -v k6 &> /dev/null; then
    echo "❌ k6 is not installed. Please install k6 first:"
    echo "   Installation instructions: https://k6.io/docs/get-started/installation/"
    exit 1
fi

# Set environment variables
export TEST_SCENARIO="load"
export TEST_START_TIME=$(date +%s%3N)

# Service URLs (can be overridden by environment)
export ORCHESTRATOR_URL=${ORCHESTRATOR_URL:-"http://localhost:3001"}
export BR_KG_URL=${BR_KG_URL:-"http://localhost:5000"}
export AGENT_URL=${AGENT_URL:-"http://localhost:8000"}

echo "🔧 Configuration:"
echo "   Orchestrator: $ORCHESTRATOR_URL"
echo "   BR-KG:      $BR_KG_URL"
echo "   Agent:        $AGENT_URL"
echo "   Expected Duration: ~9 minutes"
echo ""

# Create reports directory
mkdir -p reports

# Verify services are healthy
echo "🔍 Pre-test service health check..."

check_service() {
    local service_name=$1
    local service_url=$2

    if curl -f -s --max-time 10 "$service_url/health" > /dev/null 2>&1; then
        echo "   ✅ $service_name is healthy"
        return 0
    else
        echo "   ❌ $service_name health check failed at $service_url"
        return 1
    fi
}

services_healthy=0

if check_service "Orchestrator" "$ORCHESTRATOR_URL"; then
    ((services_healthy++))
fi

if check_service "BR-KG" "$BR_KG_URL"; then
    ((services_healthy++))
fi

if check_service "Agent" "$AGENT_URL"; then
    ((services_healthy++))
fi

if [ $services_healthy -lt 3 ]; then
    echo ""
    echo "⚠️  Warning: Only $services_healthy/3 services are healthy"
    echo "   Load testing will continue but results may not be representative"
    echo ""

    read -p "Continue with load test? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Load test cancelled."
        exit 1
    fi
fi

echo ""
echo "🚀 Starting load test..."
echo "   Phase 1: Ramp up to 10 VUs (2 minutes)"
echo "   Phase 2: Normal load 50 VUs (5 minutes)"
echo "   Phase 3: Ramp down (2 minutes)"
echo ""
echo "📊 Monitoring performance metrics..."
echo ""

# Run the load test with specific scenario
k6 run \
    --out json=reports/load-test-results.json \
    --summary-export=reports/load-test-summary.json \
    scenarios/load-test.js

echo ""
echo "✅ Load test completed!"
echo ""

# Analyze results
if [ -f "reports/load-test-results.json" ]; then
    echo "📊 Quick Results Analysis:"
    echo "========================="

    # Extract key metrics using jq if available
    if command -v jq &> /dev/null; then
        echo "   Total Requests: $(jq -r '.metrics.http_reqs.values.count // "N/A"' reports/load-test-summary.json)"
        echo "   Success Rate: $(jq -r '(1 - (.metrics.http_req_failed.values.rate // 0)) * 100 | floor' reports/load-test-summary.json)%"
        echo "   Avg Response Time: $(jq -r '.metrics.http_req_duration.values.avg // "N/A" | if type == "number" then (. | floor | tostring + "ms") else . end' reports/load-test-summary.json)"
        echo "   P95 Response Time: $(jq -r '.metrics.http_req_duration.values["p(95)"] // "N/A" | if type == "number" then (. | floor | tostring + "ms") else . end' reports/load-test-summary.json)"
        echo "   Throughput: $(jq -r '.metrics.http_reqs.values.rate // "N/A" | if type == "number" then (. * 100 | floor | . / 100 | tostring + " req/s") else . end' reports/load-test-summary.json)"

        # Check if thresholds passed
        local failed_thresholds=$(jq -r '[.metrics[] | select(.thresholds) | .thresholds | to_entries[] | select(.value.ok == false)] | length' reports/load-test-summary.json)

        if [ "$failed_thresholds" -eq 0 ]; then
            echo "   🎯 All performance thresholds: ✅ PASSED"
        else
            echo "   🎯 Performance thresholds: ❌ $failed_thresholds FAILED"
        fi
    fi
fi

echo ""
echo "📁 Generated Reports:"
echo "   JSON Results:   reports/load-test-results.json"
echo "   Summary:        reports/load-test-summary.json"
echo "   HTML Report:    reports/load_test_*.html"
echo ""

# Check for performance issues
if command -v jq &> /dev/null && [ -f "reports/load-test-summary.json" ]; then
    error_rate=$(jq -r '.metrics.http_req_failed.values.rate // 0' reports/load-test-summary.json)
    p95_response=$(jq -r '.metrics.http_req_duration.values["p(95)"] // 0' reports/load-test-summary.json)

    echo "🔍 Performance Assessment:"

    if (( $(echo "$error_rate > 0.05" | bc -l 2>/dev/null || echo "0") )); then
        echo "   ⚠️  High error rate detected: $(echo "$error_rate * 100" | bc -l | cut -d. -f1)%"
        echo "       Investigate failing endpoints and implement circuit breakers"
    fi

    if (( $(echo "$p95_response > 2000" | bc -l 2>/dev/null || echo "0") )); then
        echo "   🐌 High P95 response time: ${p95_response}ms"
        echo "       Consider caching, database optimization, or scaling"
    fi

    if (( $(echo "$error_rate <= 0.05" | bc -l 2>/dev/null || echo "1") )) && (( $(echo "$p95_response <= 2000" | bc -l 2>/dev/null || echo "1") )); then
        echo "   ✅ System performance is within acceptable limits"
    fi
fi

echo ""
echo "💡 Next steps:"
echo "   - Review the detailed HTML report"
echo "   - If load test passes, consider stress testing: ./scripts/run-stress-test.sh"
echo "   - For extended testing: ./scripts/run-soak-test.sh"
echo "   - For spike testing: ./scripts/run-spike-test.sh"
