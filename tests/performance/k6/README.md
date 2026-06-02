# Brain Researcher Performance Testing Suite

A comprehensive K6-based performance testing framework for validating the Brain Researcher backend services under various load conditions.

## Overview

This performance testing suite validates:
- **Orchestrator Service** (Port 3001) - Job orchestration and analysis APIs
- **BR-KG Service** (Port 5000) - Knowledge graph and data APIs
- **Agent Service** (Port 8000) - LLM-powered analysis agent

## Test Scenarios

### 1. Smoke Test (`smoke-test.js`)
- **Purpose**: Quick validation of basic functionality
- **Duration**: ~30 seconds
- **Load**: 1 virtual user
- **Use Case**: CI/CD pipeline validation, deployment verification

```bash
./scripts/run-smoke-test.sh
```

### 2. Load Test (`load-test.js`)
- **Purpose**: Normal production load simulation
- **Duration**: ~9 minutes
- **Load**: Ramp up to 50 virtual users
- **Use Case**: Performance baseline establishment, capacity planning

```bash
./scripts/run-load-test.sh
```

### 3. Stress Test (`stress-test.js`)
- **Purpose**: Beyond-normal capacity testing
- **Duration**: ~11 minutes
- **Load**: Up to 150 virtual users
- **Use Case**: Breaking point identification, graceful degradation validation

### 4. Spike Test (`spike-test.js`)
- **Purpose**: Sudden traffic spike simulation
- **Duration**: ~9 minutes
- **Load**: Alternating between 10 and 200 virtual users
- **Use Case**: Auto-scaling validation, traffic burst handling

### 5. Soak Test (`soak-test.js`)
- **Purpose**: Extended duration stability testing
- **Duration**: ~37 minutes
- **Load**: Sustained 30 virtual users
- **Use Case**: Memory leak detection, long-term stability validation

### 6. WebSocket Test (`websocket-test.js`)
- **Purpose**: Real-time communication validation
- **Duration**: ~9 minutes
- **Load**: Up to 50 concurrent WebSocket connections
- **Use Case**: Real-time features, job update streaming validation

### 7. SSE Stream Test (`sse-stream-test.js`)
- **Purpose**: Validate `/api/jobs/{id}/stream` under concurrent subscribers
- **Duration**: ~3 minutes
- **Load**: Ramps from 5 to 25 simultaneous EventSource clients
- **Use Case**: Ensures live progress updates stay healthy when multiple dashboards or tabs listen to the same jobs

## Performance Benchmarks

### Response Time Targets
- **P50**: < 500ms (50th percentile)
- **P95**: < 2000ms (95th percentile)
- **P99**: < 5000ms (99th percentile)

### Error Rate Thresholds
- **Normal Operations**: < 5% error rate
- **Stress Conditions**: < 15% error rate
- **Critical Endpoints**: < 1% error rate

### Throughput Requirements
- **Minimum**: 100 requests per second
- **Target**: 200+ requests per second
- **Burst Capacity**: 500+ requests per second

### Service-Specific SLAs
- **Orchestrator**: P95 < 1000ms
- **BR-KG**: P95 < 1500ms
- **Agent**: P95 < 3000ms (complex analysis operations)

## Quick Start

### Prerequisites

1. **Install K6**:
   ```bash
   # macOS
   brew install k6

   # Ubuntu/Debian
   sudo gpg -k
   sudo gpg --no-default-keyring --keyring /usr/share/keyrings/k6-archive-keyring.gpg --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D69
   echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" | sudo tee /etc/apt/sources.list.d/k6.list
   sudo apt-get update
   sudo apt-get install k6

   # Windows
   winget install k6
   ```

2. **Start Brain Researcher Services**:
   ```bash
   # Terminal 1: Orchestrator
   br serve orchestrator

   # Terminal 2: BR-KG
   br serve kg

   # Terminal 3: Agent
   br serve agent
   ```

3. **Verify Service Health**:
   ```bash
   curl http://localhost:3001/health  # Orchestrator
   curl http://localhost:5000/health  # BR-KG
   curl http://localhost:8000/health  # Agent
   ```

### Running Tests

#### Individual Test Scenarios
```bash
cd tests/performance/k6/

# Quick validation
./scripts/run-smoke-test.sh

# Production load simulation
./scripts/run-load-test.sh

# All test scenarios (except soak)
./scripts/run-all-tests.sh

# Include soak test (adds ~30 minutes)
RUN_SOAK_TEST=true ./scripts/run-all-tests.sh
```

#### Direct K6 Execution
```bash
# Run specific scenario
TEST_SCENARIO=load k6 run run-performance-tests.js

# Run with custom options
k6 run --vus 10 --duration 60s scenarios/load-test.js

# Generate JSON output
k6 run --out json=results.json scenarios/stress-test.js
```

## Configuration

### Environment Variables
```bash
# Service URLs (defaults shown)
export ORCHESTRATOR_URL="http://localhost:3001"
export BR_KG_URL="http://localhost:5000"
export AGENT_URL="http://localhost:8000"

# Test scenario selection
export TEST_SCENARIO="load"  # smoke|load|stress|spike|soak

# Optional flags
export RUN_SOAK_TEST="true"  # Include soak test in full suite
```

### Custom Thresholds
Modify `config/k6.config.js` to adjust:
- Response time thresholds
- Error rate limits
- Throughput requirements
- Service-specific SLAs

## Reports and Analysis

### Generated Reports
Each test generates multiple report formats:

#### HTML Reports (Recommended)
- **File**: `reports/[scenario]_test_[timestamp].html`
- **Content**: Interactive dashboard with metrics, charts, recommendations
- **Best For**: Detailed analysis, sharing with stakeholders

#### JSON Reports
- **File**: `reports/[scenario]_test_[timestamp].json`
- **Content**: Raw metrics data, programmatic analysis
- **Best For**: CI/CD integration, automated analysis

#### Text Summaries
- **File**: `reports/[scenario]_summary_[timestamp].txt`
- **Content**: Concise metrics summary
- **Best For**: Quick review, log aggregation

### Key Metrics

#### Response Time Analysis
- Average, median, P95, P99 response times
- Response time distribution histograms
- Service-specific response time breakdowns

#### Throughput Analysis
- Requests per second over time
- Peak throughput identification
- Sustained throughput capacity

#### Error Analysis
- Error rate trends
- Error categorization by type
- Service-specific error patterns

#### Resource Utilization
- Memory usage estimation
- CPU load indicators
- Connection pool utilization

## Troubleshooting

### Common Issues

#### Services Not Available
```bash
# Check service status
./scripts/run-smoke-test.sh

# Start missing services
br serve orchestrator  # Port 3001
br serve kg            # Port 5000
br serve agent         # Port 8000
```

#### High Error Rates
1. Check service logs for errors
2. Verify database connectivity
3. Review network configuration
4. Monitor resource utilization

#### Poor Performance
1. Check system resources (CPU, memory)
2. Review database query performance
3. Analyze network latency
4. Consider scaling infrastructure

### Debug Mode
```bash
# Verbose K6 output
k6 run --log-output=stdout --log-format=raw scenarios/load-test.js

# Custom metrics collection
K6_DEBUG=true k6 run scenarios/stress-test.js
```

## CI/CD Integration

### GitHub Actions Example
```yaml
name: Performance Tests
on: [push, pull_request]

jobs:
  performance:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Install K6
        run: |
          sudo gpg --no-default-keyring --keyring /usr/share/keyrings/k6-archive-keyring.gpg --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D69
          echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" | sudo tee /etc/apt/sources.list.d/k6.list
          sudo apt-get update && sudo apt-get install k6

      - name: Start Services
        run: |
          docker-compose up -d
          sleep 30  # Wait for services to start

      - name: Run Performance Tests
        run: |
          cd tests/performance/k6
          ./scripts/run-smoke-test.sh
          ./scripts/run-load-test.sh

      - name: Upload Reports
        uses: actions/upload-artifact@v3
        with:
          name: performance-reports
          path: tests/performance/k6/reports/
```

## Best Practices

### Performance Testing Strategy
1. **Start with Smoke Tests**: Validate basic functionality
2. **Establish Baselines**: Run load tests to set performance benchmarks
3. **Test Edge Cases**: Use stress and spike tests to find limits
4. **Monitor Long-term**: Use soak tests to catch stability issues

### Test Environment
- Use production-like data volumes
- Mirror production infrastructure configuration
- Run tests in isolated environment
- Monitor system resources during testing

### Continuous Monitoring
- Set up automated performance regression detection
- Track performance metrics over time
- Alert on threshold violations
- Regular capacity planning reviews

## Advanced Usage

### Custom Test Scenarios
Create new test scenarios by extending the base utilities:

```javascript
import { CONFIG } from './config/k6.config.js';
import { OrchestratorAPI, BR-KGAPI, AgentAPI } from './scripts/utils.js';

export default function() {
  const orchestrator = new OrchestratorAPI();
  const brKg = new BR-KGAPI();

  // Custom test logic
  orchestrator.listDatasets();
  brKg.executeSearch('custom query', ['Study'], 50);
}
```

### Load Pattern Customization
Modify `config/k6.config.js` to create custom load profiles:

```javascript
CUSTOM_PROFILE: {
  stages: [
    { duration: '5m', target: 100 },  // Custom ramp-up
    { duration: '10m', target: 200 }, // Custom load level
    { duration: '3m', target: 0 },    // Custom ramp-down
  ],
}
```

## Contributing

### Adding New Test Scenarios
1. Create scenario file in `scenarios/`
2. Add configuration in `config/k6.config.js`
3. Update documentation
4. Add integration to master runner

### Reporting Issues
Include in bug reports:
- K6 version
- Test scenario details
- Service configuration
- Error logs and stack traces
- System resource information

## Support

- **Documentation**: This README and inline code comments
- **Issues**: GitHub Issues for bug reports and feature requests
- **Performance Optimization**: Contact the Brain Researcher team

---

**Note**: Performance testing should be run in a controlled environment that mirrors production infrastructure for accurate results. Resource-constrained environments may show different performance characteristics than production systems.
