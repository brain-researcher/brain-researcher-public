# AGENT-012 Test Fixtures

This directory contains test fixtures and utilities for testing the Multi-Backend Runtime Support system (AGENT-012).

## Overview

The AGENT-012 multi-backend system enables Brain Researcher to execute neuroimaging jobs across multiple computational backends including Kubernetes, SLURM HPC clusters, and AWS Batch. These fixtures provide comprehensive test scenarios, mock responses, and configuration examples.

## File Structure

### `sample_configs.yaml`
Complete configuration examples for setting up multiple backends in production environments. Includes:

- **Backend Configurations**: Real-world configs for Kubernetes, SLURM, and AWS Batch
- **Selection Strategies**: Different approaches for backend selection (fastest, cheapest, most available, etc.)
- **Resource Profiles**: Predefined resource templates for common neuroimaging workloads
- **Job Templates**: Reusable job definitions for standard analyses (FSL, FreeSurfer, etc.)
- **Failover Rules**: Automatic fallback configurations between backends
- **Monitoring Settings**: Health check and alerting configurations

### `test_scenarios.json`
Comprehensive test scenarios covering all aspects of multi-backend operation:

- **Backend Scenarios**: Different backend states (healthy, busy, degraded, failed)
- **Job Scenarios**: Various neuroimaging workloads with different resource requirements
- **Failover Scenarios**: Backend failure conditions and expected recovery behavior
- **Selection Strategy Scenarios**: Tests for all selection algorithms
- **Error Scenarios**: Various failure modes and error conditions
- **Performance Benchmarks**: Target performance metrics for each operation
- **Stress Test Scenarios**: High-load and concurrent operation tests

### `mock_responses.py`
Mock response generators and utilities for testing backend integrations:

- **MockKubernetesResponses**: Kubernetes API response generators
- **MockSLURMResponses**: SLURM command output generators  
- **MockAWSBatchResponses**: AWS Batch API response generators
- **MockBackendFactory**: Factory for creating test backend instances
- **Utility Functions**: Helper functions for generating test data

## Usage Examples

### Using Mock Backends in Tests

```python
from tests.fixtures.AGENT_012.mock_responses import MockBackendFactory

# Create different types of mock backends
healthy_k8s = MockBackendFactory.create_healthy_kubernetes_backend("test-k8s")
busy_slurm = MockBackendFactory.create_busy_slurm_backend("test-slurm")
expensive_aws = MockBackendFactory.create_expensive_aws_backend("test-aws")

# Use in backend selector tests
selector = BackendSelector([healthy_k8s, busy_slurm, expensive_aws])
```

### Loading Test Scenarios

```python
import json
from pathlib import Path

# Load test scenarios
scenarios_file = Path(__file__).parent / "test_scenarios.json"
with open(scenarios_file) as f:
    scenarios = json.load(f)

# Get specific scenario
failover_scenario = scenarios["failover_scenarios"]["primary_backend_down"]
```

### Using Configuration Templates

```python
import yaml
from pathlib import Path

# Load sample configuration
config_file = Path(__file__).parent / "sample_configs.yaml"
with open(config_file) as f:
    config = yaml.safe_load(f)

# Extract backend configs
k8s_config = config["backends"]["university_k8s"]["config"]
slurm_config = config["backends"]["hpc_slurm"]["config"]
```

## Test Categories

### Unit Tests
- Individual backend implementation testing
- Backend selector algorithm testing
- Resource requirement validation
- Error handling and edge cases

### Integration Tests
- Multi-backend job submission workflows
- Failover mechanism testing
- End-to-end job lifecycle testing
- Configuration loading and validation

### Performance Tests
- Backend selection latency
- Concurrent job submission
- Health check performance
- Capacity query performance

### Stress Tests
- High concurrent load testing
- Backend failure during operation
- Resource contention scenarios
- Long-running job monitoring

## Backend-Specific Test Data

### Kubernetes Tests
- Job manifest generation and validation
- Pod status monitoring
- Resource allocation testing
- GPU resource handling
- Namespace isolation

### SLURM Tests
- Job script generation
- SLURM command output parsing
- SSH connection handling
- Multi-node job support
- Module loading and environment setup

### AWS Batch Tests
- Job definition creation
- CloudWatch log retrieval
- Cost estimation
- Fargate vs EC2 configuration
- IAM role and permission handling

## Performance Benchmarks

The fixtures include performance targets for various operations:

- **Backend Selection**: < 500ms (p95)
- **Job Submission**: < 2-10s depending on backend (p95)
- **Health Checks**: < 1s (p95)
- **Status Updates**: < 2s (p95)

## Error Scenarios

Comprehensive error condition testing including:

- Network connectivity failures
- Authentication/authorization errors
- Resource quota exceeded
- Invalid job specifications
- Backend service unavailability
- Timeout conditions

## Resource Profiles

Standard resource profiles for common neuroimaging workloads:

- **Light**: 2 CPU, 8GB RAM, 30min (skull stripping, simple preprocessing)
- **Standard**: 8 CPU, 32GB RAM, 1 GPU, 2hr (fMRI analysis, GLM)
- **Heavy**: 32 CPU, 128GB RAM, 4 GPU, 8hr (deep learning, connectomics)
- **Distributed**: 64 CPU, 256GB RAM, 24hr, multi-node (population studies)

## Extending the Fixtures

When adding new test scenarios:

1. **Add to test_scenarios.json**: Define the scenario parameters and expected outcomes
2. **Update mock_responses.py**: Add any new mock response generators needed
3. **Update sample_configs.yaml**: Add configuration examples if introducing new features
4. **Document the scenario**: Update this README with usage examples

## Integration with Test Suite

These fixtures are used throughout the AGENT-012 test suite:

- `tests/unit/test_backends/`: Backend-specific unit tests
- `tests/integration/test_multi_backend.py`: Cross-backend integration tests
- `tests/performance/`: Performance and stress testing
- `tests/e2e/`: End-to-end workflow testing

## Best Practices

1. **Use realistic data**: Mock responses should closely match real backend behavior
2. **Test edge cases**: Include both success and failure scenarios
3. **Validate configurations**: Ensure sample configs work with actual backends
4. **Performance awareness**: Include timing and resource constraints in tests
5. **Maintainability**: Keep fixtures up-to-date with backend API changes