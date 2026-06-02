# K6 Load Testing for Brain Researcher Load Balancing Infrastructure

This directory contains comprehensive K6 load testing scenarios for validating the Brain Researcher platform's load balancing and auto-scaling infrastructure under various load conditions.

## Overview

K6 is a modern load testing tool that uses JavaScript for scripting test scenarios. It's designed for developers and provides excellent performance, reliability, and ease of use for testing APIs, microservices, and web applications.

## Directory Structure

```
k6/
├── scenarios/
│   ├── load-test.js          # Standard load testing
│   ├── stress-test.js        # Stress testing to find limits
│   ├── spike-test.js         # Spike testing for sudden load
│   ├── soak-test.js          # Soak testing for long-duration stability
│   ├── websocket-test.js     # WebSocket connection testing
│   └── api-endpoints-test.js # Comprehensive API endpoint testing
├── config/
│   ├── development.json      # Development environment config
│   ├── staging.json          # Staging environment config
│   └── production.json       # Production environment config
├── utils/
│   ├── common.js             # Common utilities and helpers
│   ├── auth.js               # Authentication helpers
│   └── metrics.js            # Custom metrics definitions
├── data/
│   ├── test-data.json        # Sample test data
│   └── user-scenarios.json   # User behavior scenarios
└── reports/                  # Generated test reports
```

## Test Scenarios

### 1. Load Test (`load-test.js`)
- **Purpose**: Validate normal expected load behavior
- **Duration**: 10-30 minutes
- **Users**: 10-100 concurrent users
- **Ramp-up**: Gradual increase to simulate realistic traffic
- **Validates**: Response times, throughput, error rates under normal load

### 2. Stress Test (`stress-test.js`)
- **Purpose**: Find the breaking point of the system
- **Duration**: 15-45 minutes
- **Users**: Gradually increase until system degrades
- **Ramp-up**: Aggressive increase to push system limits
- **Validates**: Maximum capacity, degradation patterns, recovery behavior

### 3. Spike Test (`spike-test.js`)
- **Purpose**: Validate behavior under sudden traffic spikes
- **Duration**: 5-15 minutes with spike periods
- **Users**: Sudden jumps from baseline to high load
- **Pattern**: Baseline → Spike → Return to baseline
- **Validates**: Auto-scaling responsiveness, spike handling, recovery

### 4. Soak Test (`soak-test.js`)
- **Purpose**: Validate long-term stability and resource leaks
- **Duration**: 1-4 hours
- **Users**: Moderate constant load
- **Pattern**: Steady state for extended period
- **Validates**: Memory leaks, connection pooling, long-term stability

### 5. WebSocket Test (`websocket-test.js`)
- **Purpose**: Test WebSocket connections and real-time features
- **Duration**: 10-30 minutes
- **Connections**: Multiple concurrent WebSocket connections
- **Validates**: WebSocket load balancing, session affinity, connection limits

### 6. API Endpoints Test (`api-endpoints-test.js`)
- **Purpose**: Comprehensive testing of all API endpoints
- **Coverage**: All critical API endpoints
- **Scenarios**: Various user workflows and data patterns
- **Validates**: Individual endpoint performance, load balancing distribution

## Configuration

### Environment Configuration Files

Each environment has specific configuration:

```json
{
  "baseUrl": "https://brain-researcher-staging.com",
  "thresholds": {
    "http_req_duration": ["p(95)<500"],
    "http_req_failed": ["rate<0.01"]
  },
  "stages": [
    {"duration": "2m", "target": 10},
    {"duration": "5m", "target": 50},
    {"duration": "5m", "target": 50},
    {"duration": "2m", "target": 0}
  ]
}
```

### Performance Thresholds

| Metric | Development | Staging | Production |
|--------|-------------|---------|------------|
| Response Time (95th percentile) | < 1000ms | < 500ms | < 200ms |
| Error Rate | < 5% | < 1% | < 0.1% |
| Throughput | > 10 RPS | > 50 RPS | > 200 RPS |
| WebSocket Connections | > 100 | > 500 | > 2000 |

## Running Tests

### Prerequisites

1. Install K6:
   ```bash
   # MacOS
   brew install k6

   # Ubuntu/Debian
   sudo apt-key adv --keyserver hkp://keyserver.ubuntu.com:80 --recv-keys C5AD17C747E3415A3642D57D77C6C491D6AC1D69
   echo "deb https://dl.k6.io/deb stable main" | sudo tee /etc/apt/sources.list.d/k6.list
   sudo apt-get update
   sudo apt-get install k6

   # Docker
   docker run -i loadimpact/k6 run - <script.js
   ```

2. Set environment variables:
   ```bash
   export K6_ENVIRONMENT=development
   export BASE_URL=http://localhost
   export AUTH_TOKEN=your_test_token
   ```

### Basic Test Execution

```bash
# Run basic load test
k6 run scenarios/load-test.js

# Run with specific config
k6 run --config config/staging.json scenarios/stress-test.js

# Run with environment variables
k6 run -e BASE_URL=http://localhost:3000 scenarios/load-test.js

# Run with custom VUs and duration
k6 run --vus 50 --duration 10m scenarios/load-test.js
```

### Advanced Test Execution

```bash
# Run with results output
k6 run --out json=reports/load-test-results.json scenarios/load-test.js

# Run with InfluxDB output (for Grafana dashboards)
k6 run --out influxdb=http://localhost:8086/k6 scenarios/load-test.js

# Run with multiple outputs
k6 run --out json=reports/results.json --out influxdb=http://localhost:8086/k6 scenarios/load-test.js

# Run test suite
./run-all-tests.sh
```

## Test Data and Scenarios

### User Scenarios

The tests simulate realistic user behavior patterns:

1. **Researcher Workflow**:
   - Login → Browse datasets → Run analysis → View results
   - Duration: 5-15 minutes
   - API calls: 10-30 requests

2. **Data Analysis Session**:
   - Authentication → Upload data → Configure analysis → Monitor progress
   - Duration: 10-30 minutes
   - API calls: 20-100 requests

3. **Collaborative Session**:
   - Multiple users working on shared project
   - Real-time updates via WebSocket
   - Duration: 30-60 minutes

### Test Data

Sample datasets and configurations are provided for consistent testing:
- Neuroimaging data samples
- User profiles and authentication tokens
- Analysis configurations
- Mock API responses

## Monitoring and Alerting

### Built-in Metrics

K6 provides comprehensive metrics:
- `http_req_duration`: HTTP request duration
- `http_req_failed`: Failed HTTP request rate
- `http_reqs`: HTTP request rate
- `data_sent`: Data transmission rate
- `data_received`: Data reception rate
- `vus`: Number of active virtual users
- `iterations`: Number of completed iterations

### Custom Metrics

Additional custom metrics for Brain Researcher:
- `analysis_request_duration`: Time for analysis requests
- `websocket_connection_time`: WebSocket connection establishment time
- `file_upload_duration`: File upload completion time
- `auto_scaling_response_time`: Time for auto-scaling to respond

### Thresholds and SLA Validation

Tests automatically validate SLA requirements:

```javascript
export let options = {
  thresholds: {
    'http_req_duration': ['p(95)<500'], // 95% of requests under 500ms
    'http_req_failed': ['rate<0.01'],   // Error rate under 1%
    'analysis_request_duration': ['p(90)<30000'], // 90% of analyses under 30s
  }
}
```

## Integration with CI/CD

### GitHub Actions Integration

```yaml
name: Load Testing
on:
  schedule:
    - cron: '0 2 * * *'  # Daily at 2 AM
  workflow_dispatch:

jobs:
  load-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Run K6 Load Test
        uses: grafana/k6-action@v0.2.0
        with:
          filename: tests/load/k6/scenarios/load-test.js
          flags: --out json=reports/load-test-results.json
```

### Jenkins Integration

```groovy
pipeline {
    agent any
    stages {
        stage('Load Testing') {
            steps {
                sh 'k6 run --out json=reports/results.json tests/load/k6/scenarios/load-test.js'
                publishHTML([
                    allowMissing: false,
                    alwaysLinkToLastBuild: true,
                    keepAll: true,
                    reportDir: 'reports',
                    reportFiles: 'results.html',
                    reportName: 'K6 Load Test Report'
                ])
            }
        }
    }
}
```

## Performance Baselines

### Expected Performance Characteristics

| Component | Baseline Performance | Load Test Target | Stress Test Limit |
|-----------|---------------------|------------------|------------------|
| HAProxy Load Balancer | 5ms overhead | < 10ms | < 20ms |
| API Gateway | 50ms response time | < 100ms | < 200ms |
| Orchestrator | 100ms processing | < 200ms | < 500ms |
| BR-KG | 200ms queries | < 400ms | < 1000ms |
| Agent (LLM) | 2000ms responses | < 5000ms | < 10000ms |
| WebSocket | 10ms latency | < 50ms | < 100ms |

### Scaling Expectations

| Metric | Development | Staging | Production |
|--------|-------------|---------|------------|
| Concurrent Users | 10-50 | 100-500 | 1000-5000 |
| Requests per Second | 10-100 | 100-1000 | 1000-10000 |
| WebSocket Connections | 10-100 | 100-1000 | 1000-10000 |
| Auto-scaling Response | < 2 minutes | < 1 minute | < 30 seconds |

## Troubleshooting

### Common Issues

1. **Connection Refused Errors**:
   - Check if services are running
   - Verify network connectivity
   - Check firewall settings

2. **High Error Rates**:
   - Review application logs
   - Check resource limits
   - Verify auto-scaling configuration

3. **Poor Performance**:
   - Monitor system resources
   - Check database connection pooling
   - Review load balancing distribution

### Debug Mode

Run tests in debug mode for detailed output:

```bash
k6 run --http-debug scenarios/load-test.js
```

### Logging and Monitoring

Enable comprehensive logging:

```bash
K6_LOG_OUTPUT=stdout K6_LOG_FORMAT=json k6 run scenarios/load-test.js
```

## Best Practices

1. **Test Environment Isolation**: Use dedicated test environments
2. **Realistic Data**: Use production-like data volumes and patterns
3. **Gradual Ramp-up**: Avoid sudden load spikes in normal testing
4. **Consistent Baselines**: Establish and maintain performance baselines
5. **Regular Testing**: Run tests regularly to catch performance regressions
6. **Comprehensive Coverage**: Test all critical user workflows
7. **Monitor During Tests**: Watch system metrics during test execution
8. **Post-Test Analysis**: Analyze results and system behavior thoroughly

## Contributing

When adding new test scenarios:

1. Follow the existing code structure and patterns
2. Include comprehensive comments and documentation
3. Add appropriate thresholds and validations
4. Test scenarios in development environment first
5. Update this README with new scenario descriptions