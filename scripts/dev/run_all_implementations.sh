#!/bin/bash
# Comprehensive test script for all implemented features

echo "=========================================="
echo "Testing All Brain Researcher Implementations"
echo "=========================================="
echo ""

# Colors for output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test counter
PASSED=0
FAILED=0

# Function to run a test
run_test() {
    local test_name="$1"
    local command="$2"

    echo -n "Testing $test_name... "

    if eval "$command" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ PASSED${NC}"
        ((PASSED++))
    else
        echo -e "${RED}✗ FAILED${NC}"
        echo "  Command: $command"
        ((FAILED++))
    fi
}

# Function to check file exists
check_file() {
    local file_name="$1"
    local file_path="$2"

    echo -n "Checking $file_name... "

    if [ -f "$file_path" ]; then
        echo -e "${GREEN}✓ EXISTS${NC}"
        ((PASSED++))
    else
        echo -e "${RED}✗ MISSING${NC}"
        ((FAILED++))
    fi
}

echo "1. Testing Project Structure"
echo "----------------------------"
check_file ".gitignore" ".gitignore"
check_file "pyproject.toml" "pyproject.toml"
check_file "README.md" "README.md"
check_file ".gitattributes" ".gitattributes"
check_file ".pre-commit-config.yaml" ".pre-commit-config.yaml"
echo ""

echo "2. Testing CLI Installation"
echo "----------------------------"
run_test "br command exists" "which br"
run_test "brain-researcher command exists" "which brain-researcher"
run_test "CLI version" "br version"
run_test "CLI help" "br --help"
echo ""

echo "3. Testing CLI Commands"
echo "-----------------------"
run_test "db status" "br db status"
run_test "db help" "br db --help"
run_test "data list-sources" "br data list-sources"
run_test "data help" "br data --help"
run_test "query stats" "br query stats"
run_test "query help" "br query --help"
run_test "analyze help" "br analyze --help"
run_test "ingest help" "br ingest --help"
echo ""

echo "4. Testing Data Management"
echo "--------------------------"
check_file "data README" "data/README.md"
run_test "data download script" "python scripts/data/download_data.py --help"
run_test "data check" "python scripts/data/download_data.py check"
check_file "Git LFS config" ".gitattributes"
echo ""

echo "5. Testing Pre-commit Setup"
echo "---------------------------"
run_test "pre-commit installed" "which pre-commit"
run_test "pre-commit config valid" "pre-commit validate-config"
check_file "setup script" "scripts/dev/setup_precommit.sh"
echo ""

echo "6. Testing Documentation"
echo "------------------------"
check_file "docs README" "docs/README.md"
check_file "CLI migration guide" "docs/guides/cli_migration_guide.md"
check_file "data management guide" "docs/guides/data_management_guide.md"
echo ""

echo "7. Testing Python Package"
echo "-------------------------"
run_test "import brain_researcher" "python -c 'import brain_researcher'"
run_test "package version" "python -c 'import brain_researcher; print(brain_researcher.__version__)'"
echo ""

echo "8. Testing Database"
echo "-------------------"
run_test "Neo4j credentials set" "[[ -n \"\$NEO4J_URI\" && -n \"\$NEO4J_PASSWORD\" ]]"
check_file "GLM database" "data/br-kg/db/br-kg_glmfitlins.db"
echo ""

echo "9. Testing Scripts"
echo "------------------"
check_file "download data script" "scripts/data/download_data.py"
check_file "pre-commit setup" "scripts/dev/setup_precommit.sh"
run_test "scripts executable" "test -x scripts/dev/setup_precommit.sh"
echo ""

echo "10. Testing Search Functionality"
echo "--------------------------------"
run_test "search motor cortex" "br query search 'motor cortex' --limit 1"
echo ""

echo "=========================================="
echo "Test Summary"
echo "=========================================="
echo -e "Passed: ${GREEN}$PASSED${NC}"
echo -e "Failed: ${RED}$FAILED${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
    exit 0
else
    echo -e "${RED}Some tests failed. Please check the output above.${NC}"
    exit 1
fi
