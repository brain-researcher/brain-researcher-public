/**
 * Spike Testing Scenario for Brain Researcher Backend Services
 *
 * This test simulates sudden traffic spikes to validate system behavior
 * under rapid load increases and recovery patterns.
 */

import { check, group, sleep } from 'k6';
import http from 'k6/http';
import { CONFIG, SPIKE_PROFILE, getRandomQuery, getRandomDatasetId } from '../config/k6.config.js';
import {
  OrchestratorAPI,
  BRKGAPI,
  AgentAPI,
  TestDataGenerator,
  errorRate,
  successfulRequests,
  requestDuration,
  memoryUsage
} from '../scripts/utils.js';

// Spike test configuration
export let options = {
  stages: SPIKE_PROFILE.stages,
  thresholds: {
    // Spike-specific thresholds - expect temporary degradation during spikes
    'http_req_duration': ['p(50)<2000', 'p(95)<8000'], // More lenient during spikes
    'http_req_failed': ['rate<0.25'], // Allow higher failure rate during spikes
    'http_reqs': ['rate>20'], // Minimum throughput even during chaos

    // Recovery thresholds - system should recover quickly
    'http_req_duration{expected:recovery}': ['p(95)<1000'],
    'http_req_failed{expected:recovery}': ['rate<0.05'],

    // Spike detection metrics
    'spike_response_degradation': ['p(90)<5000'],
    'spike_recovery_time': ['p(95)<30000'], // Should recover within 30s
  },
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
  summaryTimeUnit: 'ms',
};

// Initialize service clients
const orchestrator = new OrchestratorAPI();
const brKg = new BRKGAPI();
const agent = new AgentAPI();

// Spike test metrics
let spikeMetrics = {
  spikes: [],
  currentSpike: null,
  recoveryTimes: [],
  maxDegradation: 0,
  baselinePerformance: null
};

export function setup() {
  console.log('Starting spike test setup...');

  // Establish baseline performance
  const baselineStart = Date.now();

  orchestrator.healthCheck();
  brKg.executeGraphQLQuery('query { datasets(limit: 5) { id name } }');
  agent.listTools();

  const baselineTime = Date.now() - baselineStart;
  spikeMetrics.baselinePerformance = baselineTime;

  console.log(`Baseline performance: ${baselineTime}ms`);

  return {
    setupTime: Date.now(),
    baselinePerformance: baselineTime
  };
}

export default function(data) {
  const currentPhase = getCurrentPhase();
  const vuCount = __VU;

  // Tag requests based on expected behavior
  const tags = { expected: currentPhase };

  switch (currentPhase) {
    case 'normal':
      runNormalLoadScenario(tags);
      break;
    case 'spike':
      runSpikeScenario(tags);
      trackSpikeMetrics(vuCount);
      break;
    case 'recovery':
      runRecoveryScenario(tags);
      trackRecoveryMetrics();
      break;
    default:
      runNormalLoadScenario(tags);
  }

  // Adaptive sleep based on current load phase
  const sleepTime = currentPhase === 'spike' ? 0.1 :
                   currentPhase === 'recovery' ? 1.5 : 1.0;
  sleep(sleepTime);
}

function getCurrentPhase() {
  const elapsed = Date.now() - (__ENV.TEST_START_TIME || Date.now());
  const stage = Math.floor(elapsed / 60000); // Convert to stage number

  // Stage pattern: normal(1m) → spike(30s) → normal(1m) → spike(30s) → recovery(1m)
  const phasePattern = ['normal', 'spike', 'normal', 'spike', 'recovery'];
  return phasePattern[Math.min(stage, phasePattern.length - 1)] || 'normal';
}

function runNormalLoadScenario(tags) {
  group('Normal Load Phase', () => {
    // Standard operations during normal load
    orchestrator.healthCheck();

    const query = getRandomQuery('AGENT');
    orchestrator.createRun(query, 'glm', getRandomDatasetId());

    brKg.executeGraphQLQuery(
      'query { studies(limit: 10) { title pmid } }',
      {},
      { tags }
    );

    brKg.executeSearch('brain activation', ['Study'], 20);
  });
}

function runSpikeScenario(tags) {
  group('Spike Load Phase', () => {
    // Aggressive load during spike - rapid concurrent requests
    const spikeStart = Date.now();

    // Record spike start
    if (!spikeMetrics.currentSpike) {
      spikeMetrics.currentSpike = {
        startTime: spikeStart,
        startVU: __VU,
        peakVU: __VU,
        responses: []
      };
    } else {
      spikeMetrics.currentSpike.peakVU = Math.max(
        spikeMetrics.currentSpike.peakVU,
        __VU
      );
    }

    // Fire multiple requests simultaneously
    const requests = [
      () => orchestrator.createRun(
        'Analyze brain connectivity patterns in working memory networks',
        'connectivity',
        getRandomDatasetId()
      ),
      () => brKg.executeGraphQLQuery(
        TestDataGenerator.generateComplexGraphQLQuery(),
        { limit: 100, taskType: 'working_memory' },
        { tags }
      ),
      () => agent.executeQuery(
        'Execute comprehensive neuroimaging analysis with statistical maps',
        `spike_user_${__VU}`,
        { priority: 'high', timeout: 60 }
      ),
      () => brKg.executeSearch(
        'comprehensive brain analysis activation patterns connectivity networks',
        ['Study', 'BrainRegion', 'Dataset'],
        50
      ),
      () => orchestrator.listDatasets('complex neuroimaging studies')
    ];

    // Execute all requests with minimal delay
    requests.forEach((request, index) => {
      setTimeout(() => {
        const requestStart = Date.now();
        try {
          const result = request();
          const requestTime = Date.now() - requestStart;

          // Track spike response times
          if (spikeMetrics.currentSpike) {
            spikeMetrics.currentSpike.responses.push(requestTime);
          }

          // Calculate degradation compared to baseline
          if (spikeMetrics.baselinePerformance) {
            const degradation = requestTime / spikeMetrics.baselinePerformance;
            spikeMetrics.maxDegradation = Math.max(
              spikeMetrics.maxDegradation,
              degradation
            );
          }

        } catch (error) {
          console.log(`Spike request ${index} failed: ${error.message}`);
        }
      }, index * 50); // 50ms stagger
    });
  });
}

function runRecoveryScenario(tags) {
  group('Recovery Phase', () => {
    const recoveryStart = Date.now();

    // Light load to test recovery
    const healthCheck = orchestrator.healthCheck();
    const healthTime = Date.now() - recoveryStart;

    // Check if system is recovering (response times improving)
    if (healthCheck && healthTime < 1000) {
      trackRecoverySuccess(recoveryStart);
    }

    // Gradual return to normal operations
    brKg.executeGraphQLQuery(
      'query { datasets(limit: 3) { id name } }',
      {},
      { tags }
    );

    const simpleQuery = 'Show me basic brain activation data';
    agent.executeQuery(simpleQuery, `recovery_user_${__VU}`, {
      timeout: 30,
      tags
    });

    sleep(2); // Longer sleep during recovery
  });
}

function trackSpikeMetrics(vuCount) {
  if (spikeMetrics.currentSpike) {
    spikeMetrics.currentSpike.peakVU = Math.max(
      spikeMetrics.currentSpike.peakVU,
      vuCount
    );
  }
}

function trackRecoveryMetrics() {
  if (spikeMetrics.currentSpike && !spikeMetrics.currentSpike.endTime) {
    // Mark end of current spike
    spikeMetrics.currentSpike.endTime = Date.now();
    spikeMetrics.currentSpike.duration =
      spikeMetrics.currentSpike.endTime - spikeMetrics.currentSpike.startTime;

    // Calculate average response time during spike
    const responses = spikeMetrics.currentSpike.responses;
    if (responses.length > 0) {
      spikeMetrics.currentSpike.avgResponseTime =
        responses.reduce((a, b) => a + b, 0) / responses.length;
    }

    // Store completed spike and reset for next one
    spikeMetrics.spikes.push({ ...spikeMetrics.currentSpike });
    spikeMetrics.currentSpike = null;
  }
}

function trackRecoverySuccess(recoveryStart) {
  const recoveryTime = Date.now() - recoveryStart;
  spikeMetrics.recoveryTimes.push(recoveryTime);

  console.log(`Recovery detected in ${recoveryTime}ms`);
}

export function teardown(data) {
  console.log('Spike test completed');

  // Final spike processing
  if (spikeMetrics.currentSpike) {
    trackRecoveryMetrics();
  }

  // Calculate recovery statistics
  if (spikeMetrics.recoveryTimes.length > 0) {
    const avgRecovery = spikeMetrics.recoveryTimes.reduce((a, b) => a + b, 0) /
                       spikeMetrics.recoveryTimes.length;
    console.log(`Average recovery time: ${avgRecovery.toFixed(2)}ms`);
  }

  console.log(`Spike test metrics:`);
  console.log(`- Number of spikes: ${spikeMetrics.spikes.length}`);
  console.log(`- Max degradation: ${spikeMetrics.maxDegradation.toFixed(2)}x baseline`);

  return { spikeMetrics };
}

export function handleSummary(data) {
  const summary = {
    'spike_test_summary.json': JSON.stringify({
      ...data,
      spikeMetrics: spikeMetrics
    }, null, 2),
    'spike_test_summary.html': generateSpikeTestReport(data),
    stdout: generateSpikeTestConsoleReport(data)
  };

  return summary;
}

function generateSpikeTestConsoleReport(data) {
  const duration = data.state.testRunDurationMs / 1000;
  const totalRequests = data.metrics.http_reqs.values.count;
  const errorRate = data.metrics.http_req_failed.values.rate;
  const p95Response = data.metrics.http_req_duration.values['p(95)'];

  const avgRecovery = spikeMetrics.recoveryTimes.length > 0 ?
    spikeMetrics.recoveryTimes.reduce((a, b) => a + b, 0) / spikeMetrics.recoveryTimes.length :
    0;

  return `
=== SPIKE TEST SUMMARY ===
Test Duration: ${duration.toFixed(2)}s
Total Requests: ${totalRequests}
Spike Events: ${spikeMetrics.spikes.length}

Performance During Spikes:
- Success Rate: ${((1 - errorRate) * 100).toFixed(2)}%
- P95 Response Time: ${p95Response.toFixed(2)}ms
- Max Performance Degradation: ${spikeMetrics.maxDegradation.toFixed(2)}x baseline

Recovery Analysis:
- Average Recovery Time: ${avgRecovery.toFixed(2)}ms
- Recovery Events: ${spikeMetrics.recoveryTimes.length}
- System Resilience: ${avgRecovery < 10000 ? '✅ Fast Recovery' : '⚠️ Slow Recovery'}

Spike Details:
${spikeMetrics.spikes.map((spike, i) =>
  `Spike ${i+1}: ${spike.duration}ms duration, peak ${spike.peakVU} VUs, avg response ${spike.avgResponseTime?.toFixed(2) || 'N/A'}ms`
).join('\n')}

System Behavior:
${errorRate < 0.25 ? '✅ System handled spikes well' : '⚠️ High errors during spikes'}
${p95Response < 8000 ? '✅ Response times acceptable' : '⚠️ Severe response degradation'}
${avgRecovery < 30000 ? '✅ Quick recovery' : '⚠️ Slow recovery patterns'}

Recommendations:
${generateSpikeTestRecommendations(data, spikeMetrics)}
========================
  `;
}

function generateSpikeTestRecommendations(data, metrics) {
  const recommendations = [];

  if (metrics.maxDegradation > 10) {
    recommendations.push('- Consider auto-scaling or load balancing improvements');
  }

  if (data.metrics.http_req_failed.values.rate > 0.2) {
    recommendations.push('- Implement circuit breakers to prevent cascade failures');
  }

  const avgRecovery = metrics.recoveryTimes.length > 0 ?
    metrics.recoveryTimes.reduce((a, b) => a + b, 0) / metrics.recoveryTimes.length : 0;

  if (avgRecovery > 20000) {
    recommendations.push('- Improve system recovery mechanisms and health checks');
  }

  if (metrics.spikes.some(spike => spike.avgResponseTime > 5000)) {
    recommendations.push('- Optimize critical endpoints for spike load tolerance');
  }

  if (data.metrics.http_reqs.values.rate < 20) {
    recommendations.push('- Investigate throughput bottlenecks during high load');
  }

  if (recommendations.length === 0) {
    recommendations.push('- System demonstrated good spike load tolerance');
    recommendations.push('- Consider testing with larger spike magnitudes');
  }

  return recommendations.join('\n');
}

function generateSpikeTestReport(data) {
  const timestamp = new Date().toISOString();
  const duration = data.state.testRunDurationMs / 1000;

  const avgRecovery = spikeMetrics.recoveryTimes.length > 0 ?
    spikeMetrics.recoveryTimes.reduce((a, b) => a + b, 0) / spikeMetrics.recoveryTimes.length :
    0;

  return `
<!DOCTYPE html>
<html>
<head>
    <title>Brain Researcher Spike Test Report</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background-color: #f8f9fa; }
        .header { background: linear-gradient(135deg, #fd7e14, #e55100); color: white; padding: 20px; border-radius: 5px; }
        .spike-indicator { background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px; margin: 15px 0; }
        .recovery-indicator { background: #d4edda; border-left: 4px solid #28a745; padding: 15px; margin: 15px 0; }
        .metric-group { background: white; margin: 20px 0; padding: 20px; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .spike-timeline { display: flex; align-items: center; margin: 10px 0; }
        .normal-phase { background: #28a745; color: white; padding: 5px 10px; margin: 2px; border-radius: 3px; }
        .spike-phase { background: #dc3545; color: white; padding: 5px 10px; margin: 2px; border-radius: 3px; animation: blink 1s infinite; }
        .recovery-phase { background: #17a2b8; color: white; padding: 5px 10px; margin: 2px; border-radius: 3px; }
        @keyframes blink { 0%, 50% { opacity: 1; } 51%, 100% { opacity: 0.5; } }
        .summary-table { width: 100%; border-collapse: collapse; margin: 20px 0; }
        .summary-table th, .summary-table td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
        .summary-table th { background-color: #fd7e14; color: white; }
        .chart-placeholder { background: #e9ecef; padding: 40px; text-align: center; margin: 20px 0; border-radius: 5px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>⚡ Brain Researcher Spike Test Report</h1>
        <p><strong>Generated:</strong> ${timestamp}</p>
        <p><strong>Duration:</strong> ${duration.toFixed(2)} seconds</p>
        <p><strong>Spike Events:</strong> ${spikeMetrics.spikes.length}</p>
    </div>

    <div class="spike-indicator">
        <h3>🎯 Spike Test Pattern</h3>
        <div class="spike-timeline">
            <div class="normal-phase">Normal (1m)</div>
            <div class="spike-phase">SPIKE (30s)</div>
            <div class="normal-phase">Normal (1m)</div>
            <div class="spike-phase">SPIKE (30s)</div>
            <div class="recovery-phase">Recovery (1m)</div>
        </div>
    </div>

    <div class="metric-group">
        <h2>📊 Spike Performance Analysis</h2>
        <table class="summary-table">
            <tr><th>Metric</th><th>Value</th><th>Assessment</th></tr>
            <tr><td>Total Requests</td><td>${data.metrics.http_reqs.values.count}</td><td>-</td></tr>
            <tr><td>Overall Success Rate</td><td>${((1 - data.metrics.http_req_failed.values.rate) * 100).toFixed(2)}%</td>
                <td>${data.metrics.http_req_failed.values.rate < 0.25 ? '✅ Acceptable' : '⚠️ High Failures'}</td></tr>
            <tr><td>P95 Response Time</td><td>${data.metrics.http_req_duration.values['p(95)'].toFixed(2)}ms</td>
                <td>${data.metrics.http_req_duration.values['p(95)'] < 8000 ? '✅ Good' : '⚠️ Degraded'}</td></tr>
            <tr><td>Max Degradation</td><td>${spikeMetrics.maxDegradation.toFixed(2)}x baseline</td>
                <td>${spikeMetrics.maxDegradation < 5 ? '✅ Manageable' : '⚠️ Severe'}</td></tr>
            <tr><td>Average Recovery</td><td>${avgRecovery.toFixed(2)}ms</td>
                <td>${avgRecovery < 30000 ? '✅ Fast' : '⚠️ Slow'}</td></tr>
        </table>
    </div>

    <div class="metric-group">
        <h2>⚡ Individual Spike Analysis</h2>
        ${spikeMetrics.spikes.map((spike, i) => `
            <div class="spike-indicator">
                <h4>Spike ${i + 1}</h4>
                <p><strong>Duration:</strong> ${spike.duration}ms</p>
                <p><strong>Peak VUs:</strong> ${spike.peakVU}</p>
                <p><strong>Avg Response:</strong> ${spike.avgResponseTime?.toFixed(2) || 'N/A'}ms</p>
                <p><strong>Requests:</strong> ${spike.responses?.length || 0}</p>
            </div>
        `).join('')}
    </div>

    <div class="recovery-indicator">
        <h3>🔄 Recovery Analysis</h3>
        <p><strong>Recovery Events:</strong> ${spikeMetrics.recoveryTimes.length}</p>
        <p><strong>Average Recovery Time:</strong> ${avgRecovery.toFixed(2)}ms</p>
        <p><strong>Recovery Pattern:</strong> ${avgRecovery < 10000 ? 'Rapid recovery after spikes' : 'Gradual recovery pattern'}</p>
    </div>

    <div class="chart-placeholder">
        📈 Spike Load Pattern Visualization<br>
        <small>Shows load distribution and response time spikes over test duration</small>
    </div>

    <div class="metric-group">
        <h2>💡 Spike Test Insights</h2>
        ${generateSpikeTestRecommendations(data, spikeMetrics).split('\n').map(rec =>
          rec.trim() ? `<div style="padding: 8px; margin: 5px 0; border-left: 3px solid #fd7e14; background: #fff3cd;">${rec}</div>` : ''
        ).join('')}
    </div>

    <div class="metric-group">
        <h2>📋 Technical Details</h2>
        <details>
            <summary>Click to view detailed spike metrics</summary>
            <pre style="background: #f8f9fa; padding: 20px; border-radius: 5px; overflow-x: auto;">${JSON.stringify({...data, spikeMetrics}, null, 2)}</pre>
        </details>
    </div>
</body>
</html>
  `;
}