# Load Balancing and Auto-scaling Test Suite

This directory contains comprehensive tests for the Brain Researcher load balancing and auto-scaling infrastructure.

## Test Structure

### Core Test Categories

1. **HAProxy Load Balancing** (`test_haproxy_load_balancing.py`)
   - Traffic distribution fairness
   - Weighted load balancing
   - Health check functionality
   - Failover scenarios
   - Session affinity
   - SSL termination

2. **Auto-scaling System** (`test_autoscaler.py`)
   - CPU/Memory-based scaling
   - Custom metrics scaling
   - Predictive ML scaling
   - Scaling decision logic
   - Cooldown periods
   - Multi-platform support

3. **Blue-Green Deployments** (`test_blue_green_deployment.py`)
   - Zero-downtime deployments
   - Gradual traffic switching
   - Health check validation
   - Automatic rollback
   - State persistence

4. **Connection Pooling** (`test_connection_pooling.py`)
   - PgBouncer performance
   - Connection limits
   - Pool exhaustion scenarios
   - Transaction isolation

5. **Kubernetes HPA** (`test_k8s_hpa.py`)
   - Resource-based scaling
   - Custom metrics integration
   - Scaling policies
   - Behavior configuration

6. **Integration Tests** (`test_integration.py`)
   - End-to-end workflows
   - Service mesh testing
   - Cross-platform validation

### Load Testing with K6

- **Scenarios** (`k6/scenarios/`)
  - Load testing
  - Stress testing
  - Spike testing
  - Soak testing
  - WebSocket testing

- **Configuration** (`k6/config/`)
  - Environment-specific configs
  - Thresholds and SLAs
  - Metric collection

## Running Tests

### Complete Test Suite
```bash
# Run all tests (recommended)
./tests/load/run_all_tests.sh

# Run with specific environment
TEST_ENVIRONMENT=staging ./tests/load/run_all_tests.sh

# Run including long-duration soak test
RUN_SOAK_TEST=true ./tests/load/run_all_tests.sh
```

### Unit Tests
```bash
# Run all load balancing tests
pytest tests/load/ -v

# Run specific test category
pytest tests/load/test_autoscaler.py -v

# Run with coverage
pytest tests/load/ --cov=infrastructure --cov-report=html
```

### Integration Tests
```bash
# Run integration tests (requires running infrastructure)
pytest tests/integration/load_balancing/ -v --integration

# Run with real services
pytest tests/integration/load_balancing/ -v --live-services

# Complete system integration test
pytest tests/integration/load_balancing/test_complete_system.py -v
```

### Load Tests with K6
```bash
# Run load test scenarios
cd tests/load/k6

# Standard load test
k6 run --config config/development.json scenarios/load-test.js

# Stress test to find system limits
k6 run --config config/staging.json scenarios/stress-test.js

# Spike test for sudden load increases
k6 run scenarios/spike-test.js

# Long-duration soak test (1-4 hours)
k6 run --config config/production.json scenarios/soak-test.js

# WebSocket load test
k6 run scenarios/websocket-test.js

# Comprehensive API endpoint test
k6 run scenarios/api-endpoints-test.js
```

## Test Environment Setup

### Prerequisites
- Docker Swarm or Kubernetes cluster
- HAProxy running
- Redis for metrics storage
- Prometheus for monitoring
- K6 for load testing

### Environment Variables
```bash
# Platform configuration
PLATFORM=swarm  # or k8s
NAMESPACE=brain-researcher-test

# Service endpoints
HAPROXY_STATS_URL=http://localhost:8080/stats
REDIS_URL=redis://localhost:6379
PROMETHEUS_URL=http://localhost:9090

# Test configuration
LOAD_TEST_DURATION=300s
LOAD_TEST_VUS=50
STRESS_TEST_VUS=100
```

### Mock Services
The test suite includes mock services that simulate the behavior of Brain Researcher components:
- Mock Orchestrator
- Mock BR-KG
- Mock Agent
- Mock Web UI

## Test Fixtures and Data

### Synthetic Data
- Pre-generated load test data
- Mock metrics and health check responses
- Scaling scenario configurations

### Real Data Integration
- Optional integration with live services
- Performance baseline data
- Historical scaling patterns

## Metrics and Reporting

### Test Metrics Collected
- Response times and latencies
- Throughput (requests/second)
- Error rates and types
- Resource utilization
- Scaling decisions and timing
- Connection pool statistics

### Reports Generated
- HTML test reports
- K6 performance reports
- Scaling decision analysis
- Load balancing distribution analysis

## Continuous Integration

### GitHub Actions
Tests are automatically run on:
- Pull requests affecting infrastructure
- Scheduled nightly runs
- Infrastructure deployment changes

### Test Environments
- **Development**: Mock services only
- **Staging**: Real services with test data
- **Pre-production**: Full load testing

## Performance Baselines

### Expected Performance
- API response time: < 200ms (95th percentile)
- Load balancer overhead: < 5ms
- Auto-scaling decision time: < 30s
- Blue-green deployment time: < 5 minutes

### SLA Requirements
- 99.9% uptime during normal operations
- 99.5% uptime during deployments
- < 0.1% error rate under normal load
- Auto-scaling response within 2 minutes

## Troubleshooting

### Common Issues
1. **Test timeouts**: Increase test timeouts for slow environments
2. **Port conflicts**: Ensure test ports don't conflict with running services
3. **Resource limits**: Verify sufficient resources for load tests
4. **Network connectivity**: Check service discovery and networking

### Debugging
- Check HAProxy stats interface
- Review autoscaler logs
- Monitor Prometheus metrics
- Analyze K6 output files

## Contributing

When adding new tests:
1. Follow existing test patterns
2. Include both positive and negative test cases
3. Add appropriate fixtures and mock data
4. Update documentation
5. Ensure tests are deterministic and isolated