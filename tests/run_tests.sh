#!/bin/bash
# Brain Researcher Test Runner
# Run different categories of tests based on arguments

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
NPM_BIN="${NPM_BIN:-npm}"
cd "$PROJECT_ROOT"

run_ci_pytest() {
    PYTHONDONTWRITEBYTECODE=1 \
        PYTHONPATH="${PROJECT_ROOT}/src${PYTHONPATH:+:${PYTHONPATH}}" \
        "$PYTHON_BIN" -m pytest -q \
        --noconftest -p no:cacheprovider --tb=short "$@"
}

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
        run_ci_pytest \
            tests/unit/config/test_active_import_path_contract.py \
            tests/unit/config/test_active_runtime_surface_contract.py \
            tests/unit/config/test_source_layout_contract.py \
            tests/unit/core/test_grounding_references.py \
            tests/unit/core/test_analysis_bundle.py \
            tests/unit/agent/test_execution_runners.py
        ;;

    contracts)
        echo -e "${BLUE}Running offline repository contract shard...${NC}"
        run_ci_pytest \
            tests/unit/config/test_active_import_path_contract.py \
            tests/unit/config/test_active_runtime_surface_contract.py \
            tests/unit/config/test_agent_legacy_surface_contract.py \
            tests/unit/config/test_cli_dependency_constraints.py \
            tests/unit/config/test_ci_workflow_contract.py \
            tests/unit/config/test_docs_integrity.py \
            tests/unit/config/test_execution_pack_hygiene_contract.py \
            tests/unit/config/test_gateway_boundary_contract.py \
            tests/unit/config/test_internal_docs_boundary_contract.py \
            tests/unit/config/test_metadata_root_resolver.py \
            tests/unit/config/test_operations_cli_contract.py \
            tests/unit/config/test_orchestrator_agent_boundary_contract.py \
            tests/unit/config/test_package_root_contract.py \
            tests/unit/config/test_paths.py \
            tests/unit/config/test_planner_runtime_contract.py \
            tests/unit/config/test_python_lock_contract.py \
            tests/unit/config/test_python_package_contract.py \
            tests/unit/config/test_runtime_docs_contract.py \
            tests/unit/config/test_service_docs_path_contract.py \
            tests/unit/config/test_source_layout_contract.py \
            tests/unit/config/test_topology_move_contract.py \
            tests/unit/config/test_verify_environment.py
        ;;

    reproducibility)
        echo -e "${BLUE}Running offline reproducibility verifier shard...${NC}"
        run_ci_pytest \
            tests/unit/reproducibility/test_a1_source_closure.py \
            tests/unit/reproducibility/test_neurosynth_source_pipeline.py \
            tests/unit/reproducibility/test_reproducibility_packs.py \
            tests/unit/reproducibility/test_reviewer_archive_manifest.py \
            tests/unit/reproducibility/test_scientific_rerun_report.py
        ;;

    services)
        echo -e "${BLUE}Running focused service unit shard...${NC}"
        run_ci_pytest \
            tests/unit/config/test_downloader_governance_contract.py \
            tests/unit/services/test_api_fee_debit.py \
            tests/unit/services/test_cost_calculator.py \
            tests/unit/services/test_mcp_api_fee.py \
            tests/unit/services/test_mcp_runtime_bridge.py \
            tests/unit/services/test_usage_aggregator.py
        ;;

    web)
        echo -e "${BLUE}Running Web repository contracts...${NC}"
        run_ci_pytest \
            tests/unit/config/test_web_generated_artifacts_contract.py \
            tests/unit/config/test_web_toolchain_contract.py \
            tests/unit/config/test_wrapper_apps_legacy_contract.py
        echo -e "${BLUE}Running Web lint, unit tests, and production build...${NC}"
        "$NPM_BIN" --prefix apps/web-ui run lint:ci
        "$NPM_BIN" --prefix apps/web-ui test
        "$NPM_BIN" --prefix apps/web-ui run build
        ;;

    deployment-static)
        echo -e "${BLUE}Running static deployment/configuration contracts...${NC}"
        bash scripts/ci/validate_deployment_static.sh
        run_ci_pytest \
            tests/unit/config/test_helm_deployment_contract.py \
            tests/unit/config/test_machine_specific_path_contract.py \
            tests/unit/config/test_operator_docs_contract.py \
            tests/unit/config/test_public_configuration_contract.py \
            tests/unit/config/test_script_governance_contract.py
        ;;

    architecture)
        echo -e "${BLUE}Running architecture boundary tests...${NC}"
        PYTHONDONTWRITEBYTECODE=1 "$PYTHON_BIN" -m pytest -q tests/architecture/test_import_boundaries.py -p no:cacheprovider
        ;;

    fast)
        echo -e "${BLUE}Running fast tests (excluding slow, e2e, realdata, network, requires_api, requires_gpu)...${NC}"
        "$PYTHON_BIN" -m pytest \
            -m "not slow and not e2e and not realdata and not network and not requires_api and not requires_gpu" \
            -v --tb=short
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
        echo "  contracts          - Run offline repository/config/document contracts"
        echo "  reproducibility    - Run offline pack, manifest, and verifier contracts"
        echo "  services           - Run service/downloader contracts (ci-services profile)"
        echo "  web                - Run Web contracts, lint, unit tests, and build"
        echo "  deployment-static  - Run static config/deployment contracts"
        echo "  architecture       - Run architecture boundary tests"
        echo "  fast               - Exclude slow/e2e/realdata/network/API/GPU tests"
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
        echo "  tests/run_tests.sh contracts"
        echo "  tests/run_tests.sh reproducibility"
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
