#!/bin/bash
# Brain Researcher Test Runner
# Run different categories of tests based on arguments

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
cd "$PROJECT_ROOT"

# Colors for output
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║  Brain Researcher Test Suite          ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"

# Parse command line arguments
case "${1:-help}" in
    unit)
        echo -e "${BLUE}Running default unit shard...${NC}"
        "$PYTHON_BIN" -m pytest tests/unit/ -v --tb=short
        ;;

    unit-br-kg|br-kg)
        echo -e "${BLUE}Running BR-KG unit shard...${NC}"
        "$PYTHON_BIN" -m pytest tests/unit/br_kg/ -v --tb=short
        ;;

    unit-all-shards)
        echo -e "${BLUE}Running default unit shard...${NC}"
        "$PYTHON_BIN" -m pytest tests/unit/ -v --tb=short
        echo -e "${BLUE}Running BR-KG unit shard...${NC}"
        "$PYTHON_BIN" -m pytest tests/unit/br_kg/ -v --tb=short
        ;;

    unit-pr-smoke)
        echo -e "${BLUE}Running PR unit smoke shard...${NC}"
        "$PYTHON_BIN" -m pytest -q \
            tests/unit/config/test_active_import_path_contract.py \
            tests/unit/config/test_active_runtime_surface_contract.py \
            tests/unit/config/test_source_layout_contract.py \
            tests/unit/core/test_grounding_references.py \
            tests/unit/core/test_analysis_bundle.py \
            tests/unit/agent/test_execution_runners.py \
            --tb=short
        ;;

    architecture)
        echo -e "${BLUE}Running architecture boundary tests...${NC}"
        PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" -m pytest -q tests/architecture/test_import_boundaries.py -p no:cacheprovider
        ;;

    fast)
        echo -e "${BLUE}Running fast tests (excluding slow, e2e, realdata)...${NC}"
        "$PYTHON_BIN" -m pytest -m "not slow and not e2e and not realdata" -v --tb=short
        ;;

    coverage)
        echo -e "${BLUE}Running tests with coverage report...${NC}"
        "$PYTHON_BIN" -m pytest --cov=brain_researcher --cov-report=html:htmlcov --cov-report=term-missing -v
        echo -e "${GREEN}Coverage report saved to: htmlcov/index.html${NC}"
        ;;

    specific)
        if [ -z "$2" ]; then
            echo -e "${RED}Error: Please provide a test file or pattern${NC}"
            echo "Usage: $0 specific <test_file_or_pattern>"
            exit 1
        fi
        echo -e "${BLUE}Running specific test: $2${NC}"
        "$PYTHON_BIN" -m pytest "$2" -v --tb=short
        ;;

    markers)
        echo -e "${BLUE}Available test markers:${NC}"
        awk '
            /^markers =/ { in_markers = 1; next }
            in_markers && /^[^[:space:]]/ { exit }
            in_markers { sub(/^[[:space:]]+/, "  "); print }
        ' pytest.ini
        ;;

    collect)
        echo -e "${BLUE}Collecting default pytest selection (dry run)...${NC}"
        "$PYTHON_BIN" -m pytest --collect-only -q
        ;;

    collect-unit)
        echo -e "${BLUE}Collecting default unit shard (dry run)...${NC}"
        "$PYTHON_BIN" -m pytest --collect-only -q tests/unit/
        ;;

    collect-br-kg)
        echo -e "${BLUE}Collecting BR-KG unit shard (dry run)...${NC}"
        "$PYTHON_BIN" -m pytest --collect-only -q tests/unit/br_kg/
        ;;

    collect-all-shards)
        echo -e "${BLUE}Collecting default unit shard (dry run)...${NC}"
        "$PYTHON_BIN" -m pytest --collect-only -q tests/unit/
        echo -e "${BLUE}Collecting BR-KG unit shard (dry run)...${NC}"
        "$PYTHON_BIN" -m pytest --collect-only -q tests/unit/br_kg/
        ;;

    collect-architecture)
        echo -e "${BLUE}Collecting architecture tests (dry run)...${NC}"
        PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" -m pytest --collect-only -q tests/architecture/ -p no:cacheprovider
        ;;

    all)
        echo -e "${BLUE}Running default-discovered tests (honors pytest.ini addopts)...${NC}"
        "$PYTHON_BIN" -m pytest -v --tb=short
        ;;

    help)
        echo -e "${YELLOW}Usage: $0 [command]${NC}"
        echo ""
        echo "Commands:"
        echo "  unit               - Run default unit shard (excludes BR-KG via pytest.ini)"
        echo "  unit-br-kg         - Run BR-KG unit shard"
        echo "  br-kg              - Alias for unit-br-kg"
        echo "  unit-all-shards    - Run default unit shard, then BR-KG unit shard"
        echo "  unit-pr-smoke      - Run fast PR smoke tests for active contracts"
        echo "  architecture       - Run architecture boundary tests"
        echo "  fast               - Run fast tests (default, excludes slow/e2e/realdata)"
        echo "  coverage           - Run default pytest selection with coverage report"
        echo "  specific           - Run specific test file (requires path as 2nd arg)"
        echo "  markers            - Show available test markers"
        echo "  collect            - List default pytest selection without running"
        echo "  collect-unit       - Collect default unit shard without running"
        echo "  collect-br-kg      - Collect BR-KG unit shard without running"
        echo "  collect-all-shards - Collect default unit shard, then BR-KG unit shard"
        echo "  collect-architecture - Collect architecture tests without running"
        echo "  all                - Run default-discovered tests honored by pytest.ini"
        echo "  help               - Show this help message"
        echo ""
        echo "Examples:"
        echo "  tests/run_tests.sh unit-all-shards"
        echo "  tests/run_tests.sh architecture"
        echo "  tests/run_tests.sh collect-all-shards"
        echo "  tests/run_tests.sh specific tests/unit/br_kg/test_node_matcher.py"
        exit 0
        ;;

    *)
        echo -e "${RED}Unknown command: $1${NC}" >&2
        echo "Run '$0 help' to list supported commands." >&2
        exit 2
        ;;
esac

echo -e "\n${GREEN}✓ Test run complete!${NC}"
