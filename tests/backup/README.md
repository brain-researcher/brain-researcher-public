# Backup and Recovery Testing Suite

Comprehensive test suites for the Brain Researcher platform backup and recovery system.

## Overview

This testing suite provides comprehensive validation of backup and recovery functionality including:

- **Backup Validation Tests**: Verify backup script execution, integrity, compression, encryption, and retention policies
- **Recovery Tests**: Test point-in-time recovery, full system recovery, partial recovery scenarios, and rollback procedures
- **Performance Tests**: Benchmark backup duration, recovery time validation, storage usage, and network bandwidth
- **Failure Scenario Tests**: Test backup failure handling, corrupted backup detection, network failures, and storage failures
- **Monitoring Tests**: Validate alert triggering, metric collection, and health checks

## Test Structure

```
tests/backup/
├── __init__.py                     # Package initialization
├── conftest.py                     # Pytest fixtures and configuration
├── test_backup_validation.py       # Backup validation tests
├── test_performance.py             # Performance and benchmark tests
├── test_failure_scenarios.py       # Failure scenario tests
├── test_monitoring.py              # Monitoring and alerting tests
├── recovery/                       # Recovery test modules
│   ├── __init__.py
│   ├── test_point_in_time_recovery.py
│   └── test_full_system_recovery.py
├── scripts/                        # Integration test scripts
│   └── test_backup_integration.sh
├── run_all_tests.py               # Comprehensive test runner
└── README.md                      # This file
```

## Running Tests

### Quick Start

Run all backup tests:
```bash
cd tests/backup
python run_all_tests.py
```

### Specific Test Types

Run specific test categories:
```bash
# Backup validation tests only
python run_all_tests.py --test-types validation

# Recovery tests only
python run_all_tests.py --test-types recovery

# Performance tests only
python run_all_tests.py --test-types performance

# Multiple categories
python run_all_tests.py --test-types validation recovery performance
```

### Advanced Options

```bash
# Verbose output
python run_all_tests.py --verbose

# Custom output directory
python run_all_tests.py --output-dir /path/to/results

# Generate coverage reports
python run_all_tests.py --coverage

# Integration tests only
python run_all_tests.py --test-types integration
```

### Individual Test Modules

Run individual test modules using pytest:

```bash
# Backup validation tests
pytest test_backup_validation.py -v

# Recovery tests
pytest recovery/ -v

# Performance tests
pytest test_performance.py -v

# Failure scenario tests
pytest test_failure_scenarios.py -v

# Monitoring tests
pytest test_monitoring.py -v
```

### Integration Tests

Run shell-based integration tests directly:

```bash
# Full integration test suite
./scripts/test_backup_integration.sh

# Set custom test output directory
TEST_OUTPUT_DIR=/tmp/backup_tests ./scripts/test_backup_integration.sh
```

## Test Categories

### 1. Backup Validation Tests (`test_backup_validation.py`)

**TestBackupScriptExecution**
- PostgreSQL backup script success/failure
- BR-KG backup script validation
- Redis backup script testing
- Parallel backup execution
- Timeout and error handling

**TestBackupIntegrity**
- File integrity verification
- Corruption detection
- Checksum validation
- SQL content validation
- Database backup completeness

**TestCompressionAndEncryption**
- Gzip compression functionality
- AES encryption/decryption
- Combined compression+encryption pipeline
- Encryption key validation
- Algorithm selection testing

**TestBackupSizeAndContent**
- Size validation and limits
- Content completeness verification
- Version consistency across components
- Database table coverage analysis

**TestRetentionPolicies**
- Retention policy enforcement
- Component-specific retention
- Minimum backup preservation
- S3 retention policies

### 2. Recovery Tests (`recovery/`)

**TestPointInTimeRecovery** (`test_point_in_time_recovery.py`)
- PostgreSQL point-in-time recovery
- BR-KG temporal recovery
- Redis state restoration
- Cross-component consistency
- Recovery with missing backups
- Exact vs nearest timestamp matching

**TestFullSystemRecovery** (`test_full_system_recovery.py`)
- Complete system recovery workflow
- Staged recovery with dependencies
- Service dependency management
- Recovery environment isolation
- Comprehensive validation after recovery
- Performance monitoring during recovery
- Rollback capability testing
- Disaster recovery scenarios
- Recovery with data migration

### 3. Performance Tests (`test_performance.py`)

**TestBackupPerformance**
- PostgreSQL backup duration benchmarks
- Compression performance testing
- Encryption performance impact
- Network transfer performance
- Concurrent backup optimization
- Storage usage optimization

**TestRecoveryPerformance**
- Recovery time benchmarks
- Parallel vs sequential recovery
- Recovery scalability testing
- Performance under resource constraints

### 4. Failure Scenario Tests (`test_failure_scenarios.py`)

**TestBackupFailureHandling**
- PostgreSQL backup failure detection
- Retry mechanisms with exponential backoff
- Failure notification systems
- Failure escalation procedures
- Graceful degradation
- Corruption detection during creation

**TestIncompleteBackupRecovery**
- Recovery from incomplete PostgreSQL backups
- Missing backup component handling
- Timestamp mismatch recovery
- Partial recovery from corrupted backups
- Broken dependency chain recovery

**TestCorruptedBackupDetection**
- File format corruption detection
- Checksum-based corruption detection
- Content corruption identification
- Size anomaly detection

**TestNetworkFailureSimulation**
- S3 upload network failures
- Webhook notification failures
- Database connection failures
- Bandwidth degradation testing

**TestStorageFailureHandling**
- Disk space exhaustion
- Storage device failures
- Directory permission issues
- Filesystem corruption
- Network storage disconnection

### 5. Monitoring Tests (`test_monitoring.py`)

**TestAlertTriggering**
- Backup failure alerts
- Recovery success alerts
- Duration threshold alerts
- Size anomaly alerts
- Schedule miss alerts
- Storage space alerts

**TestMetricCollection**
- Performance metrics collection
- Reliability metrics tracking
- Storage utilization monitoring
- Schedule compliance metrics
- Quality and integrity metrics
- Cost and efficiency tracking

**TestHealthCheckValidation**
- Service health monitoring
- Storage accessibility checks
- Encryption system validation
- Network connectivity testing
- Integrity verification
- Comprehensive system health assessment

## Test Configuration

### Environment Variables

```bash
# Test configuration
export BACKUP_TEST_COVERAGE=1              # Enable coverage reporting
export TEST_OUTPUT_DIR=/path/to/output      # Custom test output directory
export BACKUP_TEST_TIMEOUT=300             # Test timeout in seconds

# Backup system configuration
export BACKUP_DIR=/path/to/backups          # Backup directory
export POSTGRES_HOST=localhost             # PostgreSQL host
export POSTGRES_PORT=5432                  # PostgreSQL port
export POSTGRES_USER=test_user             # PostgreSQL user
export POSTGRES_DB=test_db                 # PostgreSQL database
export ENCRYPTION_KEY_FILE=/path/to/key    # Encryption key file
export WEBHOOK_URL=http://webhook.test     # Notification webhook
export S3_BUCKET=test-backup-bucket        # S3 bucket for backups
```

### Pytest Configuration

The `conftest.py` file provides comprehensive fixtures for testing:

- `temp_backup_dir`: Temporary backup directory
- `mock_encryption_key`: Mock encryption key file
- `sample_postgres_backup`: Sample PostgreSQL backup
- `sample_br_kg_db`: Sample BR-KG database
- `sample_redis_data`: Sample Redis backup data
- `backup_config`: Standard backup configuration
- Various mock objects for external services

### Test Markers

Use pytest markers to run specific test categories:

```bash
# Run only unit tests
pytest -m unit

# Run only integration tests
pytest -m integration

# Run only slow tests
pytest -m slow

# Skip slow tests
pytest -m "not slow"
```

## Continuous Integration

### GitHub Actions Integration

Example CI configuration:

```yaml
name: Backup System Tests

on: [push, pull_request]

jobs:
  backup-tests:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:13
        env:
          POSTGRES_PASSWORD: testpass
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

      redis:
        image: redis:6
        options: >-
          --health-cmd "redis-cli ping"
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5

    steps:
    - uses: actions/checkout@v3

    - name: Set up Python
      uses: actions/setup-python@v4
      with:
        python-version: '3.9'

    - name: Install dependencies
      run: |
        pip install -r requirements.txt
        pip install pytest pytest-cov

    - name: Run backup tests
      run: |
        cd tests/backup
        python run_all_tests.py --coverage

    - name: Upload coverage reports
      uses: codecov/codecov-action@v3
```

### Local Pre-commit Hooks

Add to `.pre-commit-config.yaml`:

```yaml
repos:
  - repo: local
    hooks:
      - id: backup-tests
        name: Backup system tests
        entry: python tests/backup/run_all_tests.py --test-types validation
        language: system
        pass_filenames: false
        always_run: true
```

## Test Data and Fixtures

### Test Database Creation

Tests automatically create temporary test databases:

```python
# PostgreSQL test database
CREATE DATABASE brain_researcher_test;

# BR-KG SQLite test database with nodes and edges
CREATE TABLE nodes (id INTEGER PRIMARY KEY, label TEXT, type TEXT);
CREATE TABLE edges (id INTEGER PRIMARY KEY, source_id INTEGER, target_id INTEGER, relationship TEXT);

# Redis test data with various data types
SET test:key "test:value"
HSET test:hash field1 "value1" field2 "value2"
LPUSH test:list "item1" "item2" "item3"
```

### Mock Services

Tests use comprehensive mocking for external dependencies:

- PostgreSQL connections and commands (`pg_dump`, `pg_isready`)
- S3 client operations (`boto3`)
- Network requests (`requests`)
- File system operations
- Encryption operations (`openssl`)

## Troubleshooting

### Common Issues

**1. Permission Denied Errors**
```bash
# Ensure test scripts are executable
chmod +x tests/backup/scripts/*.sh
chmod +x tests/backup/run_all_tests.py
```

**2. Missing Dependencies**
```bash
# Install required test dependencies
pip install pytest pytest-mock requests boto3 psutil
```

**3. Database Connection Errors**
```bash
# Check PostgreSQL service is running
sudo systemctl status postgresql
sudo systemctl start postgresql

# Verify Redis service
sudo systemctl status redis
sudo systemctl start redis
```

**4. Timeout Issues**
```bash
# Increase test timeout for slow systems
export BACKUP_TEST_TIMEOUT=600
```

### Debug Mode

Enable debug logging for detailed test execution:

```bash
# Enable debug logging
export PYTHONPATH=$PWD:$PYTHONPATH
export LOG_LEVEL=DEBUG

# Run tests with maximum verbosity
python run_all_tests.py --verbose --test-types validation
```

### Test Output Locations

Test outputs are saved to:
```
tests/backup/test_results/
├── backup_test_results.json         # Overall test results
├── validation_results.xml           # Pytest XML results
├── performance_results.xml          # Performance test results
├── integration_test_output/          # Integration test outputs
│   ├── integration_test.log
│   ├── integration_test_report.html
│   └── test_backups/                # Sample backup files
└── coverage_reports/                # Coverage reports (if enabled)
    ├── coverage.xml
    └── htmlcov/
```

## Contributing

When adding new backup tests:

1. **Follow the existing test structure and naming conventions**
2. **Add comprehensive docstrings and comments**
3. **Include both positive and negative test cases**
4. **Use appropriate fixtures from `conftest.py`**
5. **Mock external dependencies appropriately**
6. **Add performance benchmarks where relevant**
7. **Update this README with new test descriptions**

### Test Development Guidelines

- **Test Organization**: Group related tests into classes
- **Test Independence**: Each test should be independent and not rely on others
- **Resource Cleanup**: Use fixtures and context managers for cleanup
- **Error Testing**: Test both success and failure scenarios
- **Performance**: Include timing and resource usage validation
- **Documentation**: Document test purpose, setup, and expected outcomes

## License

This test suite is part of the Brain Researcher project and follows the same licensing terms.