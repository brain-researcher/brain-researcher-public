#!/bin/bash

# Brain Researcher Complete Performance Test Suite Runner
# Runs all performance test scenarios in sequence

set -e

echo "🧠 Brain Researcher - Complete Performance Test Suite"
echo "===================================================="
echo ""

# Configuration
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
SUITE_REPORT_DIR="reports/suite_$TIMESTAMP"
RUN_SOAK_TEST=${RUN_SOAK_TEST:-false}  # Soak test is optional due to long duration

# Check if k6 is installed
if ! command -v k6 &> /dev/null; then
    echo "❌ k6 is not installed. Please install k6 first:"
    echo "   Installation instructions: https://k6.io/docs/get-started/installation/"
    exit 1
fi

# Service URLs (can be overridden by environment)
export ORCHESTRATOR_URL=${ORCHESTRATOR_URL:-"http://localhost:3001"}
export BR_KG_URL=${BR_KG_URL:-"http://localhost:5000"}
export AGENT_URL=${AGENT_URL:-"http://localhost:8000"}

echo "🔧 Test Suite Configuration:"
echo "   Orchestrator: $ORCHESTRATOR_URL"
echo "   BR-KG:      $BR_KG_URL"
echo "   Agent:        $AGENT_URL"
echo "   Include Soak Test: $RUN_SOAK_TEST"
echo ""

# Create suite report directory
mkdir -p "$SUITE_REPORT_DIR"
mkdir -p reports

# Pre-flight service check
echo "🔍 Pre-flight service availability check..."

check_service() {
    local service_name=$1
    local service_url=$2

    if curl -f -s --max-time 10 "$service_url/health" > /dev/null 2>&1; then
        echo "   ✅ $service_name is available"
        return 0
    else
        echo "   ❌ $service_name is not available at $service_url"
        return 1
    fi
}

services_available=0
if check_service "Orchestrator" "$ORCHESTRATOR_URL"; then ((services_available++)); fi
if check_service "BR-KG" "$BR_KG_URL"; then ((services_available++)); fi
if check_service "Agent" "$AGENT_URL"; then ((services_available++)); fi

if [ $services_available -lt 3 ]; then
    echo ""
    echo "⚠️  Warning: Only $services_available/3 services are available"
    echo "   Test suite will continue but results may not be comprehensive"
    echo ""

    if [ $services_available -lt 2 ]; then
        echo "❌ Critical: Less than 2 services available. Cannot proceed."
        echo ""
        echo "💡 To start services:"
        echo "   br serve orchestrator  # Port 3001"
        echo "   br serve kg            # Port 5000"
        echo "   br serve agent         # Port 8000"
        exit 1
    fi

    read -p "Continue with test suite? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Test suite cancelled."
        exit 1
    fi
fi

echo ""
echo "🚀 Starting Performance Test Suite..."
echo "   Estimated total duration: $(if [ "$RUN_SOAK_TEST" = "true" ]; then echo "~50 minutes"; else echo "~15 minutes"; fi)"
echo ""

# Initialize test results tracking
SUITE_START_TIME=$(date +%s)
TEST_RESULTS=()

run_test_scenario() {
    local scenario=$1
    local description=$2
    local expected_duration=$3
    local script_name=$4

    echo "=================================="
    echo "🧪 Test $((${#TEST_RESULTS[@]} + 1)): $scenario - $description"
    echo "   Expected duration: $expected_duration"
    echo "=================================="

    local test_start_time=$(date +%s)
    local test_result="UNKNOWN"
    local error_message=""

    export TEST_SCENARIO="$scenario"
    export TEST_START_TIME=$(date +%s%3N)

    if [ -n "$script_name" ] && [ -f "scenarios/$script_name" ]; then
        # Run specific scenario script
        if timeout 1800 k6 run \
            --out "json=$SUITE_REPORT_DIR/${scenario}-results.json" \
            --summary-export="$SUITE_REPORT_DIR/${scenario}-summary.json" \
            "scenarios/$script_name" 2>&1 | tee "$SUITE_REPORT_DIR/${scenario}-output.log"; then
            test_result="PASSED"
        else
            test_result="FAILED"
            error_message="Test execution failed or timed out"
        fi
    else
        # Run master test script with scenario
        if timeout 1800 k6 run \
            --out "json=$SUITE_REPORT_DIR/${scenario}-results.json" \
            --summary-export="$SUITE_REPORT_DIR/${scenario}-summary.json" \
            run-performance-tests.js 2>&1 | tee "$SUITE_REPORT_DIR/${scenario}-output.log"; then
            test_result="PASSED"
        else
            test_result="FAILED"
            error_message="Test execution failed or timed out"
        fi
    fi

    local test_end_time=$(date +%s)
    local test_duration=$((test_end_time - test_start_time))

    # Analyze results if available
    local requests="N/A"
    local success_rate="N/A"
    local avg_response="N/A"
    local p95_response="N/A"
    local thresholds_passed="N/A"

    if [ -f "$SUITE_REPORT_DIR/${scenario}-summary.json" ] && command -v jq &> /dev/null; then
        requests=$(jq -r '.metrics.http_reqs.values.count // "N/A"' "$SUITE_REPORT_DIR/${scenario}-summary.json")
        success_rate=$(jq -r '(1 - (.metrics.http_req_failed.values.rate // 0)) * 100 | floor' "$SUITE_REPORT_DIR/${scenario}-summary.json")
        avg_response=$(jq -r '.metrics.http_req_duration.values.avg // "N/A" | if type == "number" then (. | floor) else . end' "$SUITE_REPORT_DIR/${scenario}-summary.json")
        p95_response=$(jq -r '.metrics.http_req_duration.values["p(95)"] // "N/A" | if type == "number" then (. | floor) else . end' "$SUITE_REPORT_DIR/${scenario}-summary.json")

        local failed_thresholds=$(jq -r '[.metrics[] | select(.thresholds) | .thresholds | to_entries[] | select(.value.ok == false)] | length' "$SUITE_REPORT_DIR/${scenario}-summary.json")
        if [ "$failed_thresholds" -eq 0 ]; then
            thresholds_passed="✅ ALL"
        else
            thresholds_passed="❌ $failed_thresholds FAILED"
            if [ "$test_result" = "PASSED" ]; then
                test_result="PASSED_WITH_WARNINGS"
            fi
        fi
    fi

    # Store test result
    TEST_RESULTS+=("$scenario|$test_result|$test_duration|$requests|$success_rate|$avg_response|$p95_response|$thresholds_passed|$error_message")

    echo ""
    echo "📊 Test $scenario Results:"
    echo "   Status: $test_result"
    echo "   Duration: ${test_duration}s"
    echo "   Requests: $requests"
    echo "   Success Rate: ${success_rate}%"
    echo "   Avg Response: ${avg_response}ms"
    echo "   P95 Response: ${p95_response}ms"
    echo "   Thresholds: $thresholds_passed"

    if [ -n "$error_message" ]; then
        echo "   Error: $error_message"
    fi

    echo ""

    # Brief pause between tests
    sleep 10
}

# Run test scenarios in order
run_test_scenario "smoke" "Quick Validation" "30 seconds" "smoke-test.js"
run_test_scenario "load" "Normal Production Load" "9 minutes" "load-test.js"
run_test_scenario "stress" "Beyond Normal Capacity" "11 minutes" "stress-test.js"
run_test_scenario "spike" "Sudden Load Increases" "9 minutes" "spike-test.js"

if [ "$RUN_SOAK_TEST" = "true" ]; then
    run_test_scenario "soak" "Extended Duration Stability" "37 minutes" "soak-test.js"
else
    echo "⏭️  Skipping soak test (use RUN_SOAK_TEST=true to include)"
fi

# EventSource/SSE streaming under load
run_test_scenario "sse" "SSE Stream Stability" "3 minutes" "sse-stream-test.js"

# WebSocket testing
run_test_scenario "websocket" "Real-time Communications" "9 minutes" "websocket-test.js"

# Calculate total suite duration
SUITE_END_TIME=$(date +%s)
SUITE_DURATION=$((SUITE_END_TIME - SUITE_START_TIME))
SUITE_DURATION_MINUTES=$((SUITE_DURATION / 60))

echo ""
echo "🏁 Performance Test Suite Completed!"
echo "===================================="
echo "   Total Duration: ${SUITE_DURATION}s (${SUITE_DURATION_MINUTES} minutes)"
echo "   Tests Run: ${#TEST_RESULTS[@]}"
echo ""

# Generate suite summary report
generate_suite_report() {
    cat > "$SUITE_REPORT_DIR/suite-summary.html" << EOF
<!DOCTYPE html>
<html>
<head>
    <title>Brain Researcher Performance Test Suite Report</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 20px; background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; background: white; padding: 30px; border-radius: 10px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); }
        .header { background: linear-gradient(135deg, #667eea, #764ba2); color: white; padding: 30px; margin: -30px -30px 30px; border-radius: 10px 10px 0 0; }
        .suite-stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 20px; margin: 30px 0; }
        .stat-card { background: #f8f9fa; padding: 20px; border-radius: 8px; text-align: center; border-left: 4px solid #667eea; }
        .stat-value { font-size: 2em; font-weight: bold; color: #333; }
        .test-results { margin: 30px 0; }
        .test-row { display: grid; grid-template-columns: 150px 120px 80px 100px 100px 120px 120px 200px; gap: 15px; padding: 15px; border-bottom: 1px solid #eee; align-items: center; }
        .test-row:nth-child(even) { background: #f8f9fa; }
        .test-header { font-weight: bold; background: #667eea; color: white; border-radius: 5px 5px 0 0; }
        .status-passed { color: #28a745; font-weight: bold; }
        .status-failed { color: #dc3545; font-weight: bold; }
        .status-warning { color: #ffc107; font-weight: bold; }
        .recommendations { background: #e7f3ff; padding: 20px; border-radius: 8px; margin: 30px 0; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🧠 Brain Researcher Performance Test Suite</h1>
            <p>Complete test suite executed on $(date)</p>
            <p>Duration: ${SUITE_DURATION_MINUTES} minutes | Tests: ${#TEST_RESULTS[@]}</p>
        </div>

        <div class="suite-stats">
            <div class="stat-card">
                <div class="stat-value">$(echo "${TEST_RESULTS[@]}" | grep -o "PASSED" | wc -l)</div>
                <div>Tests Passed</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">$(echo "${TEST_RESULTS[@]}" | grep -o "FAILED" | wc -l)</div>
                <div>Tests Failed</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">${SUITE_DURATION_MINUTES}</div>
                <div>Total Minutes</div>
            </div>
            <div class="stat-card">
                <div class="stat-value">$services_available/3</div>
                <div>Services Available</div>
            </div>
        </div>

        <div class="test-results">
            <h2>📊 Test Results Summary</h2>
            <div class="test-row test-header">
                <div>Test Scenario</div>
                <div>Status</div>
                <div>Duration</div>
                <div>Requests</div>
                <div>Success Rate</div>
                <div>Avg Response</div>
                <div>P95 Response</div>
                <div>Thresholds</div>
            </div>
EOF

    for result in "${TEST_RESULTS[@]}"; do
        IFS='|' read -r scenario status duration requests success_rate avg_response p95_response thresholds error_message <<< "$result"

        local status_class="status-passed"
        if [[ "$status" == *"FAILED"* ]]; then
            status_class="status-failed"
        elif [[ "$status" == *"WARNING"* ]]; then
            status_class="status-warning"
        fi

        cat >> "$SUITE_REPORT_DIR/suite-summary.html" << EOF
            <div class="test-row">
                <div>$scenario</div>
                <div class="$status_class">$status</div>
                <div>${duration}s</div>
                <div>$requests</div>
                <div>${success_rate}%</div>
                <div>${avg_response}ms</div>
                <div>${p95_response}ms</div>
                <div>$thresholds</div>
            </div>
EOF
    done

    cat >> "$SUITE_REPORT_DIR/suite-summary.html" << EOF
        </div>

        <div class="recommendations">
            <h3>💡 Suite Recommendations</h3>
            <ul>
                <li>Review individual test reports for detailed analysis</li>
                <li>Monitor production systems based on identified performance patterns</li>
                <li>Consider implementing performance regression testing in CI/CD</li>
                <li>Schedule regular performance testing to catch regressions early</li>
            </ul>
        </div>

        <div>
            <h3>📁 Individual Test Reports</h3>
            <ul>
$(for result in "${TEST_RESULTS[@]}"; do
    scenario=$(echo "$result" | cut -d'|' -f1)
    echo "                <li><a href=\"${scenario}-summary.html\">${scenario} Test Detailed Report</a></li>"
done)
            </ul>
        </div>
    </div>
</body>
</html>
EOF
}

generate_suite_report

# Display final results table
echo "📊 Final Test Results:"
echo "======================"
printf "%-12s %-20s %-10s %-10s %-12s %-12s %-12s\n" "Scenario" "Status" "Duration" "Requests" "Success%" "AvgResp(ms)" "P95Resp(ms)"
printf "%-12s %-20s %-10s %-10s %-12s %-12s %-12s\n" "--------" "------" "--------" "--------" "--------" "-----------" "-----------"

for result in "${TEST_RESULTS[@]}"; do
    IFS='|' read -r scenario status duration requests success_rate avg_response p95_response thresholds error_message <<< "$result"
    printf "%-12s %-20s %-10s %-10s %-12s %-12s %-12s\n" "$scenario" "$status" "${duration}s" "$requests" "${success_rate}%" "${avg_response}ms" "${p95_response}ms"
done

echo ""
echo "📁 Complete Suite Reports Generated:"
echo "   Suite Summary:  $SUITE_REPORT_DIR/suite-summary.html"
echo "   Individual Reports: $SUITE_REPORT_DIR/"
echo ""

# Overall assessment
FAILED_TESTS=$(echo "${TEST_RESULTS[@]}" | grep -o "FAILED" | wc -l)
PASSED_TESTS=$(echo "${TEST_RESULTS[@]}" | grep -o "PASSED" | wc -l)

if [ "$FAILED_TESTS" -eq 0 ]; then
    echo "🎉 All tests passed! System performance is within acceptable limits."
elif [ "$FAILED_TESTS" -lt "$((${#TEST_RESULTS[@]} / 2))" ]; then
    echo "⚠️  Some tests failed ($FAILED_TESTS/${#TEST_RESULTS[@]}). Review individual reports for issues."
else
    echo "❌ Multiple test failures ($FAILED_TESTS/${#TEST_RESULTS[@]}). System requires performance optimization."
fi

echo ""
echo "🚀 Performance testing suite completed successfully!"
echo "   View $SUITE_REPORT_DIR/suite-summary.html for comprehensive analysis"
