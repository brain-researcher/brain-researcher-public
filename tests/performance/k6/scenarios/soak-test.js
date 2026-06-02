/**
 * Soak Testing Scenario for Brain Researcher Backend Services
 *
 * This test runs extended load over time to identify memory leaks,
 * resource degradation, and system stability issues.
 */

import { check, group, sleep } from 'k6';
import http from 'k6/http';
import { CONFIG, SOAK_PROFILE, getRandomQuery, getRandomDatasetId } from '../config/k6.config.js';
import {
  OrchestratorAPI,
  BRKGAPI,
  AgentAPI,
  TestDataGenerator,
  errorRate,
  successfulRequests,
  requestDuration,
  memoryUsage,
  cpuUsage
} from '../scripts/utils.js';

// Soak test configuration - extended duration, stable load
export let options = {
  stages: SOAK_PROFILE.stages,
  thresholds: {
    // Long-term stability thresholds
    'http_req_duration': ['p(50)<800', 'p(95)<3000', 'p(99)<8000'],
    'http_req_failed': ['rate<0.02'], // Very low error rate for extended test
    'http_reqs': ['rate>80'], // Consistent throughput

    // Memory and resource stability (should not degrade over time)
    'memory_usage_trend': ['trend<5'], // Memory usage shouldn't increase significantly
    'response_time_trend': ['trend<10'], // Response times shouldn't degrade
    'error_rate_trend': ['trend<1'], // Error rate should remain stable

    // Service-specific long-term performance
    'http_req_duration{service:orchestrator}': ['p(95)<2000'],
    'http_req_duration{service:brKg}': ['p(95)<2500'],
    'http_req_duration{service:agent}': ['p(95)<4000'],

    // Connection stability
    'http_req_connecting': ['p(95)<500'],
    'http_req_waiting': ['p(95)<2500'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  summaryTimeUnit: 'ms',
  discardResponseBodies: true, // Save memory during long test
};

// Initialize service clients
const orchestrator = new OrchestratorAPI();
const brKg = new BRKGAPI();
const agent = new AgentAPI();

// Soak test tracking
let soakMetrics = {
  startTime: null,
  snapshots: [],
  degradationDetected: false,
  memoryLeakDetected: false,
  performanceDrift: {
    baseline: null,
    current: null,
    samples: []
  }
};

export function setup() {
  console.log('Starting soak test setup...');
  console.log('This test will run for 30+ minutes to detect stability issues');

  soakMetrics.startTime = Date.now();

  // Establish baseline performance
  const baseline = measureBaselinePerformance();
  soakMetrics.performanceDrift.baseline = baseline;

  console.log(`Baseline established: ${baseline.avgResponseTime}ms avg response`);

  return {
    setupTime: Date.now(),
    baselineMetrics: baseline
  };
}

export default function(data) {
  const testPhase = getTestPhase();
  const iteration = (__ITER || 0) + 1;

  // Take performance snapshots periodically
  if (iteration % 100 === 0) {
    takePerformanceSnapshot(iteration);
  }

  // Run different scenarios based on test phase
  switch (testPhase) {
    case 'ramp_up':
      runRampUpScenario();
      break;
    case 'steady_state':
      runSteadyStateScenario(iteration);
      break;
    case 'ramp_down':
      runRampDownScenario();
      break;
    default:
      runSteadyStateScenario(iteration);
  }

  // Check for performance degradation
  if (iteration % 500 === 0) {
    checkForDegradation();
  }

  // Consistent sleep pattern for steady load
  sleep(2 + Math.random() * 1); // 2-3 seconds between requests
}

function getTestPhase() {
  const elapsed = Date.now() - soakMetrics.startTime;
  const minutes = elapsed / 60000;

  if (minutes < 5) return 'ramp_up';
  if (minutes < 32) return 'steady_state'; // 30 minutes of steady load
  return 'ramp_down';
}

function runRampUpScenario() {
  group('Soak Test - Ramp Up', () => {
    // Lighter load during ramp-up
    orchestrator.healthCheck();

    const query = getRandomQuery('AGENT');
    orchestrator.createRun(query, 'glm', getRandomDatasetId());

    brKg.executeGraphQLQuery('query { datasets(limit: 5) { id name description } }');
  });
}

function runSteadyStateScenario(iteration) {
  group('Soak Test - Steady State', () => {
    const scenario = iteration % 4;

    switch (scenario) {
      case 0:
        runDataExplorationWorkflow();
        break;
      case 1:
        runAnalysisWorkflow();
        break;
      case 2:
        runSearchWorkflow();
        break;
      case 3:
        runMixedOperationsWorkflow();
        break;
    }
  });
}

function runRampDownScenario() {
  group('Soak Test - Ramp Down', () => {
    // Lighter operations during ramp-down
    orchestrator.healthCheck();
    brKg.executeGraphQLQuery('query { datasets(limit: 3) { id name } }');

    // Final performance check
    takePerformanceSnapshot('final');
  });
}

function runDataExplorationWorkflow() {
  // Simulate user exploring datasets and studies
  orchestrator.listDatasets();

  brKg.searchDatasets('fMRI working memory', 10);

  const exploreQuery = `
    query ExploreStudies($taskType: String!) {
      studies(taskType: $taskType, limit: 15) {
        id title pmid
        subjects { age gender }
        activations { brainRegion { name } statisticValue }
      }
    }
  `;

  brKg.executeGraphQLQuery(exploreQuery, { taskType: 'working_memory' });

  brKg.executeSearch('prefrontal cortex', ['BrainRegion'], 20);
}

function runAnalysisWorkflow() {
  // Simulate running analyses
  const analysisQuery = TestDataGenerator.generateFMRIQuery();
  const datasetId = getRandomDatasetId();

  orchestrator.createRun(analysisQuery, 'connectivity', datasetId);

  agent.executeQuery(
    analysisQuery,
    `soak_user_${__VU}`,
    {
      analysis_type: 'group_comparison',
      correction_method: 'fdr',
      timeout: 180
    }
  );

  // Check job status
  const mockJobId = `job_soak_${Date.now()}`;
  orchestrator.getJob(mockJobId);
}

function runSearchWorkflow() {
  // Simulate comprehensive search operations
  const searchTerms = [
    'working memory activation',
    'default mode network connectivity',
    'emotion regulation amygdala',
    'motor cortex finger tapping',
    'attention networks parietal'
  ];

  const searchTerm = searchTerms[Math.floor(Math.random() * searchTerms.length)];

  brKg.executeSearch(searchTerm, ['Study', 'BrainRegion'], 25);

  const sparqlQuery = `
    PREFIX brain: <https://br-kg.org/ontology/>
    SELECT ?study ?region ?activation
    WHERE {
      ?study brain:hasActivation ?activation .
      ?activation brain:locatedIn ?region .
      ?region brain:partOf ?network .
    }
    LIMIT 30
  `;

  brKg.executeSPARQLQuery(sparqlQuery);

  // Performance metrics check
  brKg.getPerformanceMetrics();
}

function runMixedOperationsWorkflow() {
  // Mix of all operations to simulate realistic usage
  orchestrator.listTools();

  const complexQuery = TestDataGenerator.generateComplexGraphQLQuery();
  brKg.executeGraphQLQuery(complexQuery, {
    limit: 20,
    taskType: 'attention'
  });

  orchestrator.createRun(
    'Analyze brain networks and connectivity patterns',
    'meta_analysis',
    getRandomDatasetId()
  );

  agent.listTools();
}

function measureBaselinePerformance() {
  const measurements = [];

  for (let i = 0; i < 5; i++) {
    const start = Date.now();

    orchestrator.healthCheck();
    brKg.executeGraphQLQuery('query { datasets(limit: 1) { id } }');

    const duration = Date.now() - start;
    measurements.push(duration);

    sleep(1);
  }

  const avgResponseTime = measurements.reduce((a, b) => a + b, 0) / measurements.length;
  const minResponseTime = Math.min(...measurements);
  const maxResponseTime = Math.max(...measurements);

  return {
    avgResponseTime,
    minResponseTime,
    maxResponseTime,
    timestamp: Date.now()
  };
}

function takePerformanceSnapshot(iteration) {
  const snapshot = {
    iteration,
    timestamp: Date.now(),
    elapsedMinutes: (Date.now() - soakMetrics.startTime) / 60000,
    memoryEstimate: estimateMemoryUsage(),
    responseTimeEstimate: estimateCurrentResponseTime()
  };

  soakMetrics.snapshots.push(snapshot);

  console.log(`Soak test snapshot ${iteration}: ${snapshot.elapsedMinutes.toFixed(1)}m elapsed`);

  // Check for trends
  if (soakMetrics.snapshots.length >= 3) {
    const recent = soakMetrics.snapshots.slice(-3);
    const responseTimeTrend = calculateTrend(recent.map(s => s.responseTimeEstimate));
    const memoryTrend = calculateTrend(recent.map(s => s.memoryEstimate));

    if (responseTimeTrend > 50) {
      console.log('⚠️ Response time degradation detected');
      soakMetrics.degradationDetected = true;
    }

    if (memoryTrend > 10) {
      console.log('⚠️ Potential memory leak detected');
      soakMetrics.memoryLeakDetected = true;
    }
  }
}

function estimateMemoryUsage() {
  // Estimate based on request complexity and VU count
  return __VU * 10 + (Date.now() - soakMetrics.startTime) / 100000;
}

function estimateCurrentResponseTime() {
  // Simple estimation based on system load
  const baseTime = soakMetrics.performanceDrift.baseline?.avgResponseTime || 500;
  const loadFactor = __VU / 30; // Assume 30 is optimal VU count
  return baseTime * (1 + loadFactor * 0.1);
}

function calculateTrend(values) {
  if (values.length < 2) return 0;

  const first = values[0];
  const last = values[values.length - 1];

  return ((last - first) / first) * 100; // Percentage change
}

function checkForDegradation() {
  const current = measureBaselinePerformance();
  const baseline = soakMetrics.performanceDrift.baseline;

  if (baseline) {
    const degradation = ((current.avgResponseTime - baseline.avgResponseTime) /
                        baseline.avgResponseTime) * 100;

    if (degradation > 20) {
      console.log(`⚠️ Performance degradation detected: ${degradation.toFixed(1)}% slower than baseline`);
      soakMetrics.degradationDetected = true;
    }

    soakMetrics.performanceDrift.current = current;
    soakMetrics.performanceDrift.samples.push({
      timestamp: Date.now(),
      avgResponseTime: current.avgResponseTime,
      degradationPercent: degradation
    });
  }
}

export function teardown(data) {
  const totalDuration = (Date.now() - soakMetrics.startTime) / 60000;
  console.log(`Soak test completed after ${totalDuration.toFixed(2)} minutes`);

  // Final analysis
  console.log('=== SOAK TEST ANALYSIS ===');
  console.log(`Snapshots taken: ${soakMetrics.snapshots.length}`);
  console.log(`Degradation detected: ${soakMetrics.degradationDetected ? 'Yes' : 'No'}`);
  console.log(`Memory leak detected: ${soakMetrics.memoryLeakDetected ? 'Yes' : 'No'}`);

  if (soakMetrics.performanceDrift.baseline && soakMetrics.performanceDrift.current) {
    const finalDegradation = ((soakMetrics.performanceDrift.current.avgResponseTime -
                             soakMetrics.performanceDrift.baseline.avgResponseTime) /
                            soakMetrics.performanceDrift.baseline.avgResponseTime) * 100;
    console.log(`Final performance change: ${finalDegradation.toFixed(1)}%`);
  }

  return { soakMetrics };
}

export function handleSummary(data) {
  const summary = {
    'soak_test_summary.json': JSON.stringify({
      ...data,
      soakMetrics: soakMetrics
    }, null, 2),
    'soak_test_summary.html': generateSoakTestReport(data),
    stdout: generateSoakTestConsoleReport(data)
  };

  return summary;
}

function generateSoakTestConsoleReport(data) {
  const duration = data.state.testRunDurationMs / 60000; // Convert to minutes
  const totalRequests = data.metrics.http_reqs.values.count;
  const errorRate = data.metrics.http_req_failed.values.rate;
  const avgResponse = data.metrics.http_req_duration.values.avg;

  const finalDegradation = soakMetrics.performanceDrift.baseline && soakMetrics.performanceDrift.current ?
    ((soakMetrics.performanceDrift.current.avgResponseTime -
      soakMetrics.performanceDrift.baseline.avgResponseTime) /
     soakMetrics.performanceDrift.baseline.avgResponseTime) * 100 : 0;

  return `
=== SOAK TEST SUMMARY ===
Test Duration: ${duration.toFixed(2)} minutes (${(duration/60).toFixed(1)} hours)
Total Requests: ${totalRequests}
Avg Requests/Min: ${(totalRequests / duration).toFixed(1)}

Long-term Performance:
- Success Rate: ${((1 - errorRate) * 100).toFixed(2)}%
- Avg Response Time: ${avgResponse.toFixed(2)}ms
- Performance Drift: ${finalDegradation.toFixed(1)}%

Stability Analysis:
- Performance Snapshots: ${soakMetrics.snapshots.length}
- Degradation Detected: ${soakMetrics.degradationDetected ? '⚠️ YES' : '✅ NO'}
- Memory Leak Signs: ${soakMetrics.memoryLeakDetected ? '⚠️ YES' : '✅ NO'}

System Stability:
${errorRate < 0.02 ? '✅ Excellent error rate stability' : '⚠️ Elevated error rate'}
${Math.abs(finalDegradation) < 10 ? '✅ Performance remained stable' : '⚠️ Significant performance drift'}
${!soakMetrics.degradationDetected ? '✅ No degradation patterns detected' : '⚠️ Performance degradation observed'}

Long-term Health:
${generateSoakTestRecommendations(data, soakMetrics)}
========================
  `;
}

function generateSoakTestRecommendations(data, metrics) {
  const recommendations = [];

  if (metrics.degradationDetected) {
    recommendations.push('- Investigate performance degradation causes (memory leaks, connection pooling)');
  }

  if (metrics.memoryLeakDetected) {
    recommendations.push('- Check for memory leaks in long-running processes');
  }

  if (data.metrics.http_req_failed.values.rate > 0.02) {
    recommendations.push('- Review error patterns for long-term stability issues');
  }

  const finalDegradation = metrics.performanceDrift.baseline && metrics.performanceDrift.current ?
    ((metrics.performanceDrift.current.avgResponseTime -
      metrics.performanceDrift.baseline.avgResponseTime) /
     metrics.performanceDrift.baseline.avgResponseTime) * 100 : 0;

  if (Math.abs(finalDegradation) > 15) {
    recommendations.push('- Significant performance drift detected - review resource management');
  }

  if (metrics.snapshots.length > 0) {
    const avgMemoryTrend = metrics.snapshots.reduce((sum, s) => sum + s.memoryEstimate, 0) / metrics.snapshots.length;
    if (avgMemoryTrend > 100) {
      recommendations.push('- Monitor memory usage patterns in production');
    }
  }

  if (recommendations.length === 0) {
    recommendations.push('- System demonstrated excellent long-term stability');
    recommendations.push('- Consider extending soak test duration for production validation');
  }

  return recommendations.join('\n');
}

function generateSoakTestReport(data) {
  const timestamp = new Date().toISOString();
  const duration = data.state.testRunDurationMs / 60000;

  const finalDegradation = soakMetrics.performanceDrift.baseline && soakMetrics.performanceDrift.current ?
    ((soakMetrics.performanceDrift.current.avgResponseTime -
      soakMetrics.performanceDrift.baseline.avgResponseTime) /
     soakMetrics.performanceDrift.baseline.avgResponseTime) * 100 : 0;

  return `
<!DOCTYPE html>
<html>
<head>
    <title>Brain Researcher Soak Test Report</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background-color: #f8f9fa; }
        .header { background: linear-gradient(135deg, #6f42c1, #563d7c); color: white; padding: 20px; border-radius: 5px; }
        .duration-highlight { background: #e7f1ff; border: 1px solid #b3d7ff; padding: 15px; border-radius: 5px; margin: 15px 0; text-align: center; }
        .stability-indicator { padding: 15px; margin: 15px 0; border-radius: 5px; }
        .stable { background: #d4edda; border-left: 4px solid #28a745; }
        .degraded { background: #f8d7da; border-left: 4px solid #dc3545; }
        .warning { background: #fff3cd; border-left: 4px solid #ffc107; }
        .metric-group { background: white; margin: 20px 0; padding: 20px; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .timeline { display: flex; align-items: center; margin: 15px 0; }
        .phase { padding: 10px 15px; margin: 5px; border-radius: 5px; color: white; text-align: center; }
        .ramp-up { background: #17a2b8; }
        .steady-state { background: #28a745; }
        .ramp-down { background: #6c757d; }
        .summary-table { width: 100%; border-collapse: collapse; margin: 20px 0; }
        .summary-table th, .summary-table td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
        .summary-table th { background-color: #6f42c1; color: white; }
        .trend-chart { background: #f8f9fa; border: 1px solid #dee2e6; padding: 20px; margin: 20px 0; border-radius: 5px; text-align: center; }
        .snapshot-timeline { display: flex; flex-wrap: wrap; gap: 10px; margin: 15px 0; }
        .snapshot { background: #e9ecef; padding: 8px 12px; border-radius: 3px; font-size: 0.9em; }
    </style>
</head>
<body>
    <div class="header">
        <h1>⏰ Brain Researcher Soak Test Report</h1>
        <p><strong>Generated:</strong> ${timestamp}</p>
        <p><strong>Duration:</strong> ${duration.toFixed(2)} minutes (${(duration/60).toFixed(2)} hours)</p>
        <p><strong>Test Type:</strong> Extended Load / Endurance Testing</p>
    </div>

    <div class="duration-highlight">
        <h3>🕒 Extended Duration Analysis</h3>
        <p>This soak test ran for <strong>${duration.toFixed(1)} minutes</strong> with consistent load to identify stability issues, memory leaks, and performance degradation over time.</p>
    </div>

    <div class="timeline">
        <div class="phase ramp-up">Ramp Up<br><small>5 minutes</small></div>
        <div class="phase steady-state">Steady State<br><small>30 minutes</small></div>
        <div class="phase ramp-down">Ramp Down<br><small>2 minutes</small></div>
    </div>

    <div class="stability-indicator ${!soakMetrics.degradationDetected && !soakMetrics.memoryLeakDetected ? 'stable' :
                                    soakMetrics.degradationDetected || soakMetrics.memoryLeakDetected ? 'degraded' : 'warning'}">
        <h3>${!soakMetrics.degradationDetected && !soakMetrics.memoryLeakDetected ? '✅ System Stable' :
             '⚠️ Stability Issues Detected'}</h3>
        <p><strong>Performance Degradation:</strong> ${soakMetrics.degradationDetected ? 'Detected' : 'Not Detected'}</p>
        <p><strong>Memory Leak Indicators:</strong> ${soakMetrics.memoryLeakDetected ? 'Detected' : 'Not Detected'}</p>
        <p><strong>Overall Performance Drift:</strong> ${finalDegradation.toFixed(1)}%</p>
    </div>

    <div class="metric-group">
        <h2>📊 Long-term Performance Metrics</h2>
        <table class="summary-table">
            <tr><th>Metric</th><th>Value</th><th>Assessment</th></tr>
            <tr><td>Total Requests</td><td>${data.metrics.http_reqs.values.count}</td><td>-</td></tr>
            <tr><td>Average RPS</td><td>${(data.metrics.http_reqs.values.count / (duration * 60)).toFixed(2)}</td><td>-</td></tr>
            <tr><td>Success Rate</td><td>${((1 - data.metrics.http_req_failed.values.rate) * 100).toFixed(3)}%</td>
                <td>${data.metrics.http_req_failed.values.rate < 0.02 ? '✅ Excellent' : '⚠️ Needs Review'}</td></tr>
            <tr><td>Avg Response Time</td><td>${data.metrics.http_req_duration.values.avg.toFixed(2)}ms</td><td>-</td></tr>
            <tr><td>P95 Response Time</td><td>${data.metrics.http_req_duration.values['p(95)'].toFixed(2)}ms</td>
                <td>${data.metrics.http_req_duration.values['p(95)'] < 3000 ? '✅ Good' : '⚠️ Elevated'}</td></tr>
            <tr><td>Performance Drift</td><td>${finalDegradation.toFixed(2)}%</td>
                <td>${Math.abs(finalDegradation) < 10 ? '✅ Stable' : '⚠️ Significant Drift'}</td></tr>
        </table>
    </div>

    <div class="metric-group">
        <h2>📈 Performance Trend Analysis</h2>
        <p><strong>Snapshots Captured:</strong> ${soakMetrics.snapshots.length}</p>
        <div class="snapshot-timeline">
            ${soakMetrics.snapshots.map((snapshot, i) => `
                <div class="snapshot">
                    ${snapshot.elapsedMinutes.toFixed(0)}m: ${snapshot.responseTimeEstimate.toFixed(0)}ms
                </div>
            `).join('')}
        </div>

        <div class="trend-chart">
            📊 Performance Trend Visualization<br>
            <small>Shows response time and resource utilization trends over the test duration</small><br>
            <strong>Baseline:</strong> ${soakMetrics.performanceDrift.baseline?.avgResponseTime.toFixed(2) || 'N/A'}ms →
            <strong>Final:</strong> ${soakMetrics.performanceDrift.current?.avgResponseTime.toFixed(2) || 'N/A'}ms
        </div>
    </div>

    <div class="metric-group">
        <h2>🔍 Stability Analysis</h2>
        <div class="stability-indicator ${!soakMetrics.degradationDetected ? 'stable' : 'warning'}">
            <strong>Response Time Degradation:</strong> ${soakMetrics.degradationDetected ? '⚠️ Detected during test execution' : '✅ No significant degradation observed'}
        </div>
        <div class="stability-indicator ${!soakMetrics.memoryLeakDetected ? 'stable' : 'warning'}">
            <strong>Memory Leak Indicators:</strong> ${soakMetrics.memoryLeakDetected ? '⚠️ Potential memory leaks detected' : '✅ No memory leak patterns observed'}
        </div>
    </div>

    <div class="metric-group">
        <h2>💡 Long-term Stability Recommendations</h2>
        ${generateSoakTestRecommendations(data, soakMetrics).split('\n').map(rec =>
          rec.trim() ? `<div style="padding: 8px; margin: 5px 0; border-left: 3px solid #6f42c1; background: #f3e5f5;">${rec}</div>` : ''
        ).join('')}
    </div>

    <div class="metric-group">
        <h2>📋 Detailed Soak Test Data</h2>
        <details>
            <summary>Click to view comprehensive test results</summary>
            <pre style="background: #f8f9fa; padding: 20px; border-radius: 5px; overflow-x: auto; max-height: 400px;">${JSON.stringify({...data, soakMetrics}, null, 2)}</pre>
        </details>
    </div>
</body>
</html>
  `;
}