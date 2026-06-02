#!/bin/bash

# Comprehensive Load Balancing and Auto-scaling Test Suite
# This script runs all load balancing tests in the correct order
# Specialty runner: not part of default CI. Requires local load-test services
# and optional k6 installation.

set -e  # Exit on any error

# Configuration
export TEST_ENVIRONMENT=${TEST_ENVIRONMENT:-development}
export BASE_URL=${BASE_URL:-http://localhost:3000}
export PARALLEL_TESTS=${PARALLEL_TESTS:-false}

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Brain Researcher Load Balancing Test Suite${NC}"
echo -e "${BLUE}========================================${NC}"
echo "Environment: $TEST_ENVIRONMENT"
echo "Base URL: $BASE_URL"
echo "Timestamp: $(date)"
echo ""

# Function to print test status
print_status() {
    local status=$1
    local message=$2
    if [ "$status" = "SUCCESS" ]; then
        echo -e "${GREEN}✓ $message${NC}"
    elif [ "$status" = "FAILURE" ]; then
        echo -e "${RED}✗ $message${NC}"
    elif [ "$status" = "WARNING" ]; then
        echo -e "${YELLOW}⚠ $message${NC}"
    else
        echo -e "${BLUE}ℹ $message${NC}"
    fi
}

# Function to check if required services are running
check_prerequisites() {
    print_status "INFO" "Checking prerequisites..."

    # Check if Docker is running
    if ! docker info > /dev/null 2>&1; then
        print_status "FAILURE" "Docker is not running"
        exit 1
    fi

    # Check if required services are available
    local required_services=("haproxy" "redis" "neo4j")

    for service in "${required_services[@]}"; do
        if docker ps --format "table {{.Names}}" | grep -q "$service"; then
            print_status "SUCCESS" "$service is running"
        else
            print_status "WARNING" "$service may not be running"
        fi
    done

    # Check if base URL is accessible
    if curl -f -s "$BASE_URL/health" > /dev/null 2>&1; then
        print_status "SUCCESS" "Base URL is accessible"
    else
        print_status "WARNING" "Base URL may not be accessible"
    fi

    echo ""
}

# Function to run pytest tests
run_pytest_test() {
    local test_file=$1
    local test_name=$2

    print_status "INFO" "Running $test_name..."

    if python -m pytest "$test_file" -v --tb=short --junit-xml="reports/junit_$(basename $test_file .py).xml" 2>&1; then
        print_status "SUCCESS" "$test_name completed successfully"
        return 0
    else
        print_status "FAILURE" "$test_name failed"
        return 1
    fi
}

# Function to run K6 tests
run_k6_test() {
    local scenario=$1
    local test_name=$2
    local config_file="k6/config/${TEST_ENVIRONMENT}.json"

    print_status "INFO" "Running $test_name..."

    if command -v k6 > /dev/null 2>&1; then
        if k6 run --config "$config_file" --out "json=reports/k6_$(basename $scenario .js).json" "k6/scenarios/$scenario" 2>&1; then
            print_status "SUCCESS" "$test_name completed successfully"
            return 0
        else
            print_status "FAILURE" "$test_name failed"
            return 1
        fi
    else
        print_status "WARNING" "K6 not installed, skipping $test_name"
        return 2
    fi
}

# Create reports directory
mkdir -p reports
mkdir -p reports/screenshots

# Start test execution
print_status "INFO" "Starting comprehensive test suite..."
echo ""

# Check prerequisites
check_prerequisites

# Test execution results
declare -a test_results
declare -a test_names

# Phase 1: Unit Tests for Load Balancing Components
echo -e "${BLUE}Phase 1: Component Unit Tests${NC}"
echo "=================================="

# HAProxy Load Balancing Tests
if run_pytest_test "test_haproxy_load_balancing.py" "HAProxy Load Balancing Tests"; then
    test_results+=("PASS")
else
    test_results+=("FAIL")
fi
test_names+=("HAProxy Load Balancing")

# Auto-scaling System Tests
if run_pytest_test "test_autoscaler.py" "Auto-scaling System Tests"; then
    test_results+=("PASS")
else
    test_results+=("FAIL")
fi
test_names+=("Auto-scaling System")

# Blue-Green Deployment Tests
if run_pytest_test "test_blue_green_deployment.py" "Blue-Green Deployment Tests"; then
    test_results+=("PASS")
else
    test_results+=("FAIL")
fi
test_names+=("Blue-Green Deployment")

# Connection Pooling Tests
if run_pytest_test "test_connection_pooling.py" "Connection Pooling Tests"; then
    test_results+=("PASS")
else
    test_results+=("FAIL")
fi
test_names+=("Connection Pooling")

# Kubernetes HPA Tests
if run_pytest_test "test_k8s_hpa.py" "Kubernetes HPA Tests"; then
    test_results+=("PASS")
else
    test_results+=("FAIL")
fi
test_names+=("Kubernetes HPA")

echo ""

# Phase 2: K6 Load Testing Scenarios
echo -e "${BLUE}Phase 2: K6 Load Testing Scenarios${NC}"
echo "===================================="

# Standard Load Test
result=$(run_k6_test "load-test.js" "Standard Load Test")
case $? in
    0) test_results+=("PASS") ;;
    1) test_results+=("FAIL") ;;
    2) test_results+=("SKIP") ;;
esac
test_names+=("K6 Load Test")

# Stress Test
result=$(run_k6_test "stress-test.js" "Stress Test")
case $? in
    0) test_results+=("PASS") ;;
    1) test_results+=("FAIL") ;;
    2) test_results+=("SKIP") ;;
esac
test_names+=("K6 Stress Test")

# Spike Test
result=$(run_k6_test "spike-test.js" "Spike Test")
case $? in
    0) test_results+=("PASS") ;;
    1) test_results+=("FAIL") ;;
    2) test_results+=("SKIP") ;;
esac
test_names+=("K6 Spike Test")

# Only run soak test if explicitly requested (takes hours)
if [ "$RUN_SOAK_TEST" = "true" ]; then
    result=$(run_k6_test "soak-test.js" "Soak Test (Long Duration)")
    case $? in
        0) test_results+=("PASS") ;;
        1) test_results+=("FAIL") ;;
        2) test_results+=("SKIP") ;;
    esac
    test_names+=("K6 Soak Test")
else
    print_status "INFO" "Soak test skipped (set RUN_SOAK_TEST=true to enable)"
fi

# WebSocket Test
result=$(run_k6_test "websocket-test.js" "WebSocket Load Test")
case $? in
    0) test_results+=("PASS") ;;
    1) test_results+=("FAIL") ;;
    2) test_results+=("SKIP") ;;
esac
test_names+=("K6 WebSocket Test")

# API Endpoints Test
result=$(run_k6_test "api-endpoints-test.js" "API Endpoints Test")
case $? in
    0) test_results+=("PASS") ;;
    1) test_results+=("FAIL") ;;
    2) test_results+=("SKIP") ;;
esac
test_names+=("K6 API Endpoints Test")

echo ""

# Phase 3: Integration Tests
echo -e "${BLUE}Phase 3: System Integration Tests${NC}"
echo "=================================="

# Complete System Integration Test
if run_pytest_test "integration/load_balancing/test_complete_system.py" "Complete System Integration Tests"; then
    test_results+=("PASS")
else
    test_results+=("FAIL")
fi
test_names+=("System Integration")

echo ""

# Generate Test Report
echo -e "${BLUE}========================================${NC}"
echo -e "${BLUE}Test Results Summary${NC}"
echo -e "${BLUE}========================================${NC}"

total_tests=${#test_results[@]}
passed_tests=0
failed_tests=0
skipped_tests=0

for i in "${!test_results[@]}"; do
    result="${test_results[$i]}"
    name="${test_names[$i]}"

    case "$result" in
        "PASS")
            print_status "SUCCESS" "$name"
            ((passed_tests++))
            ;;
        "FAIL")
            print_status "FAILURE" "$name"
            ((failed_tests++))
            ;;
        "SKIP")
            print_status "WARNING" "$name (SKIPPED)"
            ((skipped_tests++))
            ;;
    esac
done

echo ""
echo "Total Tests: $total_tests"
echo "Passed: $passed_tests"
echo "Failed: $failed_tests"
echo "Skipped: $skipped_tests"

# Calculate success rate
success_rate=$(( (passed_tests * 100) / (total_tests - skipped_tests) ))
echo "Success Rate: $success_rate%"

# Overall result
if [ $failed_tests -eq 0 ]; then
    print_status "SUCCESS" "All tests passed successfully!"
    exit_code=0
else
    print_status "FAILURE" "Some tests failed. Check logs for details."
    exit_code=1
fi

# Generate HTML report if possible
if command -v python3 > /dev/null 2>&1; then
    print_status "INFO" "Generating HTML report..."

    # Create a simple HTML report
    cat > reports/test_report.html << EOF
<!DOCTYPE html>
<html>
<head>
    <title>Load Balancing Test Results</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .success { color: green; }
        .failure { color: red; }
        .warning { color: orange; }
        .summary { background: #f5f5f5; padding: 15px; border-radius: 5px; }
        table { border-collapse: collapse; width: 100%; }
        th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        th { background-color: #f2f2f2; }
    </style>
</head>
<body>
    <h1>Brain Researcher Load Balancing Test Results</h1>
    <div class="summary">
        <h2>Summary</h2>
        <p><strong>Environment:</strong> $TEST_ENVIRONMENT</p>
        <p><strong>Date:</strong> $(date)</p>
        <p><strong>Total Tests:</strong> $total_tests</p>
        <p><strong>Passed:</strong> $passed_tests</p>
        <p><strong>Failed:</strong> $failed_tests</p>
        <p><strong>Skipped:</strong> $skipped_tests</p>
        <p><strong>Success Rate:</strong> $success_rate%</p>
    </div>

    <h2>Test Details</h2>
    <table>
        <tr>
            <th>Test Name</th>
            <th>Status</th>
        </tr>
EOF

    for i in "${!test_results[@]}"; do
        result="${test_results[$i]}"
        name="${test_names[$i]}"

        case "$result" in
            "PASS")
                echo "        <tr><td>$name</td><td class=\"success\">PASSED</td></tr>" >> reports/test_report.html
                ;;
            "FAIL")
                echo "        <tr><td>$name</td><td class=\"failure\">FAILED</td></tr>" >> reports/test_report.html
                ;;
            "SKIP")
                echo "        <tr><td>$name</td><td class=\"warning\">SKIPPED</td></tr>" >> reports/test_report.html
                ;;
        esac
    done

    cat >> reports/test_report.html << EOF
    </table>
</body>
</html>
EOF

    print_status "SUCCESS" "HTML report generated: reports/test_report.html"
fi

echo ""
echo -e "${BLUE}Test suite completed at $(date)${NC}"
echo -e "${BLUE}Check the reports/ directory for detailed results${NC}"

exit $exit_code
