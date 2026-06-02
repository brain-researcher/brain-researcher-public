#!/bin/bash

# Brain Researcher Performance Test Suite Setup Validator
# Validates that all components are properly configured and ready for testing

set -e

echo "🧠 Brain Researcher Performance Test Suite - Setup Validation"
echo "============================================================="
echo ""

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Validation results
VALIDATION_ERRORS=0
VALIDATION_WARNINGS=0

validate_requirement() {
    local requirement=$1
    local command_check=$2
    local description=$3
    local required=${4:-true}

    echo -n "Checking $requirement... "

    if eval "$command_check" >/dev/null 2>&1; then
        echo -e "${GREEN}✅ OK${NC}"
        if [ -n "$description" ]; then
            echo "   $description"
        fi
        return 0
    else
        if [ "$required" = "true" ]; then
            echo -e "${RED}❌ MISSING (Required)${NC}"
            ((VALIDATION_ERRORS++))
        else
            echo -e "${YELLOW}⚠️  MISSING (Optional)${NC}"
            ((VALIDATION_WARNINGS++))
        fi

        if [ -n "$description" ]; then
            echo "   $description"
        fi
        return 1
    fi
}

echo "🔧 Checking Prerequisites"
echo "========================="

validate_requirement "K6 Installation" \
    "command -v k6" \
    "K6 load testing tool - install from https://k6.io/docs/get-started/installation/"

validate_requirement "curl" \
    "command -v curl" \
    "HTTP client for service health checks"

validate_requirement "jq (JSON processor)" \
    "command -v jq" \
    "JSON parsing tool for report analysis - install with: apt install jq / brew install jq" \
    false

validate_requirement "bc (calculator)" \
    "command -v bc" \
    "Basic calculator for numerical comparisons in shell scripts" \
    false

echo ""
echo "📁 Checking File Structure"
echo "=========================="

validate_requirement "Configuration Files" \
    "[ -f config/k6.config.js ]" \
    "K6 configuration and test parameters"

validate_requirement "Utility Scripts" \
    "[ -f scripts/utils.js ]" \
    "Common functions for HTTP requests and data generation"

validate_requirement "Test Scenarios Directory" \
    "[ -d scenarios ]" \
    "Individual test scenario files"

validate_requirement "Reports Directory" \
    "mkdir -p reports && [ -d reports ]" \
    "Output directory for test results and reports"

validate_requirement "Shell Scripts Directory" \
    "[ -d scripts ]" \
    "Executable test runner scripts"

echo ""
echo "🧪 Checking Test Scenarios"
echo "=========================="

validate_requirement "Load Test Scenario" \
    "[ -f scenarios/load-test.js ]" \
    "Normal production load simulation"

validate_requirement "Stress Test Scenario" \
    "[ -f scenarios/stress-test.js ]" \
    "Beyond-capacity load testing"

validate_requirement "Spike Test Scenario" \
    "[ -f scenarios/spike-test.js ]" \
    "Sudden traffic spike simulation"

validate_requirement "Soak Test Scenario" \
    "[ -f scenarios/soak-test.js ]" \
    "Extended duration stability testing"

validate_requirement "WebSocket Test Scenario" \
    "[ -f scenarios/websocket-test.js ]" \
    "Real-time communication testing"

echo ""
echo "🚀 Checking Test Runners"
echo "========================"

validate_requirement "Master Test Runner" \
    "[ -f run-performance-tests.js ]" \
    "Main test orchestration script"

validate_requirement "Smoke Test Runner" \
    "[ -x scripts/run-smoke-test.sh ]" \
    "Quick validation test script"

validate_requirement "Load Test Runner" \
    "[ -x scripts/run-load-test.sh ]" \
    "Production load test script"

validate_requirement "Complete Suite Runner" \
    "[ -x scripts/run-all-tests.sh ]" \
    "Full test suite orchestration"

echo ""
echo "📝 Checking Documentation"
echo "========================="

validate_requirement "README Documentation" \
    "[ -f README.md ]" \
    "Complete usage and setup documentation"

validate_requirement "Package Configuration" \
    "[ -f package.json ]" \
    "NPM scripts and project metadata"

echo ""
echo "🔌 Checking Service Availability"
echo "================================"

# Service URLs
ORCHESTRATOR_URL=${ORCHESTRATOR_URL:-"http://localhost:3001"}
BR_KG_URL=${BR_KG_URL:-"http://localhost:5000"}
AGENT_URL=${AGENT_URL:-"http://localhost:8000"}

echo "Service endpoints:"
echo "  Orchestrator: $ORCHESTRATOR_URL"
echo "  BR-KG:      $BR_KG_URL"
echo "  Agent:        $AGENT_URL"
echo ""

validate_requirement "Orchestrator Service" \
    "curl -f -s --max-time 5 '$ORCHESTRATOR_URL/health'" \
    "Job orchestration and analysis API service" \
    false

validate_requirement "BR-KG Service" \
    "curl -f -s --max-time 5 '$BR_KG_URL/health'" \
    "Knowledge graph and data API service" \
    false

validate_requirement "Agent Service" \
    "curl -f -s --max-time 5 '$AGENT_URL/health'" \
    "LLM-powered analysis agent service" \
    false

echo ""
echo "🧾 Validation Summary"
echo "===================="

if [ $VALIDATION_ERRORS -eq 0 ] && [ $VALIDATION_WARNINGS -eq 0 ]; then
    echo -e "${GREEN}🎉 Perfect! All validations passed.${NC}"
    echo ""
    echo "✅ Your performance testing environment is fully configured and ready."
    echo ""
    echo "🚀 Quick Start Commands:"
    echo "   ./scripts/run-smoke-test.sh      # Quick validation (30s)"
    echo "   ./scripts/run-load-test.sh       # Production load test (9m)"
    echo "   ./scripts/run-all-tests.sh       # Complete test suite (15m)"
    echo ""
    OVERALL_STATUS="READY"
elif [ $VALIDATION_ERRORS -eq 0 ]; then
    echo -e "${YELLOW}⚠️  Setup is functional with warnings.${NC}"
    echo "   Errors: $VALIDATION_ERRORS"
    echo "   Warnings: $VALIDATION_WARNINGS"
    echo ""
    echo "✅ Core testing functionality is available."
    echo "⚠️  Some optional features may not work optimally."
    echo ""
    OVERALL_STATUS="FUNCTIONAL_WITH_WARNINGS"
else
    echo -e "${RED}❌ Setup validation failed.${NC}"
    echo "   Errors: $VALIDATION_ERRORS (must be fixed)"
    echo "   Warnings: $VALIDATION_WARNINGS (recommended to fix)"
    echo ""
    echo "🔧 Please address the missing requirements before running tests."
    echo ""
    OVERALL_STATUS="FAILED"
fi

# Service-specific guidance
services_available=0
if curl -f -s --max-time 5 "$ORCHESTRATOR_URL/health" >/dev/null 2>&1; then ((services_available++)); fi
if curl -f -s --max-time 5 "$BR_KG_URL/health" >/dev/null 2>&1; then ((services_available++)); fi
if curl -f -s --max-time 5 "$AGENT_URL/health" >/dev/null 2>&1; then ((services_available++)); fi

if [ $services_available -eq 0 ]; then
    echo ""
    echo -e "${RED}🚨 No services are currently running!${NC}"
    echo ""
    echo "To start Brain Researcher services:"
    echo "   br serve orchestrator  # Terminal 1 - Port 3001"
    echo "   br serve kg           # Terminal 2 - Port 5000"
    echo "   br serve agent        # Terminal 3 - Port 8000"
    echo ""
    echo "Or using Docker:"
    echo "   docker-compose up -d"
elif [ $services_available -lt 3 ]; then
    echo ""
    echo -e "${YELLOW}⚠️  Only $services_available/3 services are running.${NC}"
    echo "Performance tests will work but may not be comprehensive."
    echo ""
    echo "For complete testing, start all services:"
    echo "   br serve orchestrator  # Port 3001"
    echo "   br serve kg           # Port 5000"
    echo "   br serve agent        # Port 8000"
else
    echo ""
    echo -e "${GREEN}✅ All 3 services are running and healthy!${NC}"
    echo "Your system is ready for comprehensive performance testing."
fi

echo ""
echo "📚 Additional Resources:"
echo "   Documentation: README.md"
echo "   Test Scenarios: scenarios/"
echo "   Example Reports: Run any test to generate sample reports"
echo ""

# Generate validation report
cat > validation-report.txt << EOF
Brain Researcher Performance Test Suite - Validation Report
Generated: $(date)

Overall Status: $OVERALL_STATUS
Validation Errors: $VALIDATION_ERRORS
Validation Warnings: $VALIDATION_WARNINGS
Services Available: $services_available/3

Service Endpoints:
- Orchestrator: $ORCHESTRATOR_URL
- BR-KG: $BR_KG_URL
- Agent: $AGENT_URL

Setup Status: $(if [ $VALIDATION_ERRORS -eq 0 ]; then echo "READY"; else echo "NEEDS_ATTENTION"; fi)
EOF

echo "📄 Validation report saved to: validation-report.txt"
echo ""

# Exit with appropriate code
if [ $VALIDATION_ERRORS -eq 0 ]; then
    exit 0
else
    exit 1
fi
