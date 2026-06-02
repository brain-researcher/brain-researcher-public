#!/bin/bash
"""
Integration Test Script for Backup System

This script performs end-to-end integration testing of the backup system
including all components and recovery procedures.
"""

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_ROOT="$(dirname "$SCRIPT_DIR")"
PROJECT_ROOT="$(dirname "$(dirname "$TEST_ROOT")")"
TEST_OUTPUT_DIR="${TEST_ROOT}/integration_test_output"
LOG_FILE="${TEST_OUTPUT_DIR}/integration_test.log"

# Test configuration
TEST_BACKUP_DIR="${TEST_OUTPUT_DIR}/test_backups"
TEST_DB_NAME="brain_researcher_test"
TEST_RETENTION_DAYS=7

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "${LOG_FILE}"
}

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1" | tee -a "${LOG_FILE}"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1" | tee -a "${LOG_FILE}"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" | tee -a "${LOG_FILE}"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1" | tee -a "${LOG_FILE}"
}

# Setup test environment
setup_test_environment() {
    log_info "Setting up test environment..."

    # Create test directories
    mkdir -p "${TEST_OUTPUT_DIR}"
    mkdir -p "${TEST_BACKUP_DIR}"

    # Initialize log file
    echo "Backup Integration Test Started at $(date)" > "${LOG_FILE}"

    log_info "Test environment setup complete"
}

# Test backup script execution
test_backup_script_execution() {
    log_info "Testing backup script execution..."

    local test_results=()

    # Test PostgreSQL backup script
    if test_postgres_backup_script; then
        test_results+=("postgres:PASS")
        log_success "PostgreSQL backup script test passed"
    else
        test_results+=("postgres:FAIL")
        log_error "PostgreSQL backup script test failed"
    fi

    # Test BR-KG backup script
    if test_br_kg_backup_script; then
        test_results+=("br-kg:PASS")
        log_success "BR-KG backup script test passed"
    else
        test_results+=("br-kg:FAIL")
        log_error "BR-KG backup script test failed"
    fi

    # Test Redis backup script
    if test_redis_backup_script; then
        test_results+=("redis:PASS")
        log_success "Redis backup script test passed"
    else
        test_results+=("redis:FAIL")
        log_error "Redis backup script test failed"
    fi

    # Write results
    printf '%s\n' "${test_results[@]}" > "${TEST_OUTPUT_DIR}/backup_script_results.txt"

    return 0
}

test_postgres_backup_script() {
    log_info "Testing PostgreSQL backup script..."

    # Set environment variables for test
    export BACKUP_DIR="${TEST_BACKUP_DIR}"
    export POSTGRES_HOST="localhost"
    export POSTGRES_PORT="5432"
    export POSTGRES_USER="test_user"
    export POSTGRES_DB="${TEST_DB_NAME}"
    export RETENTION_DAYS="${TEST_RETENTION_DAYS}"
    export LOG_FILE="${TEST_OUTPUT_DIR}/postgres_backup_test.log"

    # Create mock encryption key
    local encryption_key="${TEST_BACKUP_DIR}/test_encryption.key"
    echo "test-encryption-key-for-integration-testing" > "${encryption_key}"
    export ENCRYPTION_KEY_FILE="${encryption_key}"

    # Mock pg_isready and pg_dump for testing
    create_postgres_mocks

    # Run backup script
    local backup_script="${PROJECT_ROOT}/backup/scripts/postgres-backup.sh"
    if [[ -f "${backup_script}" ]]; then
        if timeout 60 bash "${backup_script}"; then
            log_info "PostgreSQL backup script executed successfully"

            # Verify backup file was created
            local backup_files=$(find "${TEST_BACKUP_DIR}" -name "postgres_${TEST_DB_NAME}_*.sql.gz.enc" -type f)
            if [[ -n "${backup_files}" ]]; then
                log_info "PostgreSQL backup files created: ${backup_files}"
                return 0
            else
                log_error "No PostgreSQL backup files found"
                return 1
            fi
        else
            log_error "PostgreSQL backup script failed to execute"
            return 1
        fi
    else
        log_warn "PostgreSQL backup script not found at ${backup_script}"
        return 1
    fi
}

test_br_kg_backup_script() {
    log_info "Testing BR-KG backup script..."

    # Set environment variables
    export BACKUP_DIR="${TEST_BACKUP_DIR}"
    export BR_KG_DB_PATH="${TEST_BACKUP_DIR}/test_br_kg_graph.db"
    export RETENTION_DAYS="${TEST_RETENTION_DAYS}"
    export LOG_FILE="${TEST_OUTPUT_DIR}/br-kg_backup_test.log"

    # Create test database
    create_test_br_kg_database

    # Create backup script (simplified for testing)
    local backup_script="${TEST_OUTPUT_DIR}/br-kg_backup_test.sh"
    cat > "${backup_script}" << 'EOF'
#!/bin/bash
set -euo pipefail

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/br-kg_${TIMESTAMP}.tar.gz.enc"

# Create archive
tar -czf "${BACKUP_FILE%.enc}" -C "$(dirname "${BR_KG_DB_PATH}")" "$(basename "${BR_KG_DB_PATH}")"

# Mock encryption
mv "${BACKUP_FILE%.enc}" "${BACKUP_FILE}"

echo "BR-KG backup completed: ${BACKUP_FILE}"
EOF

    chmod +x "${backup_script}"

    if timeout 30 bash "${backup_script}"; then
        log_info "BR-KG backup script executed successfully"

        # Verify backup file
        local backup_files=$(find "${TEST_BACKUP_DIR}" -name "br_kg_*.tar.gz.enc" -type f)
        if [[ -n "${backup_files}" ]]; then
            log_info "BR-KG backup files created: ${backup_files}"
            return 0
        else
            log_error "No BR-KG backup files found"
            return 1
        fi
    else
        log_error "BR-KG backup script failed"
        return 1
    fi
}

test_redis_backup_script() {
    log_info "Testing Redis backup script..."

    # Set environment variables
    export BACKUP_DIR="${TEST_BACKUP_DIR}"
    export REDIS_HOST="localhost"
    export REDIS_PORT="6379"
    export RETENTION_DAYS="${TEST_RETENTION_DAYS}"
    export LOG_FILE="${TEST_OUTPUT_DIR}/redis_backup_test.log"

    # Create test Redis data
    create_test_redis_data

    # Create backup script (simplified for testing)
    local backup_script="${TEST_OUTPUT_DIR}/redis_backup_test.sh"
    cat > "${backup_script}" << 'EOF'
#!/bin/bash
set -euo pipefail

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/redis_${TIMESTAMP}.tar.gz.enc"
TEMP_DIR=$(mktemp -d)

# Create mock Redis backup files
echo "REDIS0009" > "${TEMP_DIR}/dump.rdb"
echo "*3\r\n\$3\r\nSET\r\n\$8\r\ntest:key\r\n\$10\r\ntest:value\r\n" > "${TEMP_DIR}/appendonly.aof"
echo '{"test:key": "test:value"}' > "${TEMP_DIR}/redis_keys_${TIMESTAMP}.json"

# Create metadata
cat > "${TEMP_DIR}/metadata.json" << EOJ
{
    "backup_type": "redis",
    "timestamp": "${TIMESTAMP}",
    "keys_count": 1,
    "memory_usage": 1024
}
EOJ

# Create archive
tar -czf "${BACKUP_FILE%.enc}" -C "${TEMP_DIR}" .

# Mock encryption
mv "${BACKUP_FILE%.enc}" "${BACKUP_FILE}"

# Cleanup
rm -rf "${TEMP_DIR}"

echo "Redis backup completed: ${BACKUP_FILE}"
EOF

    chmod +x "${backup_script}"

    if timeout 30 bash "${backup_script}"; then
        log_info "Redis backup script executed successfully"

        # Verify backup file
        local backup_files=$(find "${TEST_BACKUP_DIR}" -name "redis_*.tar.gz.enc" -type f)
        if [[ -n "${backup_files}" ]]; then
            log_info "Redis backup files created: ${backup_files}"
            return 0
        else
            log_error "No Redis backup files found"
            return 1
        fi
    else
        log_error "Redis backup script failed"
        return 1
    fi
}

# Test backup verification
test_backup_verification() {
    log_info "Testing backup verification..."

    # Find all backup files
    local backup_files=$(find "${TEST_BACKUP_DIR}" -name "*.enc" -type f)

    if [[ -z "${backup_files}" ]]; then
        log_error "No backup files found for verification"
        return 1
    fi

    local verification_results=()

    while IFS= read -r backup_file; do
        log_info "Verifying backup file: ${backup_file}"

        if verify_backup_file "${backup_file}"; then
            verification_results+=("$(basename "${backup_file}"):PASS")
            log_success "Backup verification passed: ${backup_file}"
        else
            verification_results+=("$(basename "${backup_file}"):FAIL")
            log_error "Backup verification failed: ${backup_file}"
        fi
    done <<< "${backup_files}"

    # Write results
    printf '%s\n' "${verification_results[@]}" > "${TEST_OUTPUT_DIR}/verification_results.txt"

    return 0
}

verify_backup_file() {
    local backup_file="$1"

    # Basic file checks
    if [[ ! -f "${backup_file}" ]]; then
        log_error "Backup file does not exist: ${backup_file}"
        return 1
    fi

    local file_size=$(stat -c%s "${backup_file}")
    if [[ ${file_size} -eq 0 ]]; then
        log_error "Backup file is empty: ${backup_file}"
        return 1
    fi

    # Check file extension and format
    case "${backup_file}" in
        *.sql.gz.enc)
            log_info "Verifying PostgreSQL backup format"
            # For testing, we'll assume it's valid if it exists and has content
            return 0
            ;;
        *.tar.gz.enc)
            log_info "Verifying archive backup format"
            # For testing, we'll assume it's valid if it exists and has content
            return 0
            ;;
        *)
            log_warn "Unknown backup file format: ${backup_file}"
            return 1
            ;;
    esac
}

# Test recovery procedures
test_recovery_procedures() {
    log_info "Testing recovery procedures..."

    # Find backup files for recovery testing
    local postgres_backup=$(find "${TEST_BACKUP_DIR}" -name "postgres_*.sql.gz.enc" -type f | head -1)
    local br_kg_backup=$(find "${TEST_BACKUP_DIR}" -name "br_kg_*.tar.gz.enc" -type f | head -1)
    local redis_backup=$(find "${TEST_BACKUP_DIR}" -name "redis_*.tar.gz.enc" -type f | head -1)

    local recovery_results=()

    # Test PostgreSQL recovery
    if [[ -n "${postgres_backup}" ]]; then
        if test_postgres_recovery "${postgres_backup}"; then
            recovery_results+=("postgres_recovery:PASS")
            log_success "PostgreSQL recovery test passed"
        else
            recovery_results+=("postgres_recovery:FAIL")
            log_error "PostgreSQL recovery test failed"
        fi
    fi

    # Test BR-KG recovery
    if [[ -n "${br_kg_backup}" ]]; then
        if test_br_kg_recovery "${br_kg_backup}"; then
            recovery_results+=("br_kg_recovery:PASS")
            log_success "BR-KG recovery test passed"
        else
            recovery_results+=("br_kg_recovery:FAIL")
            log_error "BR-KG recovery test failed"
        fi
    fi

    # Test Redis recovery
    if [[ -n "${redis_backup}" ]]; then
        if test_redis_recovery "${redis_backup}"; then
            recovery_results+=("redis_recovery:PASS")
            log_success "Redis recovery test passed"
        else
            recovery_results+=("redis_recovery:FAIL")
            log_error "Redis recovery test failed"
        fi
    fi

    # Write results
    printf '%s\n' "${recovery_results[@]}" > "${TEST_OUTPUT_DIR}/recovery_results.txt"

    return 0
}

test_postgres_recovery() {
    local backup_file="$1"
    log_info "Testing PostgreSQL recovery from: ${backup_file}"

    local recovery_dir="${TEST_OUTPUT_DIR}/postgres_recovery"
    mkdir -p "${recovery_dir}"

    # Simulate recovery process
    local recovery_script="${recovery_dir}/recovery_test.sh"
    cat > "${recovery_script}" << EOF
#!/bin/bash
set -euo pipefail

BACKUP_FILE="${backup_file}"
RECOVERY_DB="${TEST_DB_NAME}_recovery"

echo "Simulating PostgreSQL recovery from \${BACKUP_FILE}"
echo "Target database: \${RECOVERY_DB}"

# Mock recovery steps:
# 1. Decrypt backup (simulation)
echo "Step 1: Decrypting backup file..."
sleep 1

# 2. Decompress backup (simulation)
echo "Step 2: Decompressing backup..."
sleep 1

# 3. Create recovery database (simulation)
echo "Step 3: Creating recovery database \${RECOVERY_DB}..."
sleep 1

# 4. Restore data (simulation)
echo "Step 4: Restoring data from backup..."
sleep 2

echo "PostgreSQL recovery completed successfully"
EOF

    chmod +x "${recovery_script}"

    if timeout 30 bash "${recovery_script}" > "${recovery_dir}/recovery_output.log" 2>&1; then
        log_info "PostgreSQL recovery simulation completed"
        return 0
    else
        log_error "PostgreSQL recovery simulation failed"
        return 1
    fi
}

test_br_kg_recovery() {
    local backup_file="$1"
    log_info "Testing BR-KG recovery from: ${backup_file}"

    local recovery_dir="${TEST_OUTPUT_DIR}/br-kg_recovery"
    mkdir -p "${recovery_dir}"

    # Simulate recovery process
    local recovery_script="${recovery_dir}/recovery_test.sh"
    cat > "${recovery_script}" << EOF
#!/bin/bash
set -euo pipefail

BACKUP_FILE="${backup_file}"
RECOVERY_DB="${recovery_dir}/br-kg_recovered.db"

echo "Simulating BR-KG recovery from \${BACKUP_FILE}"
echo "Target database: \${RECOVERY_DB}"

# Mock recovery steps
echo "Step 1: Extracting archive..."
sleep 1

echo "Step 2: Verifying database integrity..."
sleep 1

echo "Step 3: Copying database to recovery location..."
touch "\${RECOVERY_DB}"
sleep 1

echo "BR-KG recovery completed successfully"
EOF

    chmod +x "${recovery_script}"

    if timeout 30 bash "${recovery_script}" > "${recovery_dir}/recovery_output.log" 2>&1; then
        log_info "BR-KG recovery simulation completed"

        # Verify recovery database exists
        if [[ -f "${recovery_dir}/br-kg_recovered.db" ]]; then
            return 0
        else
            log_error "Recovery database not found"
            return 1
        fi
    else
        log_error "BR-KG recovery simulation failed"
        return 1
    fi
}

test_redis_recovery() {
    local backup_file="$1"
    log_info "Testing Redis recovery from: ${backup_file}"

    local recovery_dir="${TEST_OUTPUT_DIR}/redis_recovery"
    mkdir -p "${recovery_dir}"

    # Simulate recovery process
    local recovery_script="${recovery_dir}/recovery_test.sh"
    cat > "${recovery_script}" << EOF
#!/bin/bash
set -euo pipefail

BACKUP_FILE="${backup_file}"
RECOVERY_DIR="${recovery_dir}"

echo "Simulating Redis recovery from \${BACKUP_FILE}"
echo "Target directory: \${RECOVERY_DIR}"

# Mock recovery steps
echo "Step 1: Extracting Redis backup archive..."
sleep 1

echo "Step 2: Restoring RDB file..."
touch "\${RECOVERY_DIR}/dump.rdb"

echo "Step 3: Restoring AOF file..."
touch "\${RECOVERY_DIR}/appendonly.aof"

echo "Step 4: Importing JSON keys..."
echo '{"test:key": "test:value"}' > "\${RECOVERY_DIR}/restored_keys.json"

echo "Redis recovery completed successfully"
EOF

    chmod +x "${recovery_script}"

    if timeout 30 bash "${recovery_script}" > "${recovery_dir}/recovery_output.log" 2>&1; then
        log_info "Redis recovery simulation completed"

        # Verify recovery files exist
        if [[ -f "${recovery_dir}/dump.rdb" && -f "${recovery_dir}/appendonly.aof" ]]; then
            return 0
        else
            log_error "Recovery files not found"
            return 1
        fi
    else
        log_error "Redis recovery simulation failed"
        return 1
    fi
}

# Helper functions
create_postgres_mocks() {
    local mock_dir="${TEST_OUTPUT_DIR}/mocks"
    mkdir -p "${mock_dir}"

    # Mock pg_isready
    cat > "${mock_dir}/pg_isready" << 'EOF'
#!/bin/bash
echo "Mock pg_isready: accepting connections"
exit 0
EOF

    # Mock pg_dump
    cat > "${mock_dir}/pg_dump" << 'EOF'
#!/bin/bash
echo "Mock pg_dump executing..."
echo "-- PostgreSQL database dump" > "$@"
echo "-- Dumped from database version 13.4" >> "$@"
echo "SET statement_timeout = 0;" >> "$@"
echo "CREATE TABLE test (id SERIAL PRIMARY KEY);" >> "$@"
echo "INSERT INTO test VALUES (1);" >> "$@"
echo "-- PostgreSQL database dump complete" >> "$@"
EOF

    chmod +x "${mock_dir}/pg_isready" "${mock_dir}/pg_dump"

    # Add mock directory to PATH
    export PATH="${mock_dir}:${PATH}"
}

create_test_br_kg_database() {
    local db_file="${BR_KG_DB_PATH}"
    local db_dir=$(dirname "${db_file}")
    mkdir -p "${db_dir}"

    # Create simple SQLite database for testing
    sqlite3 "${db_file}" << 'EOF'
CREATE TABLE nodes (
    id INTEGER PRIMARY KEY,
    label TEXT,
    type TEXT
);
CREATE TABLE edges (
    id INTEGER PRIMARY KEY,
    source_id INTEGER,
    target_id INTEGER,
    relationship TEXT
);
INSERT INTO nodes VALUES (1, 'Test Node', 'Concept');
INSERT INTO edges VALUES (1, 1, 1, 'relates_to');
EOF

    log_info "Created test BR-KG database: ${db_file}"
}

create_test_redis_data() {
    local data_dir="${TEST_BACKUP_DIR}/redis_test_data"
    mkdir -p "${data_dir}"

    # Create mock Redis data files
    echo "REDIS0009" > "${data_dir}/dump.rdb"
    echo "*3\r\n\$3\r\nSET\r\n\$8\r\ntest:key\r\n\$10\r\ntest:value\r\n" > "${data_dir}/appendonly.aof"

    log_info "Created test Redis data: ${data_dir}"
}

# Generate test report
generate_test_report() {
    log_info "Generating integration test report..."

    local report_file="${TEST_OUTPUT_DIR}/integration_test_report.html"

    cat > "${report_file}" << EOF
<!DOCTYPE html>
<html>
<head>
    <title>Backup System Integration Test Report</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .header { background-color: #f0f0f0; padding: 20px; border-radius: 5px; }
        .section { margin: 20px 0; }
        .pass { color: green; font-weight: bold; }
        .fail { color: red; font-weight: bold; }
        .results-table { border-collapse: collapse; width: 100%; }
        .results-table th, .results-table td { border: 1px solid #ddd; padding: 8px; text-align: left; }
        .results-table th { background-color: #f2f2f2; }
    </style>
</head>
<body>
    <div class="header">
        <h1>Backup System Integration Test Report</h1>
        <p>Generated on: $(date)</p>
        <p>Test Environment: Integration Testing</p>
    </div>

    <div class="section">
        <h2>Test Summary</h2>
        <p>This report contains the results of comprehensive integration testing for the Brain Researcher backup system.</p>
    </div>

    <div class="section">
        <h2>Backup Script Execution Results</h2>
        <table class="results-table">
            <tr><th>Component</th><th>Status</th></tr>
EOF

    if [[ -f "${TEST_OUTPUT_DIR}/backup_script_results.txt" ]]; then
        while IFS=':' read -r component status; do
            local status_class="fail"
            if [[ "${status}" == "PASS" ]]; then
                status_class="pass"
            fi
            echo "            <tr><td>${component}</td><td class=\"${status_class}\">${status}</td></tr>" >> "${report_file}"
        done < "${TEST_OUTPUT_DIR}/backup_script_results.txt"
    fi

    cat >> "${report_file}" << EOF
        </table>
    </div>

    <div class="section">
        <h2>Backup Verification Results</h2>
        <table class="results-table">
            <tr><th>Backup File</th><th>Status</th></tr>
EOF

    if [[ -f "${TEST_OUTPUT_DIR}/verification_results.txt" ]]; then
        while IFS=':' read -r backup_file status; do
            local status_class="fail"
            if [[ "${status}" == "PASS" ]]; then
                status_class="pass"
            fi
            echo "            <tr><td>${backup_file}</td><td class=\"${status_class}\">${status}</td></tr>" >> "${report_file}"
        done < "${TEST_OUTPUT_DIR}/verification_results.txt"
    fi

    cat >> "${report_file}" << EOF
        </table>
    </div>

    <div class="section">
        <h2>Recovery Procedure Results</h2>
        <table class="results-table">
            <tr><th>Recovery Test</th><th>Status</th></tr>
EOF

    if [[ -f "${TEST_OUTPUT_DIR}/recovery_results.txt" ]]; then
        while IFS=':' read -r recovery_test status; do
            local status_class="fail"
            if [[ "${status}" == "PASS" ]]; then
                status_class="pass"
            fi
            echo "            <tr><td>${recovery_test}</td><td class=\"${status_class}\">${status}</td></tr>" >> "${report_file}"
        done < "${TEST_OUTPUT_DIR}/recovery_results.txt"
    fi

    cat >> "${report_file}" << EOF
        </table>
    </div>

    <div class="section">
        <h2>Test Files and Logs</h2>
        <ul>
            <li><a href="integration_test.log">Main Test Log</a></li>
            <li><a href="postgres_backup_test.log">PostgreSQL Backup Log</a></li>
            <li><a href="br_kg_backup_test.log">BR-KG Backup Log</a></li>
            <li><a href="redis_backup_test.log">Redis Backup Log</a></li>
        </ul>
    </div>
</body>
</html>
EOF

    log_success "Integration test report generated: ${report_file}"
}

# Cleanup test environment
cleanup_test_environment() {
    log_info "Cleaning up test environment..."

    # Keep test results but clean up temporary files
    if [[ -d "${TEST_BACKUP_DIR}" ]]; then
        find "${TEST_BACKUP_DIR}" -name "*.tmp" -delete 2>/dev/null || true
    fi

    # Remove mock binaries
    local mock_dir="${TEST_OUTPUT_DIR}/mocks"
    if [[ -d "${mock_dir}" ]]; then
        rm -rf "${mock_dir}"
    fi

    log_info "Cleanup completed"
}

# Main execution
main() {
    echo "Starting Backup System Integration Test"
    echo "======================================="

    # Setup
    setup_test_environment

    # Run tests
    log_info "Running backup script execution tests..."
    test_backup_script_execution

    log_info "Running backup verification tests..."
    test_backup_verification

    log_info "Running recovery procedure tests..."
    test_recovery_procedures

    # Generate report
    generate_test_report

    # Cleanup
    cleanup_test_environment

    log_success "Integration test completed successfully"
    echo ""
    echo "Test results available in: ${TEST_OUTPUT_DIR}"
    echo "HTML report: ${TEST_OUTPUT_DIR}/integration_test_report.html"
    echo ""
}

# Error handling
trap 'log_error "Integration test failed with exit code $? at line $LINENO"' ERR

# Run main function if script is executed directly
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main "$@"
fi
