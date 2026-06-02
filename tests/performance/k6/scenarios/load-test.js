/**
 * Load Testing Scenario for Brain Researcher Backend Services
 *
 * This test simulates normal production load across all services to validate
 * performance under expected traffic patterns.
 */

import { check, group, sleep } from 'k6';
import http from 'k6/http';
import { CONFIG, LOAD_PROFILE, getRandomQuery, getRandomDatasetId } from '../config/k6.config.js';
import {
  OrchestratorAPI,
  BRKGAPI,
  AgentAPI,
  TestDataGenerator,
  makeRequest,
  errorRate,
  successfulRequests,
  queryExecutionTime
} from '../scripts/utils.js';

// Test configuration
export let options = {
  stages: LOAD_PROFILE.stages,
  thresholds: CONFIG.THRESHOLDS,
  ext: {
    loadimpact: {
      distribution: {
        'amazon:us:ashburn': { loadZone: 'amazon:us:ashburn', percent: 100 },
      },
    },
  },
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  summaryTimeUnit: 'ms',
};

// Initialize service clients
const orchestrator = new OrchestratorAPI();
const brKg = new BRKGAPI();
const agent = new AgentAPI();

// Test data
const testQueries = CONFIG.TEST_DATA.AGENT_QUERIES;
const graphqlQueries = CONFIG.TEST_DATA.BR_KG_QUERIES;
const datasetIds = CONFIG.TEST_DATA.DATASET_IDS;

export function setup() {
  console.log('Starting load test setup...');

  // Verify all services are healthy
  const orchestratorHealth = orchestrator.healthCheck();
  const brKgHealth = brKg.healthCheck();
  const agentHealth = agent.healthCheck();

  console.log(`Service health checks - Orchestrator: ${orchestratorHealth}, BR-KG: ${brKgHealth}, Agent: ${agentHealth}`);

  if (!orchestratorHealth || !brKgHealth || !agentHealth) {
    throw new Error('One or more services failed health check');
  }

  return {
    setupTime: Date.now(),
    servicesHealthy: true
  };
}

export default function(data) {
  // Simulate realistic user behavior with different service interaction patterns
  const userBehavior = Math.random();

  if (userBehavior < 0.4) {
    // 40% - Heavy Orchestrator usage (typical web UI interactions)
    runOrchestratorScenario();
  } else if (userBehavior < 0.7) {
    // 30% - BR-KG API usage (data exploration)
    runBRKGScenario();
  } else if (userBehavior < 0.9) {
    // 20% - Agent interactions (complex analysis)
    runAgentScenario();
  } else {
    // 10% - Mixed workflow (end-to-end analysis)
    runMixedWorkflowScenario();
  }

  // Random sleep between requests (1-3 seconds)
  sleep(1 + Math.random() * 2);
}

function runOrchestratorScenario() {
  group('Orchestrator Load Test Scenario', () => {
    // 1. Check service health
    orchestrator.healthCheck();

    // 2. List available datasets
    orchestrator.listDatasets();

    // 3. Get available tools
    orchestrator.listTools();

    // 4. Create analysis run
    const prompt = getRandomQuery('AGENT');
    const pipeline = CONFIG.TEST_DATA.PIPELINES[Math.floor(Math.random() * CONFIG.TEST_DATA.PIPELINES.length)];
    const datasetId = getRandomDatasetId();

    const createRunResult = orchestrator.createRun(prompt, pipeline, datasetId);

    if (createRunResult) {
      // 5. Check job status
      // In real scenario, we'd get job_id from the response
      const mockJobId = 'job_' + Math.random().toString(36).substr(2, 9);
      orchestrator.getJob(mockJobId);

      sleep(0.5);

      // 6. Check job status again (polling behavior)
      orchestrator.getJob(mockJobId);
    }

    // 7. Search datasets with query
    const searchQuery = 'motor task';
    orchestrator.listDatasets(searchQuery);
  });
}

function runBRKGScenario() {
  group('BR-KG Load Test Scenario', () => {
    // 1. Health check
    brKg.healthCheck();

    // 2. Execute simple GraphQL query
    const simpleQuery = 'query { datasets(limit: 5) { id name description } }';
    brKg.executeGraphQLQuery(simpleQuery);

    // 3. Execute complex GraphQL query
    const complexQuery = TestDataGenerator.generateComplexGraphQLQuery();
    const variables = {
      limit: 10,
      taskType: 'working_memory'
    };
    brKg.executeGraphQLQuery(complexQuery, variables);

    // 4. Full-text search
    const searchQuery = 'prefrontal cortex activation';
    brKg.executeSearch(searchQuery, ['Study', 'BrainRegion'], 20);

    // 5. SPARQL query
    const sparqlQuery = TestDataGenerator.generateSPARQLQuery();
    brKg.executeSPARQLQuery(sparqlQuery);

    // 6. Dataset search
    brKg.searchDatasets('fMRI motor task', 15);

    // 7. Performance metrics check
    brKg.getPerformanceMetrics();
  });
}

function runAgentScenario() {
  group('Agent Load Test Scenario', () => {
    // 1. Health check
    agent.healthCheck();

    // 2. List available tools
    agent.listTools();

    // 3. Execute analysis query
    const query = TestDataGenerator.generateFMRIQuery();
    const parameters = TestDataGenerator.generateRandomParameters();

    agent.executeQuery(query, 'load_test_user', { parameters });

    // 4. Execute another query with different parameters
    const query2 = getRandomQuery('AGENT');
    agent.executeQuery(query2, 'load_test_user', {
      timeout: 60,
      max_iterations: 5
    });
  });
}

function runMixedWorkflowScenario() {
  group('Mixed Workflow Load Test Scenario', () => {
    // Simulate a complete analysis workflow

    // 1. Start with dataset exploration via Orchestrator
    orchestrator.listDatasets('fMRI');

    // 2. Get detailed dataset info from BR-KG
    const datasetQuery = 'query { datasets(source: "OpenNeuro") { id name subjects tasks } }';
    brKg.executeGraphQLQuery(datasetQuery);

    // 3. Create analysis run
    const prompt = 'Analyze working memory activation patterns in the prefrontal cortex';
    orchestrator.createRun(prompt, 'glm', 'ds000001');

    // 4. Search for related studies in BR-KG
    brKg.executeSearch('working memory prefrontal cortex', ['Study'], 10);

    // 5. Execute complex analysis via Agent
    const complexAnalysis = 'Compare activation patterns between young and old adults in working memory tasks';
    agent.executeQuery(complexAnalysis, 'workflow_user', {
      analysis_type: 'group_comparison',
      correction_method: 'fdr'
    });

    // 6. Get performance metrics
    brKg.getPerformanceMetrics();
  });
}

export function teardown(data) {
  console.log('Load test completed');
  console.log(`Test duration: ${(Date.now() - data.setupTime) / 1000}s`);
}

export function handleSummary(data) {
  const summary = {
    'load_test_summary.json': JSON.stringify(data, null, 2),
    'load_test_summary.html': generateHTMLReport(data),
    stdout: `
=== LOAD TEST SUMMARY ===
Test Duration: ${data.state.testRunDurationMs / 1000}s
Virtual Users: ${data.options.stages ? 'Variable (see stages)' : data.options.vus}

HTTP Requests:
- Total: ${data.metrics.http_reqs.values.count}
- Success Rate: ${((1 - data.metrics.http_req_failed.values.rate) * 100).toFixed(2)}%
- Avg Response Time: ${data.metrics.http_req_duration.values.avg.toFixed(2)}ms
- P95 Response Time: ${data.metrics['http_req_duration'].values['p(95)'].toFixed(2)}ms
- P99 Response Time: ${data.metrics['http_req_duration'].values['p(99)'].toFixed(2)}ms

Requests per Second: ${data.metrics.http_reqs.values.rate.toFixed(2)}

Service Performance:
- Orchestrator P95: ${data.metrics['http_req_duration{group:::orchestrator_api}']?.values['p(95)']?.toFixed(2) || 'N/A'}ms
- BR-KG P95: ${data.metrics['http_req_duration{group:::brKg_api}']?.values['p(95)']?.toFixed(2) || 'N/A'}ms
- Agent P95: ${data.metrics['http_req_duration{group:::agent_api}']?.values['p(95)']?.toFixed(2) || 'N/A'}ms

Thresholds:
${Object.entries(data.metrics).filter(([key, metric]) =>
  metric.thresholds && Object.keys(metric.thresholds).length > 0
).map(([key, metric]) =>
  Object.entries(metric.thresholds).map(([threshold, result]) =>
    `- ${key} ${threshold}: ${result.ok ? '✅ PASS' : '❌ FAIL'}`
  ).join('\n')
).join('\n')}
========================
    `
  };

  return summary;
}

function generateHTMLReport(data) {
  const timestamp = new Date().toISOString();
  const duration = data.state.testRunDurationMs / 1000;

  return `
<!DOCTYPE html>
<html>
<head>
    <title>Brain Researcher Load Test Report</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; }
        .header { background: #f0f0f0; padding: 20px; border-radius: 5px; }
        .metric-group { margin: 20px 0; }
        .metric { background: #f9f9f9; padding: 10px; margin: 5px 0; border-left: 4px solid #007cba; }
        .pass { border-left-color: #28a745; }
        .fail { border-left-color: #dc3545; }
        .summary-table { width: 100%; border-collapse: collapse; margin: 20px 0; }
        .summary-table th, .summary-table td { padding: 10px; text-align: left; border-bottom: 1px solid #ddd; }
        .summary-table th { background-color: #f2f2f2; }
    </style>
</head>
<body>
    <div class="header">
        <h1>Brain Researcher Load Test Report</h1>
        <p><strong>Generated:</strong> ${timestamp}</p>
        <p><strong>Duration:</strong> ${duration.toFixed(2)} seconds</p>
        <p><strong>Test Type:</strong> Load Test (Normal Production Load)</p>
    </div>

    <div class="metric-group">
        <h2>Overall Performance</h2>
        <table class="summary-table">
            <tr><th>Metric</th><th>Value</th></tr>
            <tr><td>Total Requests</td><td>${data.metrics.http_reqs.values.count}</td></tr>
            <tr><td>Success Rate</td><td>${((1 - data.metrics.http_req_failed.values.rate) * 100).toFixed(2)}%</td></tr>
            <tr><td>Requests/Second</td><td>${data.metrics.http_reqs.values.rate.toFixed(2)}</td></tr>
            <tr><td>Avg Response Time</td><td>${data.metrics.http_req_duration.values.avg.toFixed(2)}ms</td></tr>
            <tr><td>P95 Response Time</td><td>${data.metrics.http_req_duration.values['p(95)'].toFixed(2)}ms</td></tr>
            <tr><td>P99 Response Time</td><td>${data.metrics.http_req_duration.values['p(99)'].toFixed(2)}ms</td></tr>
        </table>
    </div>

    <div class="metric-group">
        <h2>Threshold Results</h2>
        ${Object.entries(data.metrics).filter(([key, metric]) =>
          metric.thresholds && Object.keys(metric.thresholds).length > 0
        ).map(([key, metric]) =>
          Object.entries(metric.thresholds).map(([threshold, result]) =>
            `<div class="metric ${result.ok ? 'pass' : 'fail'}">
              <strong>${key}</strong> ${threshold}: ${result.ok ? '✅ PASS' : '❌ FAIL'}
            </div>`
          ).join('')
        ).join('')}
    </div>

    <div class="metric-group">
        <h2>Recommendations</h2>
        <ul>
            ${data.metrics.http_req_failed.values.rate > 0.05 ?
              '<li>⚠️ Error rate above 5% - investigate failing endpoints</li>' : ''}
            ${data.metrics.http_req_duration.values['p(95)'] > 2000 ?
              '<li>⚠️ P95 response time above 2s - consider performance optimization</li>' : ''}
            ${data.metrics.http_reqs.values.rate < 100 ?
              '<li>⚠️ Throughput below 100 RPS - may need capacity scaling</li>' : ''}
            <li>✅ Load test completed successfully</li>
        </ul>
    </div>

    <div class="metric-group">
        <h2>Raw Data</h2>
        <pre>${JSON.stringify(data, null, 2)}</pre>
    </div>
</body>
</html>
  `;
}