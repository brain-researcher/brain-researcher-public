/**
 * Stress Testing Scenario for Brain Researcher Backend Services
 *
 * This test pushes the system beyond normal capacity to identify breaking points
 * and ensure graceful degradation under extreme load.
 */

import { check, group, sleep, fail } from 'k6';
import http from 'k6/http';
import { CONFIG, STRESS_PROFILE, getRandomQuery, getRandomDatasetId } from '../config/k6.config.js';
import {
  OrchestratorAPI,
  BRKGAPI,
  AgentAPI,
  TestDataGenerator,
  errorRate,
  successfulRequests,
  failedRequests,
  requestDuration,
  queryExecutionTime,
  memoryUsage,
  cpuUsage
} from '../scripts/utils.js';

// Stress test configuration - more aggressive thresholds
export let options = {
  stages: STRESS_PROFILE.stages,
  thresholds: {
    // Relaxed thresholds for stress test (expect some degradation)
    'http_req_duration': ['p(50)<1000', 'p(95)<5000', 'p(99)<10000'],
    'http_req_failed': ['rate<0.15'], // Allow up to 15% failure rate under stress
    'http_reqs': ['rate>50'], // Minimum 50 RPS even under stress

    // Service-specific stress thresholds
    'http_req_duration{group:::orchestrator_api}': ['p(95)<3000'],
    'http_req_duration{group:::brKg_api}': ['p(95)<4000'],
    'http_req_duration{group:::agent_api}': ['p(95)<8000'],

    // Resource utilization warnings (not failures)
    'memory_usage': ['value<95'],
    'cpu_usage': ['value<90'],

    // Connection and stability metrics
    'http_req_connecting': ['p(95)<1000'],
    'http_req_waiting': ['p(95)<7000'],
  },
  ext: {
    loadimpact: {
      distribution: {
        'amazon:us:ashburn': { loadZone: 'amazon:us:ashburn', percent: 70 },
        'amazon:us:portland': { loadZone: 'amazon:us:portland', percent: 30 },
      },
    },
  },
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)', 'p(99.9)'],
  summaryTimeUnit: 'ms',
  discardResponseBodies: false, // Keep response bodies for error analysis
};

// Initialize service clients with extended timeouts
const orchestrator = new OrchestratorAPI();
const brKg = new BRKGAPI();
const agent = new AgentAPI();

// Stress test specific data - larger and more complex
const heavyQueries = [
  'Perform comprehensive meta-analysis across all working memory studies with statistical maps',
  'Execute connectivity analysis with whole-brain parcellation and network statistics',
  'Run machine learning classification on high-dimensional neuroimaging features',
  'Generate statistical parametric maps with multiple comparison corrections',
  'Analyze longitudinal changes in brain structure across lifespan datasets'
];

const complexGraphQLQueries = [
  `query HeavyQuery($limit: Int!) {
    studies(limit: $limit) {
      id title pmid authors { name affiliation institution }
      activations { coordinates { x y z } brainRegion { name atlas hierarchyLevel }
        statisticValue threshold pValue correctionMethod }
      contrasts { name condition controlCondition statisticalTest }
      subjects { age gender handedness groupLabel }
      datasets { id name modality scannerType fieldStrength }
      analyses { method software version parameters }
    }
  }`,
  `query NetworkAnalysis {
    brainRegions(hierarchyLevel: "region") {
      name coordinates atlas
      connectedRegions { region strength method }
      studies(limit: 100) { title activationMagnitude }
      functionalNetworks { name components centrality }
    }
  }`
];

let stressMetrics = {
  peakVUs: 0,
  maxErrorRate: 0,
  slowestResponse: 0,
  systemBreakPoint: null,
  recoveryTime: 0
};

export function setup() {
  console.log('Starting stress test setup...');

  // Extended health check with retry logic
  let healthRetries = 0;
  let allHealthy = false;

  while (healthRetries < 3 && !allHealthy) {
    try {
      const orchestratorHealth = orchestrator.healthCheck();
      const brKgHealth = brKg.healthCheck();
      const agentHealth = agent.healthCheck();

      if (orchestratorHealth && brKgHealth && agentHealth) {
        allHealthy = true;
        console.log('All services healthy - proceeding with stress test');
      } else {
        healthRetries++;
        console.log(`Health check failed, retry ${healthRetries}/3`);
        sleep(5);
      }
    } catch (error) {
      healthRetries++;
      console.log(`Health check error: ${error.message}, retry ${healthRetries}/3`);
      sleep(5);
    }
  }

  if (!allHealthy) {
    throw new Error('Services not healthy enough for stress testing');
  }

  return {
    setupTime: Date.now(),
    baselineMetrics: captureBaselineMetrics()
  };
}

export default function(data) {
  const currentStage = getCurrentStage();
  stressMetrics.peakVUs = Math.max(stressMetrics.peakVUs, __VU);

  // Adjust behavior based on current load stage
  if (currentStage === 'ramp_up') {
    runProgressiveLoadScenario();
  } else if (currentStage === 'stress') {
    runHighStressScenario();
  } else if (currentStage === 'peak_stress') {
    runPeakStressScenario();
  } else {
    runRecoveryScenario();
  }

  // Reduce sleep time as stress increases
  const sleepTime = Math.max(0.1, 2 - (__VU / 100));
  sleep(sleepTime);
}

function getCurrentStage() {
  const elapsed = Date.now() - __ENV.TEST_START_TIME;

  if (elapsed < 120000) return 'ramp_up';        // First 2 minutes
  if (elapsed < 420000) return 'stress';         // Next 5 minutes
  if (elapsed < 540000) return 'peak_stress';    // Next 2 minutes
  return 'recovery';                             // Final ramp down
}

function runProgressiveLoadScenario() {
  group('Progressive Load Scenario', () => {
    // Start with basic operations
    orchestrator.healthCheck();
    orchestrator.listDatasets();

    // Add moderate complexity
    const query = getRandomQuery('AGENT');
    orchestrator.createRun(query, 'glm', getRandomDatasetId());

    // Basic BR-KG operations
    brKg.executeGraphQLQuery(CONFIG.TEST_DATA.BR_KG_QUERIES[0]);
    brKg.executeSearch('brain activation', ['Study'], 10);
  });
}

function runHighStressScenario() {
  group('High Stress Scenario', () => {
    // Multiple concurrent operations
    Promise.all([
      // Heavy Orchestrator usage
      group('Orchestrator Stress', () => {
        orchestrator.listDatasets('complex query with filters');
        orchestrator.createRun(heavyQueries[Math.floor(Math.random() * heavyQueries.length)],
                              'connectivity', getRandomDatasetId());
      }),

      // Complex BR-KG queries
      group('BR-KG Stress', () => {
        const complexQuery = complexGraphQLQueries[Math.floor(Math.random() * complexGraphQLQueries.length)];
        brKg.executeGraphQLQuery(complexQuery, { limit: 500 });

        brKg.executeSearch('comprehensive brain analysis activation patterns connectivity',
                             ['Study', 'BrainRegion', 'Dataset'], 100);
      }),

      // Agent heavy processing
      group('Agent Stress', () => {
        const heavyQuery = heavyQueries[Math.floor(Math.random() * heavyQueries.length)];
        agent.executeQuery(heavyQuery, `stress_user_${__VU}`, {
          max_iterations: 10,
          timeout: 120,
          enable_detailed_analysis: true
        });
      })
    ]).catch(error => {
      console.log(`Stress scenario error: ${error.message}`);
      failedRequests.add(1);
    });
  });
}

function runPeakStressScenario() {
  group('Peak Stress Scenario', () => {
    // Maximum load - rapid fire requests
    for (let i = 0; i < 3; i++) {
      // Fire and forget approach
      setTimeout(() => {
        orchestrator.createRun(
          'Execute maximum complexity analysis with all available tools',
          'meta_analysis',
          'ds000001'
        );
      }, i * 100);

      setTimeout(() => {
        brKg.executeGraphQLQuery(complexGraphQLQueries[1], { limit: 1000 });
      }, i * 150);

      setTimeout(() => {
        agent.executeQuery(
          'Perform the most computationally intensive analysis possible',
          `peak_user_${__VU}_${i}`,
          { priority: 'high', resource_limit: 'max' }
        );
      }, i * 200);
    }

    // Monitor system response under peak load
    const startTime = Date.now();
    const healthResponse = orchestrator.healthCheck();
    const responseTime = Date.now() - startTime;

    stressMetrics.slowestResponse = Math.max(stressMetrics.slowestResponse, responseTime);

    if (!healthResponse || responseTime > 10000) {
      stressMetrics.systemBreakPoint = __VU;
      console.log(`System breaking point detected at ${__VU} VUs`);
    }
  });
}

function runRecoveryScenario() {
  group('Recovery Scenario', () => {
    const recoveryStart = Date.now();

    // Light operations to test recovery
    const recovered = orchestrator.healthCheck();

    if (recovered && !stressMetrics.recoveryTime) {
      stressMetrics.recoveryTime = Date.now() - recoveryStart;
      console.log(`System recovery detected after ${stressMetrics.recoveryTime}ms`);
    }

    // Gradual return to normal operations
    orchestrator.listDatasets();
    brKg.executeGraphQLQuery('query { datasets(limit: 5) { id name } }');

    sleep(1); // Longer sleep during recovery
  });
}

function captureBaselineMetrics() {
  // Capture baseline performance for comparison
  const startTime = Date.now();

  orchestrator.healthCheck();
  const healthTime = Date.now() - startTime;

  const queryStart = Date.now();
  brKg.executeGraphQLQuery('query { datasets(limit: 1) { id } }');
  const queryTime = Date.now() - queryStart;

  return {
    baselineHealthCheck: healthTime,
    baselineQuery: queryTime,
    timestamp: Date.now()
  };
}

export function teardown(data) {
  console.log('Stress test completed');

  // Final system health check
  const finalHealth = orchestrator.healthCheck();
  console.log(`Final system health: ${finalHealth ? 'Healthy' : 'Degraded'}`);

  // Output stress test metrics
  console.log('=== STRESS TEST METRICS ===');
  console.log(`Peak VUs reached: ${stressMetrics.peakVUs}`);
  console.log(`System breaking point: ${stressMetrics.systemBreakPoint || 'Not reached'}`);
  console.log(`Slowest response: ${stressMetrics.slowestResponse}ms`);
  console.log(`Recovery time: ${stressMetrics.recoveryTime || 'Not measured'}ms`);
}

export function handleSummary(data) {
  const summary = {
    'stress_test_summary.json': JSON.stringify({
      ...data,
      stressMetrics: stressMetrics
    }, null, 2),
    'stress_test_summary.html': generateStressTestReport(data),
    stdout: generateStressTestConsoleReport(data)
  };

  return summary;
}

function generateStressTestConsoleReport(data) {
  const duration = data.state.testRunDurationMs / 1000;
  const totalRequests = data.metrics.http_reqs.values.count;
  const errorRate = data.metrics.http_req_failed.values.rate;
  const p99Response = data.metrics.http_req_duration.values['p(99)'];

  return `
=== STRESS TEST SUMMARY ===
Test Duration: ${duration.toFixed(2)}s
Peak Virtual Users: ${stressMetrics.peakVUs}
Total Requests: ${totalRequests}

Performance Under Stress:
- Success Rate: ${((1 - errorRate) * 100).toFixed(2)}%
- P99 Response Time: ${p99Response.toFixed(2)}ms
- Requests per Second: ${data.metrics.http_reqs.values.rate.toFixed(2)}

Stress Test Findings:
- Breaking Point: ${stressMetrics.systemBreakPoint || 'Not reached'} VUs
- Slowest Response: ${stressMetrics.slowestResponse}ms
- Recovery Time: ${stressMetrics.recoveryTime || 'N/A'}ms

System Resilience:
${errorRate < 0.15 ? '✅ System handled stress well' : '⚠️ High error rate under stress'}
${p99Response < 10000 ? '✅ Response times acceptable' : '⚠️ Severe response time degradation'}
${stressMetrics.systemBreakPoint ? '⚠️ System breaking point identified' : '✅ No breaking point reached'}

Recommendations:
${generateStressTestRecommendations(data, stressMetrics)}
========================
  `;
}

function generateStressTestRecommendations(data, stressMetrics) {
  const recommendations = [];

  if (data.metrics.http_req_failed.values.rate > 0.1) {
    recommendations.push('- Consider implementing circuit breakers for graceful degradation');
  }

  if (data.metrics.http_req_duration.values['p(99)'] > 5000) {
    recommendations.push('- Optimize slow endpoints or add response caching');
  }

  if (stressMetrics.systemBreakPoint && stressMetrics.systemBreakPoint < 100) {
    recommendations.push('- Scale infrastructure to handle higher concurrent loads');
  }

  if (stressMetrics.recoveryTime > 30000) {
    recommendations.push('- Improve system recovery mechanisms');
  }

  if (data.metrics.http_reqs.values.rate < 50) {
    recommendations.push('- Investigate throughput bottlenecks');
  }

  if (recommendations.length === 0) {
    recommendations.push('- System performed well under stress testing');
    recommendations.push('- Consider testing with higher loads to find limits');
  }

  return recommendations.join('\n');
}

function generateStressTestReport(data) {
  const timestamp = new Date().toISOString();
  const duration = data.state.testRunDurationMs / 1000;

  return `
<!DOCTYPE html>
<html>
<head>
    <title>Brain Researcher Stress Test Report</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background-color: #f8f9fa; }
        .header { background: linear-gradient(135deg, #dc3545, #c82333); color: white; padding: 20px; border-radius: 5px; }
        .warning { background: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 15px 0; }
        .success { background: #d4edda; border: 1px solid #c3e6cb; padding: 15px; border-radius: 5px; margin: 15px 0; }
        .metric-group { background: white; margin: 20px 0; padding: 20px; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .metric { padding: 10px; margin: 5px 0; border-left: 4px solid #007cba; background: #f8f9fa; }
        .critical { border-left-color: #dc3545; background: #f8d7da; }
        .warning-metric { border-left-color: #ffc107; background: #fff3cd; }
        .good { border-left-color: #28a745; background: #d4edda; }
        .summary-table { width: 100%; border-collapse: collapse; margin: 20px 0; }
        .summary-table th, .summary-table td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
        .summary-table th { background-color: #343a40; color: white; }
        .chart-placeholder { background: #e9ecef; padding: 40px; text-align: center; margin: 20px 0; border-radius: 5px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🔥 Brain Researcher Stress Test Report</h1>
        <p><strong>Generated:</strong> ${timestamp}</p>
        <p><strong>Duration:</strong> ${duration.toFixed(2)} seconds</p>
        <p><strong>Peak Load:</strong> ${stressMetrics.peakVUs} Virtual Users</p>
    </div>

    ${data.metrics.http_req_failed.values.rate > 0.1 ?
      '<div class="warning">⚠️ <strong>High Error Rate Detected:</strong> System experienced significant stress during peak load phases.</div>' :
      '<div class="success">✅ <strong>Stress Test Passed:</strong> System maintained acceptable performance under stress.</div>'
    }

    <div class="metric-group">
        <h2>🎯 Stress Test Objectives Met</h2>
        <div class="metric ${data.metrics.http_req_failed.values.rate < 0.15 ? 'good' : 'critical'}">
            <strong>Error Rate Tolerance:</strong> ${(data.metrics.http_req_failed.values.rate * 100).toFixed(2)}% (Target: <15%)
        </div>
        <div class="metric ${data.metrics.http_req_duration.values['p(99)'] < 10000 ? 'good' : 'warning-metric'}">
            <strong>P99 Response Time:</strong> ${data.metrics.http_req_duration.values['p(99)'].toFixed(2)}ms (Target: <10s)
        </div>
        <div class="metric ${stressMetrics.systemBreakPoint ? 'warning-metric' : 'good'}">
            <strong>Breaking Point:</strong> ${stressMetrics.systemBreakPoint || 'Not reached'} VUs
        </div>
    </div>

    <div class="metric-group">
        <h2>📊 Performance Under Stress</h2>
        <table class="summary-table">
            <tr><th>Metric</th><th>Value</th><th>Status</th></tr>
            <tr><td>Total Requests</td><td>${data.metrics.http_reqs.values.count}</td><td>-</td></tr>
            <tr><td>Success Rate</td><td>${((1 - data.metrics.http_req_failed.values.rate) * 100).toFixed(2)}%</td>
                <td>${data.metrics.http_req_failed.values.rate < 0.15 ? '✅ Good' : '⚠️ High Errors'}</td></tr>
            <tr><td>Peak RPS</td><td>${data.metrics.http_reqs.values.rate.toFixed(2)}</td>
                <td>${data.metrics.http_reqs.values.rate > 50 ? '✅ Good' : '⚠️ Low Throughput'}</td></tr>
            <tr><td>Avg Response Time</td><td>${data.metrics.http_req_duration.values.avg.toFixed(2)}ms</td><td>-</td></tr>
            <tr><td>P95 Response Time</td><td>${data.metrics.http_req_duration.values['p(95)'].toFixed(2)}ms</td>
                <td>${data.metrics.http_req_duration.values['p(95)'] < 5000 ? '✅ Good' : '⚠️ Slow'}</td></tr>
            <tr><td>P99 Response Time</td><td>${data.metrics.http_req_duration.values['p(99)'].toFixed(2)}ms</td>
                <td>${data.metrics.http_req_duration.values['p(99)'] < 10000 ? '✅ Good' : '⚠️ Very Slow'}</td></tr>
        </table>
    </div>

    <div class="metric-group">
        <h2>🔍 Stress Analysis Findings</h2>
        <div class="metric">
            <strong>Peak Virtual Users:</strong> ${stressMetrics.peakVUs}
        </div>
        <div class="metric">
            <strong>System Breaking Point:</strong> ${stressMetrics.systemBreakPoint || 'Not reached during test'}
        </div>
        <div class="metric">
            <strong>Slowest Response Recorded:</strong> ${stressMetrics.slowestResponse}ms
        </div>
        <div class="metric">
            <strong>Recovery Time:</strong> ${stressMetrics.recoveryTime || 'Not measured'}ms
        </div>
    </div>

    <div class="chart-placeholder">
        📈 Load Profile Chart<br>
        <small>Stages: Ramp-up (2m) → Stress Load (5m) → Peak Stress (2m) → Recovery (2m)</small>
    </div>

    <div class="metric-group">
        <h2>💡 Recommendations</h2>
        ${generateStressTestRecommendations(data, stressMetrics).split('\n').map(rec =>
          rec.trim() ? `<div class="metric">${rec}</div>` : ''
        ).join('')}
    </div>

    <div class="metric-group">
        <h2>📋 Detailed Metrics</h2>
        <details>
            <summary>Click to view raw test data</summary>
            <pre style="background: #f8f9fa; padding: 20px; border-radius: 5px; overflow-x: auto;">${JSON.stringify({...data, stressMetrics}, null, 2)}</pre>
        </details>
    </div>
</body>
</html>
  `;
}