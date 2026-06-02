# Kubernetes Testing Suite for Brain Researcher Platform

This directory contains comprehensive Kubernetes deployment tests for the Brain Researcher platform. The test suite validates deployment integrity, service functionality, scaling behavior, rollback scenarios, and monitoring infrastructure.

## Test Structure

```
tests/k8s/
├── conftest.py                     # Shared fixtures and configuration
├── pytest.ini                     # Pytest configuration
├── run_k8s_tests.sh               # Main test runner script
├── README.md                      # This file
├── test_deployment_validation.py  # Core deployment validation tests
├── smoke/
│   └── test_smoke_tests.py        # Basic functionality smoke tests
├── rollback/
│   └── test_rollback_scenarios.py # Rollback and update tests
├── scaling/
│   └── test_scaling_validation.py # Scaling and load distribution tests
├── monitoring/
│   └── test_monitoring_validation.py # Monitoring stack validation
└── results/                       # Test results and reports
```

## Test Categories

### 1. Deployment Validation Tests (`test_deployment_validation.py`)

- **Namespace Validation**: Verify required namespaces exist and are properly configured
- **Service Connectivity**: Test service discovery and endpoint availability
- **Pod Readiness**: Validate all pods are running and healthy
- **Resource Limits**: Check resource requests and limits are properly set
- **Storage Mounting**: Verify persistent volumes and claims are correctly mounted
- **Network Policies**: Test network security configurations

### 2. Smoke Tests (`smoke/test_smoke_tests.py`)

- **Service Health Endpoints**: Test health check endpoints for all services
- **Database Connectivity**: Validate database connections (PostgreSQL, Redis)
- **Inter-Service Communication**: Test service-to-service communication
- **Ingress Routing**: Verify external access through ingress
- **SSL/TLS Validation**: Test certificate configuration and HTTPS redirection

### 3. Rollback Tests (`rollback/test_rollback_scenarios.py`)

- **Deployment Rollbacks**: Test deployment rollback functionality
- **StatefulSet Rollback Handling**: Validate StatefulSet update and rollback procedures
- **Data Persistence During Rollbacks**: Ensure data integrity during operations
- **Service Availability During Updates**: Test zero-downtime deployments

### 4. Scaling Tests (`scaling/test_scaling_validation.py`)

- **HPA Trigger Validation**: Test Horizontal Pod Autoscaler configuration
- **Load Distribution Tests**: Validate load balancing across multiple pods
- **Session Affinity Validation**: Test sticky sessions for stateful services
- **Database Connection Pooling**: Verify connection scaling under load

### 5. Monitoring Tests (`monitoring/test_monitoring_validation.py`)

- **Prometheus Metrics Collection**: Test metrics scraping from all services
- **Alert Rule Validation**: Verify alerting rules are properly configured
- **Log Aggregation Tests**: Test centralized logging functionality

## Prerequisites

### Software Requirements

- `kubectl` - Kubernetes command-line tool
- `python3` - Python 3.7+
- `pytest` - Python testing framework
- Access to a Kubernetes cluster with Brain Researcher deployed

### Python Dependencies

Install required packages:

```bash
pip install pytest requests pyyaml psycopg2-binary redis
```

### Cluster Access

Ensure you have proper access to the Kubernetes cluster:

```bash
# Verify cluster access
kubectl cluster-info

# Check namespace access
kubectl get pods -n brain-researcher-core
```

## Running Tests

### Quick Start

Run all tests with default configuration:

```bash
./run_k8s_tests.sh
```

### Selective Testing

Run specific test suites:

```bash
# Smoke tests only
./run_k8s_tests.sh smoke

# Deployment validation
./run_k8s_tests.sh validation

# Monitoring tests
./run_k8s_tests.sh monitoring
```

### Advanced Usage

```bash
# Custom namespace
./run_k8s_tests.sh -n my-namespace

# Skip destructive tests
./run_k8s_tests.sh --skip-destructive scaling

# Wait for services to be ready first
./run_k8s_tests.sh --wait-for-ready all

# Verbose output
./run_k8s_tests.sh -v smoke

# Custom output directory
./run_k8s_tests.sh -o /tmp/test-results all
```

### Using pytest directly

```bash
# Run specific test file
pytest test_deployment_validation.py -v

# Run tests with custom namespace
pytest --k8s-namespace=test-env smoke/

# Run only smoke tests
pytest -m smoke

# Skip destructive tests
pytest -m "not destructive"
```

## Test Configuration

### Environment Variables

- `K8S_NAMESPACE`: Default namespace (default: `brain-researcher-core`)
- `K8S_CONTEXT`: Kubernetes context to use

### Command Line Options

- `--k8s-namespace NAME`: Specify Kubernetes namespace
- `--k8s-context CONTEXT`: Specify Kubernetes context
- `--skip-destructive`: Skip tests that modify resources
- `--wait-for-ready`: Wait for services to be ready before testing

### Test Markers

Use pytest markers to select specific test types:

```bash
# Run only smoke tests
pytest -m smoke

# Run slow tests
pytest -m slow

# Skip destructive tests
pytest -m "not destructive"

# Run monitoring tests only
pytest -m monitoring
```

## Test Results

### Output Files

Test results are saved in the `results/` directory with timestamps:

- `*_results.xml`: JUnit XML test results
- `*_output.log`: Detailed test output logs
- `test_summary.md`: Human-readable summary report

### Interpreting Results

- **✅ PASSED**: All tests in the suite passed
- **❌ FAILED**: One or more tests failed
- **❓ NO RESULTS**: Tests were skipped or couldn't run

### Example Summary

```markdown
# Kubernetes Test Summary Report

**Test Run Date:** 2025-01-15 14:30:00
**Namespace:** brain-researcher-core
**Test Type:** all

## Test Results

### validation Tests
- **Status:** ✅ PASSED
- **Tests:** 25
- **Failures:** 0
- **Errors:** 0

### smoke Tests
- **Status:** ✅ PASSED
- **Tests:** 18
- **Failures:** 0
- **Errors:** 0
```

## Troubleshooting

### Common Issues

1. **Cluster Access Denied**
   ```bash
   # Check kubectl configuration
   kubectl config current-context
   kubectl auth can-i get pods --all-namespaces
   ```

2. **Services Not Ready**
   ```bash
   # Wait for services to be ready
   ./run_k8s_tests.sh --wait-for-ready

   # Check service status manually
   kubectl get pods -n brain-researcher-core
   ```

3. **Network Connectivity Issues**
   ```bash
   # Test from within cluster
   kubectl run test-pod --image=busybox --rm -it -- wget -qO- http://orchestrator-service:3001/health
   ```

4. **Permission Errors**
   ```bash
   # Check RBAC permissions
   kubectl auth can-i get deployments -n brain-researcher-core
   kubectl auth can-i get services -n brain-researcher-core
   ```

### Debug Mode

Run tests in debug mode for detailed output:

```bash
# Verbose pytest output
pytest -v -s test_deployment_validation.py

# Show all output including passed tests
pytest -v -s --tb=long

# Stop on first failure
pytest -x
```

### Logs and Diagnostics

Access pod logs for troubleshooting:

```bash
# Get pod logs
kubectl logs deployment/orchestrator -n brain-researcher-core

# Follow logs in real-time
kubectl logs -f deployment/agent -n brain-researcher-core

# Check events
kubectl get events -n brain-researcher-core --sort-by='.lastTimestamp'
```

## Development

### Adding New Tests

1. Create test files following the naming convention `test_*.py`
2. Use appropriate pytest markers (smoke, slow, destructive, etc.)
3. Add fixtures in `conftest.py` if needed
4. Update this README with new test descriptions

### Test Structure Template

```python
import pytest

class TestNewFeature:
    """Test new Kubernetes feature."""

    def test_basic_functionality(self, kubectl_client):
        """Test basic functionality."""
        # Test implementation
        pass

    @pytest.mark.slow
    def test_performance_scenario(self, kubectl_client):
        """Test performance under load."""
        # Test implementation
        pass

    @pytest.mark.destructive
    def test_failure_recovery(self, kubectl_client, skip_if_destructive):
        """Test recovery from failures."""
        # Test implementation
        pass
```

### Best Practices

1. **Isolation**: Tests should be independent and not rely on execution order
2. **Cleanup**: Use fixtures to ensure proper cleanup after destructive tests
3. **Timeouts**: Set appropriate timeouts for long-running operations
4. **Documentation**: Document test purpose and expected behavior
5. **Markers**: Use appropriate pytest markers for test categorization

## CI/CD Integration

### Pipeline Integration

Example GitHub Actions workflow:

```yaml
name: Kubernetes Tests

on: [push, pull_request]

jobs:
  k8s-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up kubectl
        uses: azure/setup-kubectl@v1

      - name: Configure cluster access
        run: |
          echo "${{ secrets.KUBECONFIG }}" | base64 -d > ~/.kube/config

      - name: Run K8s tests
        run: |
          cd tests/k8s
          ./run_k8s_tests.sh --skip-destructive all

      - name: Upload test results
        uses: actions/upload-artifact@v3
        if: always()
        with:
          name: k8s-test-results
          path: tests/k8s/results/
```

### Integration with Monitoring

Tests can be integrated with monitoring systems:

1. **Metrics Export**: Export test results as Prometheus metrics
2. **Alert Integration**: Set up alerts for test failures
3. **Dashboard**: Create Grafana dashboards for test trends

## Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests with appropriate documentation
4. Ensure all tests pass
5. Submit a pull request

For questions or issues, please refer to the main project documentation or open an issue in the repository.