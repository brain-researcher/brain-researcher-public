#!/bin/bash
#
# Comprehensive Kubernetes Test Runner for Brain Researcher Platform
#
# This script runs all Kubernetes deployment tests including validation,
# smoke tests, rollback scenarios, scaling tests, and monitoring validation.
#

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
NAMESPACE="${K8S_NAMESPACE:-brain-researcher-core}"
CONTEXT="${K8S_CONTEXT:-}"
TEST_RESULTS_DIR="${SCRIPT_DIR}/results"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Usage information
usage() {
    cat << EOF
Usage: $0 [OPTIONS] [TEST_TYPE]

Run Kubernetes tests for Brain Researcher platform.

Options:
    -h, --help              Show this help message
    -n, --namespace NAME    Kubernetes namespace (default: brain-researcher-core)
    -c, --context CONTEXT   Kubernetes context to use
    -s, --skip-destructive  Skip destructive tests
    -w, --wait-for-ready    Wait for services to be ready before testing
    -v, --verbose           Verbose output
    -o, --output DIR        Output directory for test results
    --dry-run              Show what would be tested without running

Test Types:
    all                     Run all test suites (default)
    validation              Run deployment validation tests
    smoke                   Run smoke tests only
    rollback                Run rollback scenario tests
    scaling                 Run scaling validation tests
    monitoring              Run monitoring validation tests

Examples:
    $0                                  # Run all tests
    $0 smoke                           # Run smoke tests only
    $0 -n test-namespace validation    # Run validation in specific namespace
    $0 --skip-destructive scaling      # Run scaling tests without destructive operations

EOF
}

# Parse command line arguments
SKIP_DESTRUCTIVE=false
WAIT_FOR_READY=false
VERBOSE=false
DRY_RUN=false
TEST_TYPE="all"
OUTPUT_DIR=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            usage
            exit 0
            ;;
        -n|--namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        -c|--context)
            CONTEXT="$2"
            shift 2
            ;;
        -s|--skip-destructive)
            SKIP_DESTRUCTIVE=true
            shift
            ;;
        -w|--wait-for-ready)
            WAIT_FOR_READY=true
            shift
            ;;
        -v|--verbose)
            VERBOSE=true
            shift
            ;;
        -o|--output)
            OUTPUT_DIR="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        validation|smoke|rollback|scaling|monitoring|all)
            TEST_TYPE="$1"
            shift
            ;;
        *)
            log_error "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

# Set output directory
if [[ -z "$OUTPUT_DIR" ]]; then
    OUTPUT_DIR="$TEST_RESULTS_DIR/$(date +%Y%m%d_%H%M%S)"
fi

# Create results directory
mkdir -p "$OUTPUT_DIR"

log_info "Starting Kubernetes tests for Brain Researcher platform"
log_info "Namespace: $NAMESPACE"
log_info "Test Type: $TEST_TYPE"
log_info "Output Directory: $OUTPUT_DIR"

if [[ -n "$CONTEXT" ]]; then
    log_info "Kubernetes Context: $CONTEXT"
fi

# Check prerequisites
check_prerequisites() {
    log_info "Checking prerequisites..."

    # Check kubectl
    if ! command -v kubectl &> /dev/null; then
        log_error "kubectl is required but not installed"
        exit 1
    fi

    # Check Python and pytest
    if ! command -v python3 &> /dev/null; then
        log_error "python3 is required but not installed"
        exit 1
    fi

    if ! command -v pytest &> /dev/null; then
        log_error "pytest is required but not installed"
        exit 1
    fi

    # Check cluster access
    log_info "Checking cluster access..."
    if [[ -n "$CONTEXT" ]]; then
        kubectl --context="$CONTEXT" cluster-info > /dev/null 2>&1 || {
            log_error "Cannot access Kubernetes cluster with context: $CONTEXT"
            exit 1
        }
    else
        kubectl cluster-info > /dev/null 2>&1 || {
            log_error "Cannot access Kubernetes cluster"
            exit 1
        }
    fi

    log_success "Prerequisites check passed"
}

# Build pytest command
build_pytest_cmd() {
    local test_path="$1"
    local output_file="$2"

    cmd=(
        "pytest"
        "$test_path"
        "--tb=short"
        "--junit-xml=$output_file"
        "--k8s-namespace=$NAMESPACE"
    )

    if [[ -n "$CONTEXT" ]]; then
        cmd+=("--k8s-context=$CONTEXT")
    fi

    if [[ "$SKIP_DESTRUCTIVE" == "true" ]]; then
        cmd+=("--skip-destructive")
    fi

    if [[ "$WAIT_FOR_READY" == "true" ]]; then
        cmd+=("--wait-for-ready")
    fi

    if [[ "$VERBOSE" == "true" ]]; then
        cmd+=("-v" "-s")
    else
        cmd+=("-q")
    fi

    echo "${cmd[@]}"
}

# Run specific test suite
run_test_suite() {
    local suite_name="$1"
    local test_path="$2"
    local description="$3"

    log_info "Running $suite_name tests: $description"

    if [[ "$DRY_RUN" == "true" ]]; then
        log_info "DRY RUN: Would run tests in $test_path"
        return 0
    fi

    local output_file="$OUTPUT_DIR/${suite_name}_results.xml"
    local log_file="$OUTPUT_DIR/${suite_name}_output.log"

    local pytest_cmd
    pytest_cmd=$(build_pytest_cmd "$test_path" "$output_file")

    log_info "Command: $pytest_cmd"

    # Run the tests
    if eval "$pytest_cmd" > "$log_file" 2>&1; then
        log_success "$suite_name tests passed"
        return 0
    else
        local exit_code=$?
        log_error "$suite_name tests failed (exit code: $exit_code)"

        # Show last few lines of output for debugging
        if [[ "$VERBOSE" == "true" && -f "$log_file" ]]; then
            echo "Last 10 lines of output:"
            tail -n 10 "$log_file"
        fi

        return $exit_code
    fi
}

# Run validation tests
run_validation_tests() {
    run_test_suite "validation" \
        "$SCRIPT_DIR/test_deployment_validation.py" \
        "Deployment validation, service connectivity, resource limits"
}

# Run smoke tests
run_smoke_tests() {
    run_test_suite "smoke" \
        "$SCRIPT_DIR/smoke/test_smoke_tests.py" \
        "Service health, database connectivity, ingress routing"
}

# Run rollback tests
run_rollback_tests() {
    if [[ "$SKIP_DESTRUCTIVE" == "true" ]]; then
        log_warning "Skipping rollback tests (destructive operations disabled)"
        return 0
    fi

    run_test_suite "rollback" \
        "$SCRIPT_DIR/rollback/test_rollback_scenarios.py" \
        "Deployment rollbacks, data persistence, service availability"
}

# Run scaling tests
run_scaling_tests() {
    if [[ "$SKIP_DESTRUCTIVE" == "true" ]]; then
        log_warning "Skipping scaling tests (destructive operations disabled)"
        return 0
    fi

    run_test_suite "scaling" \
        "$SCRIPT_DIR/scaling/test_scaling_validation.py" \
        "HPA validation, load distribution, session affinity"
}

# Run monitoring tests
run_monitoring_tests() {
    run_test_suite "monitoring" \
        "$SCRIPT_DIR/monitoring/test_monitoring_validation.py" \
        "Prometheus metrics, alert rules, log aggregation"
}

# Main test execution
main() {
    # Check prerequisites
    check_prerequisites

    local overall_success=true
    local test_results=()

    # Change to script directory for relative imports
    cd "$SCRIPT_DIR"

    case "$TEST_TYPE" in
        "validation")
            run_validation_tests || overall_success=false
            test_results+=("validation")
            ;;
        "smoke")
            run_smoke_tests || overall_success=false
            test_results+=("smoke")
            ;;
        "rollback")
            run_rollback_tests || overall_success=false
            test_results+=("rollback")
            ;;
        "scaling")
            run_scaling_tests || overall_success=false
            test_results+=("scaling")
            ;;
        "monitoring")
            run_monitoring_tests || overall_success=false
            test_results+=("monitoring")
            ;;
        "all")
            log_info "Running all test suites..."

            run_validation_tests || overall_success=false
            test_results+=("validation")

            run_smoke_tests || overall_success=false
            test_results+=("smoke")

            run_rollback_tests || overall_success=false
            test_results+=("rollback")

            run_scaling_tests || overall_success=false
            test_results+=("scaling")

            run_monitoring_tests || overall_success=false
            test_results+=("monitoring")
            ;;
        *)
            log_error "Unknown test type: $TEST_TYPE"
            exit 1
            ;;
    esac

    # Generate summary report
    generate_summary_report "$OUTPUT_DIR" "${test_results[@]}"

    # Final status
    if [[ "$overall_success" == "true" ]]; then
        log_success "All Kubernetes tests completed successfully"
        log_info "Results available in: $OUTPUT_DIR"
        exit 0
    else
        log_error "Some Kubernetes tests failed"
        log_info "Check detailed results in: $OUTPUT_DIR"
        exit 1
    fi
}

# Generate summary report
generate_summary_report() {
    local output_dir="$1"
    shift
    local test_suites=("$@")

    local summary_file="$output_dir/test_summary.md"

    cat > "$summary_file" << EOF
# Kubernetes Test Summary Report

**Test Run Date:** $(date)
**Namespace:** $NAMESPACE
**Context:** ${CONTEXT:-default}
**Test Type:** $TEST_TYPE

## Test Results

EOF

    for suite in "${test_suites[@]}"; do
        local xml_file="$output_dir/${suite}_results.xml"
        local log_file="$output_dir/${suite}_output.log"

        echo "### $suite Tests" >> "$summary_file"

        if [[ -f "$xml_file" ]]; then
            # Parse XML results (basic parsing)
            local test_count
            test_count=$(grep -o 'tests="[0-9]*"' "$xml_file" | grep -o '[0-9]*' || echo "0")
            local failure_count
            failure_count=$(grep -o 'failures="[0-9]*"' "$xml_file" | grep -o '[0-9]*' || echo "0")
            local error_count
            error_count=$(grep -o 'errors="[0-9]*"' "$xml_file" | grep -o '[0-9]*' || echo "0")

            local status="✅ PASSED"
            if [[ "$failure_count" -gt 0 || "$error_count" -gt 0 ]]; then
                status="❌ FAILED"
            fi

            cat >> "$summary_file" << EOF
- **Status:** $status
- **Tests:** $test_count
- **Failures:** $failure_count
- **Errors:** $error_count
- **Log:** [${suite}_output.log](${suite}_output.log)
- **Results:** [${suite}_results.xml](${suite}_results.xml)

EOF
        else
            cat >> "$summary_file" << EOF
- **Status:** ❓ NO RESULTS
- **Log:** [${suite}_output.log](${suite}_output.log)

EOF
        fi
    done

    cat >> "$summary_file" << EOF

## Configuration

- **Skip Destructive:** $SKIP_DESTRUCTIVE
- **Wait for Ready:** $WAIT_FOR_READY
- **Verbose:** $VERBOSE

## Files Generated

$(ls -la "$output_dir")

EOF

    log_info "Summary report generated: $summary_file"
}

# Set up signal handlers for cleanup
cleanup() {
    log_info "Cleaning up..."
    # Add any cleanup logic here
    exit 130
}

trap cleanup INT TERM

# Run main function
main "$@"