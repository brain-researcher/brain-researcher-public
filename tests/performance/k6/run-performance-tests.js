/**
 * Brain Researcher Performance Test Suite Runner
 *
 * This script orchestrates all performance tests and generates comprehensive reports
 * comparing results across different load scenarios.
 */

import { check, group } from 'k6';
import { htmlReport } from 'https://raw.githubusercontent.com/benc-uk/k6-reporter/main/dist/bundle.js';
import { textSummary } from 'https://jslib.k6.io/k6-summary/0.0.1/index.js';
import exec from 'k6/execution';

// Test scenario selection based on environment variable
const TEST_SCENARIO = __ENV.TEST_SCENARIO || 'smoke';

// Import configurations
import { CONFIG, SMOKE_PROFILE, LOAD_PROFILE, STRESS_PROFILE, SPIKE_PROFILE, SOAK_PROFILE } from './config/k6.config.js';
import {
  OrchestratorAPI,
  BRKGAPI,
  AgentAPI,
  TestDataGenerator,
  makeRequest,
  checkPerformanceBenchmarks
} from './scripts/utils.js';

// Configure test options based on scenario
const testConfigurations = {
  smoke: {
    ...SMOKE_PROFILE,
    thresholds: {
      'http_req_duration': ['p(95)<1000'],
      'http_req_failed': ['rate<0.01'],
      'http_reqs': ['rate>10']
    }
  },
  load: {
    ...LOAD_PROFILE,
    thresholds: CONFIG.THRESHOLDS
  },
  stress: {
    ...STRESS_PROFILE,
    thresholds: {
      'http_req_duration': ['p(95)<5000'],
      'http_req_failed': ['rate<0.15']
    }
  },
  spike: {
    ...SPIKE_PROFILE,
    thresholds: {
      'http_req_duration': ['p(95)<8000'],
      'http_req_failed': ['rate<0.25']
    }
  },
  soak: {
    ...SOAK_PROFILE,
    thresholds: {
      'http_req_duration': ['p(95)<3000'],
      'http_req_failed': ['rate<0.02'],
      'memory_usage_trend': ['trend<5']
    }
  }
};

export let options = {
  ...testConfigurations[TEST_SCENARIO],
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  summaryTimeUnit: 'ms',
};

// Initialize service clients
const orchestrator = new OrchestratorAPI();
const brKg = new BRKGAPI();
const agent = new AgentAPI();

// Test execution tracker
let testTracker = {
  scenario: TEST_SCENARIO,
  startTime: null,
  services: {
    orchestrator: { available: false, responseTime: 0 },
    brKg: { available: false, responseTime: 0 },
    agent: { available: false, responseTime: 0 }
  },
  testResults: {
    totalRequests: 0,
    successfulRequests: 0,
    failedRequests: 0,
    scenarios: {}
  }
};

export function setup() {
  console.log(`Starting ${TEST_SCENARIO.toUpperCase()} performance test...`);
  testTracker.startTime = Date.now();

  // Comprehensive service availability check
  console.log('Checking service availability...');

  const services = [
    { name: 'orchestrator', client: orchestrator, url: CONFIG.ORCHESTRATOR_URL },
    { name: 'brKg', client: brKg, url: CONFIG.BR_KG_URL },
    { name: 'agent', client: agent, url: CONFIG.AGENT_URL }
  ];

  for (const service of services) {
    try {
      const startTime = Date.now();
      const isHealthy = service.client.healthCheck();
      const responseTime = Date.now() - startTime;

      testTracker.services[service.name] = {
        available: isHealthy,
        responseTime: responseTime,
        url: service.url
      };

      console.log(`${service.name}: ${isHealthy ? '✅ Available' : '❌ Unavailable'} (${responseTime}ms)`);
    } catch (error) {
      console.log(`${service.name}: ❌ Error - ${error.message}`);
      testTracker.services[service.name] = {
        available: false,
        responseTime: 0,
        error: error.message
      };
    }
  }

  // Verify minimum service requirements
  const availableServices = Object.values(testTracker.services).filter(s => s.available).length;
  if (availableServices < 2) {
    throw new Error(`Insufficient services available (${availableServices}/3). Cannot proceed with performance testing.`);
  }

  console.log(`Performance test setup complete. Running ${TEST_SCENARIO} scenario...`);

  return {
    setupTime: Date.now(),
    testScenario: TEST_SCENARIO,
    serviceStatus: testTracker.services
  };
}

export default function(data) {
  // Execute different test patterns based on scenario
  switch (TEST_SCENARIO) {
    case 'smoke':
      runSmokeTestScenario();
      break;
    case 'load':
      runLoadTestScenario();
      break;
    case 'stress':
      runStressTestScenario();
      break;
    case 'spike':
      runSpikeTestScenario();
      break;
    case 'soak':
      runSoakTestScenario();
      break;
    default:
      runDefaultScenario();
  }

  testTracker.testResults.totalRequests++;
}

function runSmokeTestScenario() {
  group('Smoke Test - Basic Functionality', () => {
    // Test each service with minimal load
    const orchestratorResult = orchestrator.healthCheck();
    if (orchestratorResult) testTracker.testResults.successfulRequests++;
    else testTracker.testResults.failedRequests++;

    const brKgResult = brKg.executeGraphQLQuery('query { datasets(limit: 1) { id } }');
    if (brKgResult) testTracker.testResults.successfulRequests++;
    else testTracker.testResults.failedRequests++;

    const agentResult = agent.listTools();
    if (agentResult) testTracker.testResults.successfulRequests++;
    else testTracker.testResults.failedRequests++;
  });
}

function runLoadTestScenario() {
  group('Load Test - Normal Production Load', () => {
    const userBehavior = Math.random();

    if (userBehavior < 0.5) {
      // Web UI user workflow
      orchestrator.listDatasets();
      const query = TestDataGenerator.generateFMRIQuery();
      orchestrator.createRun(query, 'glm', 'ds000001');
      testTracker.testResults.successfulRequests += 2;
    } else {
      // API user workflow
      brKg.executeGraphQLQuery(TestDataGenerator.generateComplexGraphQLQuery(), {
        limit: 10,
        taskType: 'working_memory'
      });
      brKg.executeSearch('brain activation', ['Study'], 20);
      testTracker.testResults.successfulRequests += 2;
    }
  });
}

function runStressTestScenario() {
  group('Stress Test - Beyond Normal Capacity', () => {
    // Aggressive concurrent operations
    const operations = [
      () => orchestrator.createRun(
        'Complex neuroimaging analysis with statistical maps',
        'connectivity',
        'ds000114'
      ),
      () => brKg.executeGraphQLQuery(
        TestDataGenerator.generateComplexGraphQLQuery(),
        { limit: 100, taskType: 'emotion' }
      ),
      () => agent.executeQuery(
        'Execute comprehensive meta-analysis across all available datasets',
        `stress_user_${__VU}`,
        { priority: 'high', timeout: 120 }
      )
    ];

    // Execute all operations simultaneously
    operations.forEach(op => {
      try {
        op();
        testTracker.testResults.successfulRequests++;
      } catch (error) {
        testTracker.testResults.failedRequests++;
      }
    });
  });
}

function runSpikeTestScenario() {
  group('Spike Test - Sudden Load Increases', () => {
    const currentPhase = getCurrentSpikePhase();

    if (currentPhase === 'spike') {
      // Rapid fire requests during spike
      for (let i = 0; i < 3; i++) {
        setTimeout(() => {
          orchestrator.createRun(
            'Rapid analysis request during spike',
            'meta_analysis',
            'motor-task-sample'
          );
          testTracker.testResults.successfulRequests++;
        }, i * 100);
      }
    } else {
      // Normal operations during non-spike phases
      orchestrator.listDatasets();
      brKg.executeGraphQLQuery('query { studies(limit: 5) { id title } }');
      testTracker.testResults.successfulRequests += 2;
    }
  });
}

function runSoakTestScenario() {
  group('Soak Test - Extended Duration Stability', () => {
    // Steady, consistent operations over long duration
    const operations = [
      'data_exploration',
      'analysis_execution',
      'search_operations',
      'mixed_workflow'
    ];

    const operation = operations[__ITER % operations.length];

    switch (operation) {
      case 'data_exploration':
        orchestrator.listDatasets('neuroimaging studies');
        brKg.searchDatasets('fMRI motor task', 10);
        testTracker.testResults.successfulRequests += 2;
        break;

      case 'analysis_execution':
        const analysisQuery = TestDataGenerator.generateFMRIQuery();
        orchestrator.createRun(analysisQuery, 'glm', 'ds000001');
        testTracker.testResults.successfulRequests++;
        break;

      case 'search_operations':
        brKg.executeSearch('working memory activation', ['Study'], 15);
        brKg.executeSPARQLQuery(TestDataGenerator.generateSPARQLQuery());
        testTracker.testResults.successfulRequests += 2;
        break;

      case 'mixed_workflow':
        agent.executeQuery(
          'Analyze brain connectivity in attention networks',
          `soak_user_${__VU}`,
          { analysis_type: 'connectivity' }
        );
        testTracker.testResults.successfulRequests++;
        break;
    }
  });
}

function runDefaultScenario() {
  group('Default Test Scenario', () => {
    // Basic multi-service test
    orchestrator.healthCheck();
    brKg.executeGraphQLQuery('query { datasets(limit: 3) { id name } }');
    agent.listTools();
    testTracker.testResults.successfulRequests += 3;
  });
}

function getCurrentSpikePhase() {
  const elapsed = Date.now() - (testTracker.startTime || Date.now());
  const phase = Math.floor(elapsed / 60000) % 4;

  return ['normal', 'spike', 'normal', 'spike'][phase] || 'normal';
}

export function teardown(data) {
  const totalDuration = (Date.now() - testTracker.startTime) / 1000;
  console.log(`${TEST_SCENARIO.toUpperCase()} test completed in ${totalDuration.toFixed(2)}s`);

  // Final service health check
  console.log('Post-test service health check...');
  Object.keys(testTracker.services).forEach(serviceName => {
    try {
      const client = serviceName === 'orchestrator' ? orchestrator :
                    serviceName === 'brKg' ? brKg : agent;
      const isHealthy = client.healthCheck();
      console.log(`${serviceName}: ${isHealthy ? '✅ Healthy' : '❌ Unhealthy'}`);
    } catch (error) {
      console.log(`${serviceName}: ❌ Error - ${error.message}`);
    }
  });

  return { testTracker };
}

export function handleSummary(data) {
  const timestamp = new Date().toISOString().replace(/[:.]/g, '-');
  const scenarioName = TEST_SCENARIO.toLowerCase();

  return {
    [`reports/${scenarioName}_test_${timestamp}.json`]: JSON.stringify({
      ...data,
      testTracker: testTracker,
      testConfiguration: {
        scenario: TEST_SCENARIO,
        options: options,
        timestamp: timestamp
      }
    }, null, 2),

    [`reports/${scenarioName}_test_${timestamp}.html`]: generateMasterReport(data),

    [`reports/${scenarioName}_summary_${timestamp}.txt`]: generateTextSummary(data),

    stdout: textSummary(data, { indent: ' ', enableColors: true }) + generateConsoleSummary(data)
  };
}

function generateMasterReport(data) {
  const timestamp = new Date().toISOString();
  const duration = data.state.testRunDurationMs / 1000;
  const totalRequests = data.metrics.http_reqs?.values?.count || 0;
  const errorRate = data.metrics.http_req_failed?.values?.rate || 0;
  const avgResponse = data.metrics.http_req_duration?.values?.avg || 0;
  const p95Response = data.metrics.http_req_duration?.values?.['p(95)'] || 0;

  const scenarioConfig = testConfigurations[TEST_SCENARIO];
  const scenarioTitle = TEST_SCENARIO.charAt(0).toUpperCase() + TEST_SCENARIO.slice(1);

  return `
<!DOCTYPE html>
<html>
<head>
    <title>Brain Researcher ${scenarioTitle} Test Report</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 20px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; }
        .container { max-width: 1200px; margin: 0 auto; background: white; border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,0.2); overflow: hidden; }
        .header { background: linear-gradient(135deg, #667eea, #764ba2); color: white; padding: 30px; text-align: center; }
        .header h1 { margin: 0; font-size: 2.5em; font-weight: 300; }
        .header p { margin: 10px 0 0; opacity: 0.9; font-size: 1.1em; }
        .scenario-badge { background: rgba(255,255,255,0.2); padding: 8px 16px; border-radius: 20px; display: inline-block; margin: 10px 0; font-weight: 500; }
        .dashboard { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); gap: 20px; padding: 30px; }
        .metric-card { background: white; padding: 25px; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.1); border-left: 4px solid #667eea; }
        .metric-value { font-size: 2.5em; font-weight: bold; color: #333; margin: 10px 0; }
        .metric-label { color: #666; text-transform: uppercase; font-size: 0.9em; letter-spacing: 1px; }
        .metric-trend { font-size: 0.9em; margin-top: 8px; }
        .trend-positive { color: #28a745; }
        .trend-negative { color: #dc3545; }
        .trend-neutral { color: #6c757d; }
        .service-status { padding: 30px; background: #f8f9fa; }
        .service-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; margin-top: 20px; }
        .service-card { background: white; padding: 20px; border-radius: 8px; border-left: 4px solid #28a745; }
        .service-unavailable { border-left-color: #dc3545; }
        .threshold-results { padding: 30px; }
        .threshold-item { display: flex; justify-content: between; align-items: center; padding: 10px 0; border-bottom: 1px solid #eee; }
        .threshold-pass { color: #28a745; }
        .threshold-fail { color: #dc3545; }
        .recommendations { padding: 30px; background: #e7f3ff; }
        .recommendation { background: white; padding: 15px; margin: 10px 0; border-left: 4px solid #17a2b8; border-radius: 4px; }
        .chart-placeholder { background: linear-gradient(45deg, #f8f9fa, #e9ecef); padding: 60px; text-align: center; margin: 20px 0; border-radius: 8px; color: #6c757d; font-size: 1.2em; }
        .details-section { padding: 30px; background: #f8f9fa; }
        .collapsible { background: white; border-radius: 8px; margin: 15px 0; overflow: hidden; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
        .collapsible summary { padding: 20px; cursor: pointer; background: #667eea; color: white; font-weight: 500; }
        .collapsible-content { padding: 20px; }
        pre { background: #f8f9fa; padding: 20px; border-radius: 6px; overflow-x: auto; font-size: 0.9em; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🧠 Brain Researcher Performance Test</h1>
            <div class="scenario-badge">${scenarioTitle} Test Scenario</div>
            <p>Generated: ${timestamp}</p>
            <p>Duration: ${duration.toFixed(2)} seconds</p>
        </div>

        <div class="dashboard">
            <div class="metric-card">
                <div class="metric-label">Total Requests</div>
                <div class="metric-value">${totalRequests.toLocaleString()}</div>
                <div class="metric-trend trend-neutral">Across all services</div>
            </div>

            <div class="metric-card">
                <div class="metric-label">Success Rate</div>
                <div class="metric-value">${((1 - errorRate) * 100).toFixed(2)}%</div>
                <div class="metric-trend ${errorRate < 0.05 ? 'trend-positive' : errorRate < 0.15 ? 'trend-neutral' : 'trend-negative'}">
                    ${errorRate < 0.05 ? '✅ Excellent' : errorRate < 0.15 ? '⚠️ Acceptable' : '❌ Needs Attention'}
                </div>
            </div>

            <div class="metric-card">
                <div class="metric-label">Avg Response Time</div>
                <div class="metric-value">${avgResponse.toFixed(0)}ms</div>
                <div class="metric-trend ${avgResponse < 1000 ? 'trend-positive' : avgResponse < 3000 ? 'trend-neutral' : 'trend-negative'}">
                    ${avgResponse < 1000 ? '⚡ Fast' : avgResponse < 3000 ? '👍 Good' : '🐌 Slow'}
                </div>
            </div>

            <div class="metric-card">
                <div class="metric-label">P95 Response Time</div>
                <div class="metric-value">${p95Response.toFixed(0)}ms</div>
                <div class="metric-trend ${p95Response < 2000 ? 'trend-positive' : p95Response < 5000 ? 'trend-neutral' : 'trend-negative'}">
                    95% under ${(p95Response/1000).toFixed(1)}s
                </div>
            </div>

            <div class="metric-card">
                <div class="metric-label">Throughput</div>
                <div class="metric-value">${(data.metrics.http_reqs?.values?.rate || 0).toFixed(1)}</div>
                <div class="metric-trend trend-neutral">Requests per second</div>
            </div>

            <div class="metric-card">
                <div class="metric-label">Test Scenario</div>
                <div class="metric-value">${scenarioTitle.toUpperCase()}</div>
                <div class="metric-trend trend-neutral">${getScenarioDescription(TEST_SCENARIO)}</div>
            </div>
        </div>

        <div class="service-status">
            <h2>🔧 Service Status</h2>
            <div class="service-grid">
                ${Object.entries(testTracker.services).map(([name, status]) => `
                    <div class="service-card ${status.available ? '' : 'service-unavailable'}">
                        <h3>${name.charAt(0).toUpperCase() + name.slice(1)} Service</h3>
                        <p><strong>Status:</strong> ${status.available ? '✅ Available' : '❌ Unavailable'}</p>
                        <p><strong>Response Time:</strong> ${status.responseTime}ms</p>
                        <p><strong>URL:</strong> <code>${status.url || 'N/A'}</code></p>
                        ${status.error ? `<p><strong>Error:</strong> ${status.error}</p>` : ''}
                    </div>
                `).join('')}
            </div>
        </div>

        <div class="chart-placeholder">
            📊 Performance Metrics Visualization<br>
            <small>Response Time Distribution, Throughput Over Time, Error Rate Timeline</small>
        </div>

        <div class="threshold-results">
            <h2>🎯 Performance Thresholds</h2>
            ${Object.entries(data.metrics).filter(([key, metric]) =>
                metric.thresholds && Object.keys(metric.thresholds).length > 0
            ).map(([key, metric]) =>
                Object.entries(metric.thresholds).map(([threshold, result]) => `
                    <div class="threshold-item">
                        <div>
                            <strong>${key}</strong> ${threshold}
                        </div>
                        <div class="${result.ok ? 'threshold-pass' : 'threshold-fail'}">
                            ${result.ok ? '✅ PASS' : '❌ FAIL'}
                        </div>
                    </div>
                `).join('')
            ).join('')}
        </div>

        <div class="recommendations">
            <h2>💡 Performance Recommendations</h2>
            ${generateRecommendations(data, testTracker).map(rec => `
                <div class="recommendation">${rec}</div>
            `).join('')}
        </div>

        <div class="details-section">
            <h2>📋 Detailed Results</h2>

            <details class="collapsible">
                <summary>Test Configuration</summary>
                <div class="collapsible-content">
                    <pre>${JSON.stringify({
                        scenario: TEST_SCENARIO,
                        options: scenarioConfig,
                        services: testTracker.services
                    }, null, 2)}</pre>
                </div>
            </details>

            <details class="collapsible">
                <summary>Complete Test Data</summary>
                <div class="collapsible-content">
                    <pre>${JSON.stringify(data, null, 2)}</pre>
                </div>
            </details>

            <details class="collapsible">
                <summary>Test Execution Details</summary>
                <div class="collapsible-content">
                    <pre>${JSON.stringify(testTracker, null, 2)}</pre>
                </div>
            </details>
        </div>
    </div>
</body>
</html>
  `;
}

function generateTextSummary(data) {
  const duration = data.state.testRunDurationMs / 1000;
  const totalRequests = data.metrics.http_reqs?.values?.count || 0;
  const errorRate = data.metrics.http_req_failed?.values?.rate || 0;
  const avgResponse = data.metrics.http_req_duration?.values?.avg || 0;
  const p95Response = data.metrics.http_req_duration?.values?.['p(95)'] || 0;

  return `
BRAIN RESEARCHER ${TEST_SCENARIO.toUpperCase()} TEST SUMMARY
=========================================================
Test Scenario: ${TEST_SCENARIO}
Duration: ${duration.toFixed(2)}s
Timestamp: ${new Date().toISOString()}

PERFORMANCE METRICS
------------------
Total Requests: ${totalRequests}
Success Rate: ${((1 - errorRate) * 100).toFixed(2)}%
Average Response Time: ${avgResponse.toFixed(2)}ms
P95 Response Time: ${p95Response.toFixed(2)}ms
Throughput: ${(data.metrics.http_reqs?.values?.rate || 0).toFixed(2)} req/s

SERVICE STATUS
--------------
${Object.entries(testTracker.services).map(([name, status]) =>
  `${name}: ${status.available ? 'Available' : 'Unavailable'} (${status.responseTime}ms)`
).join('\n')}

THRESHOLD RESULTS
-----------------
${Object.entries(data.metrics).filter(([key, metric]) =>
  metric.thresholds && Object.keys(metric.thresholds).length > 0
).map(([key, metric]) =>
  Object.entries(metric.thresholds).map(([threshold, result]) =>
    `${key} ${threshold}: ${result.ok ? 'PASS' : 'FAIL'}`
  ).join('\n')
).join('\n')}

RECOMMENDATIONS
---------------
${generateRecommendations(data, testTracker).join('\n')}
=========================================================
  `;
}

function generateConsoleSummary(data) {
  const duration = data.state.testRunDurationMs / 1000;
  const totalRequests = data.metrics.http_reqs?.values?.count || 0;
  const errorRate = data.metrics.http_req_failed?.values?.rate || 0;
  const throughput = data.metrics.http_reqs?.values?.rate || 0;

  return `

🧠 ===== BRAIN RESEARCHER ${TEST_SCENARIO.toUpperCase()} TEST COMPLETE =====
⏱️  Duration: ${duration.toFixed(2)}s
📊 Requests: ${totalRequests} (${throughput.toFixed(2)} req/s)
✅ Success: ${((1 - errorRate) * 100).toFixed(2)}%
🚀 Performance: ${errorRate < 0.05 ? 'Excellent' : errorRate < 0.15 ? 'Good' : 'Needs Improvement'}

📁 Reports generated in tests/performance/k6/reports/
🌐 View detailed HTML report for complete analysis
===============================================================
`;
}

function getScenarioDescription(scenario) {
  const descriptions = {
    smoke: 'Quick validation test',
    load: 'Normal production load',
    stress: 'Beyond normal capacity',
    spike: 'Sudden load increases',
    soak: 'Extended duration stability'
  };
  return descriptions[scenario] || 'Custom test scenario';
}

function generateRecommendations(data, tracker) {
  const recommendations = [];
  const errorRate = data.metrics.http_req_failed?.values?.rate || 0;
  const avgResponse = data.metrics.http_req_duration?.values?.avg || 0;
  const throughput = data.metrics.http_reqs?.values?.rate || 0;

  // Service-specific recommendations
  const unavailableServices = Object.entries(tracker.services)
    .filter(([_, status]) => !status.available)
    .map(([name, _]) => name);

  if (unavailableServices.length > 0) {
    recommendations.push(`🔧 Address unavailable services: ${unavailableServices.join(', ')}`);
  }

  // Performance recommendations
  if (errorRate > 0.05) {
    recommendations.push('⚠️ High error rate detected - investigate failing endpoints and implement circuit breakers');
  }

  if (avgResponse > 2000) {
    recommendations.push('🐌 Response times are high - consider caching, database optimization, or horizontal scaling');
  }

  if (throughput < 50) {
    recommendations.push('📈 Low throughput detected - review system capacity and bottlenecks');
  }

  // Scenario-specific recommendations
  switch (TEST_SCENARIO) {
    case 'stress':
      if (errorRate > 0.15) {
        recommendations.push('🔥 System struggles under stress - implement graceful degradation mechanisms');
      }
      break;
    case 'spike':
      if (avgResponse > 5000) {
        recommendations.push('⚡ Poor spike handling - consider auto-scaling or load balancing improvements');
      }
      break;
    case 'soak':
      recommendations.push('⏰ Monitor for memory leaks and performance degradation in production');
      break;
  }

  if (recommendations.length === 0) {
    recommendations.push('✅ System performance is within acceptable limits');
    recommendations.push('🚀 Consider testing with higher loads or longer duration');
  }

  return recommendations;
}