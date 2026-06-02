import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Gauge, Rate, Trend } from 'k6/metrics';
import {
  createCustomMetrics,
  DataGenerator,
  UserSession,
  PerformanceValidator,
  healthCheck,
  monitorAutoScaling,
  withRetry
} from '../utils/common.js';

// Custom metrics for spike testing
const customMetrics = createCustomMetrics();
const spikeResponseTime = new Trend('spike_response_time');
const spikeErrors = new Counter('spike_errors');
const autoScaleLatency = new Trend('auto_scale_spike_latency');
const recoveryTime = new Trend('post_spike_recovery_time');

// Spike test configuration - sudden traffic spikes
export let options = {
  stages: [
    { duration: '2m', target: 10 },    // Baseline: 10 users
    { duration: '30s', target: 10 },   // Stay at baseline
    { duration: '30s', target: 200 },  // SPIKE: Jump to 200 users
    { duration: '2m', target: 200 },   // Sustain spike
    { duration: '30s', target: 10 },   // Drop back to baseline
    { duration: '2m', target: 10 },    // Recovery period
    { duration: '30s', target: 300 },  // SPIKE: Even higher spike
    { duration: '1m', target: 300 },   // Sustain high spike
    { duration: '30s', target: 10 },   // Drop back to baseline
    { duration: '3m', target: 10 },    // Extended recovery
    { duration: '1m', target: 0 },     // Ramp down
  ],
  thresholds: {
    'http_req_duration': ['p(95)<1000', 'p(99)<3000'],
    'http_req_failed': ['rate<0.02'], // Allow 2% error rate during spikes
    'spike_response_time': ['p(95)<2000'], // Spike-specific threshold
    'auto_scale_spike_latency': ['p(90)<180000'], // 3 minutes for auto-scaling
    'post_spike_recovery_time': ['p(90)<120000'], // 2 minutes recovery
  },
};

// Test data generator
const dataGen = new DataGenerator();

// Performance validator for spike testing
const validator = new PerformanceValidator({
  maxResponseTime: 1000,
  maxErrorRate: 0.02,
  minThroughput: 20
});

// Spike detection variables
let spikeStartTime = null;
let baselineEstablished = false;
let spikeDetected = false;
let recoveryStartTime = null;

export function setup() {
  console.log('Setting up spike test...');

  // Generate test data optimized for spike scenarios
  const testData = {
    users: dataGen.generateUsers(500),
    analysisRequests: dataGen.generateAnalysisRequests(200),
    knowledgeGraphQueries: dataGen.generateKnowledgeGraphQueries(100),
    quickOperations: generateQuickOperations(100), // Fast operations for spikes
    spikeScenarios: generateSpikeScenarios(50) // Spike-specific scenarios
  };

  // Initial health check
  const healthStatus = healthCheck(__ENV.BASE_URL || 'http://localhost');
  if (!healthStatus.healthy) {
    throw new Error(`Health check failed: ${healthStatus.message}`);
  }

  // Establish baseline metrics
  const baselineMetrics = captureBaselineMetrics(__ENV.BASE_URL || 'http://localhost');
  console.log('Baseline metrics captured:', JSON.stringify(baselineMetrics, null, 2));

  console.log('Spike test setup complete');
  return testData;
}

export default function(data) {
  const baseUrl = __ENV.BASE_URL || 'http://localhost';
  const user = data.users[Math.floor(Math.random() * data.users.length)];
  const userSession = new UserSession(user, baseUrl);

  userSession.start();

  try {
    // Detect current load level based on virtual users
    const currentVUs = __VU;
    const isSpike = detectSpike(currentVUs);

    if (isSpike) {
      handleSpikeScenario(userSession, data);
    } else {
      handleBaselineScenario(userSession, data);
    }

  } catch (error) {
    spikeErrors.add(1);
    console.error(`Spike test error for user ${user.username}: ${error}`);
  } finally {
    userSession.end();
  }

  // Monitor auto-scaling during spikes
  monitorSpikeAutoScaling(baseUrl);

  // Very short sleep during spikes, longer during baseline
  const currentVUs = __VU;
  const sleepTime = currentVUs > 100 ? Math.random() * 0.2 : Math.random() * 1 + 0.5;
  sleep(sleepTime);
}

// Detect if we're in a spike scenario
function detectSpike(currentVUs) {
  const isCurrentlySpike = currentVUs > 100;

  if (isCurrentlySpike && !spikeDetected) {
    spikeDetected = true;
    spikeStartTime = Date.now();
    console.log('Spike detected at VU count:', currentVUs);
  } else if (!isCurrentlySpike && spikeDetected) {
    spikeDetected = false;
    recoveryStartTime = Date.now();
    console.log('Spike ended, recovery started');
  }

  return isCurrentlySpike;
}

// Handle spike scenario - fast, concurrent operations
function handleSpikeScenario(userSession, data) {
  const baseUrl = userSession.baseUrl;

  const spikeStart = Date.now();

  // Scenario 1: Quick API operations (70% during spike)
  if (Math.random() < 0.7) {
    quickApiOperations(userSession, data);
  }
  // Scenario 2: Cached data retrieval (20% during spike)
  else if (Math.random() < 0.9) {
    cachedDataRetrieval(userSession, data);
  }
  // Scenario 3: Health checks and status (10% during spike)
  else {
    healthAndStatusChecks(userSession);
  }

  const spikeResponseTime = Date.now() - spikeStart;
  customMetrics.spikeResponseTime = customMetrics.spikeResponseTime || new Trend('spike_response_time');
  customMetrics.spikeResponseTime.add(spikeResponseTime);
}

// Handle baseline scenario - normal operations
function handleBaselineScenario(userSession, data) {
  if (!baselineEstablished) {
    baselineEstablished = true;
    console.log('Baseline scenario established');
  }

  // If we just finished a spike, measure recovery
  if (recoveryStartTime && Date.now() - recoveryStartTime < 120000) {
    measureRecoveryPerformance(userSession, data);
  } else {
    // Normal baseline operations
    const scenarioType = Math.random();

    if (scenarioType < 0.5) {
      standardResearchWorkflow(userSession, data);
    } else {
      lightAnalysisScenario(userSession, data);
    }
  }
}

// Quick API operations optimized for spike handling
function quickApiOperations(userSession, data) {
  const baseUrl = userSession.baseUrl;

  // 1. Fast dataset listing
  let response = withRetry(() =>
    http.get(`${baseUrl}/api/datasets?limit=10`, {
      headers: userSession.getHeaders(),
      timeout: '5s',
    }),
    1 // Single retry for spikes
  );

  const success = check(response, {
    'quick dataset list': (r) => r.status === 200 || r.status === 503,
    'quick response time': (r) => r.timings.duration < 5000,
  });

  if (!success) spikeErrors.add(1);

  // 2. Simple search query
  const quickQuery = data.spikeScenarios[Math.floor(Math.random() * data.spikeScenarios.length)];

  response = withRetry(() =>
    http.get(`${baseUrl}/api/search?q=${encodeURIComponent(quickQuery.query)}&limit=5`, {
      headers: userSession.getHeaders(),
      timeout: '3s',
    }),
    1
  );

  check(response, {
    'quick search': (r) => r.status === 200 || r.status === 503,
    'search response time': (r) => r.timings.duration < 3000,
  });

  // 3. User profile check (should be cached)
  response = withRetry(() =>
    http.get(`${baseUrl}/api/user/profile`, {
      headers: userSession.getHeaders(),
      timeout: '2s',
    }),
    1
  );

  check(response, {
    'profile check': (r) => r.status === 200 || r.status === 503,
    'profile fast response': (r) => r.timings.duration < 2000,
  });
}

// Cached data retrieval during spikes
function cachedDataRetrieval(userSession, data) {
  const baseUrl = userSession.baseUrl;

  // 1. Cached analysis results
  let response = withRetry(() =>
    http.get(`${baseUrl}/api/analysis/recent?limit=5`, {
      headers: {
        ...userSession.getHeaders(),
        'Cache-Control': 'max-age=300' // Request cached data
      },
      timeout: '3s',
    }),
    1
  );

  check(response, {
    'cached results': (r) => r.status === 200 || r.status === 304 || r.status === 503,
    'cached response fast': (r) => r.timings.duration < 3000,
  });

  // 2. Cached knowledge graph entities
  response = withRetry(() =>
    http.get(`${baseUrl}/api/kg/popular-entities?limit=10`, {
      headers: {
        ...userSession.getHeaders(),
        'Cache-Control': 'max-age=600'
      },
      timeout: '2s',
    }),
    1
  );

  check(response, {
    'cached entities': (r) => r.status === 200 || r.status === 304 || r.status === 503,
  });

  // 3. System statistics (should be cached/pre-computed)
  response = withRetry(() =>
    http.get(`${baseUrl}/api/stats/dashboard`, {
      headers: userSession.getHeaders(),
      timeout: '2s',
    }),
    1
  );

  check(response, {
    'dashboard stats': (r) => r.status === 200 || r.status === 503,
    'stats fast response': (r) => r.timings.duration < 2000,
  });
}

// Health and status checks during spikes
function healthAndStatusChecks(userSession) {
  const baseUrl = userSession.baseUrl;

  // 1. Health check endpoint
  let response = http.get(`${baseUrl}/health`, {
    timeout: '1s',
  });

  check(response, {
    'health check available': (r) => r.status === 200 || r.status === 503,
    'health check fast': (r) => r.timings.duration < 1000,
  });

  // 2. Service status
  response = http.get(`${baseUrl}/api/status`, {
    headers: userSession.getHeaders(),
    timeout: '2s',
  });

  check(response, {
    'status check': (r) => r.status === 200 || r.status === 503,
  });

  // 3. Load balancer status
  response = http.get(`${baseUrl}/api/load-balancer/health`, {
    timeout: '1s',
  });

  check(response, {
    'load balancer check': (r) => r.status === 200 || r.status === 503,
  });
}

// Standard research workflow for baseline
function standardResearchWorkflow(userSession, data) {
  const baseUrl = userSession.baseUrl;

  // 1. Browse available datasets
  let response = withRetry(() =>
    http.get(`${baseUrl}/api/datasets`, {
      headers: userSession.getHeaders(),
    })
  );

  check(response, {
    'baseline dataset browse': (r) => r.status === 200,
    'baseline response time': (r) => r.timings.duration < 2000,
  });

  sleep(1);

  // 2. Submit light analysis
  const lightRequest = data.analysisRequests.find(req => req.complexity === 'low') ||
                       data.analysisRequests[0];

  response = withRetry(() =>
    http.post(`${baseUrl}/api/analysis/light`, JSON.stringify(lightRequest), {
      headers: {
        ...userSession.getHeaders(),
        'Content-Type': 'application/json',
      },
    })
  );

  check(response, {
    'light analysis submitted': (r) => r.status === 202,
  });

  const jobId = response.json('job_id');
  if (jobId) {
    // Check status once
    response = withRetry(() =>
      http.get(`${baseUrl}/api/analysis/${jobId}/status`, {
        headers: userSession.getHeaders(),
      })
    );

    check(response, {
      'analysis status check': (r) => r.status === 200,
    });
  }
}

// Light analysis scenario
function lightAnalysisScenario(userSession, data) {
  const baseUrl = userSession.baseUrl;

  // Simple knowledge graph query
  const simpleQuery = data.knowledgeGraphQueries.find(q => q.complexity === 'low') ||
                      data.knowledgeGraphQueries[0];

  let response = withRetry(() =>
    http.post(`${baseUrl}/api/kg/search/simple`, JSON.stringify({
      query: simpleQuery.text,
      limit: 10
    }), {
      headers: {
        ...userSession.getHeaders(),
        'Content-Type': 'application/json',
      },
    })
  );

  check(response, {
    'simple KG search': (r) => r.status === 200,
    'KG response time OK': (r) => r.timings.duration < 3000,
  });
}

// Measure recovery performance after spike
function measureRecoveryPerformance(userSession, data) {
  const recoveryStart = Date.now();

  // Try a standard operation to measure recovery
  standardResearchWorkflow(userSession, data);

  const recoveryDuration = Date.now() - recoveryStart;
  recoveryTime.add(recoveryDuration);

  console.log(`Recovery operation took ${recoveryDuration}ms`);
}

// Monitor auto-scaling during spikes
function monitorSpikeAutoScaling(baseUrl) {
  if (spikeDetected && spikeStartTime) {
    const scalingMetrics = monitorAutoScaling(baseUrl);

    if (scalingMetrics.responseTime) {
      const spikeLatency = Date.now() - spikeStartTime;
      autoScaleLatency.add(spikeLatency);

      console.log(`Auto-scaling response to spike: ${scalingMetrics.responseTime}ms, total spike latency: ${spikeLatency}ms`);
    }
  }
}

// Generate quick operations for spike testing
function generateQuickOperations(count) {
  const operations = [];
  const operationTypes = ['list', 'search', 'status', 'profile', 'cache'];

  for (let i = 0; i < count; i++) {
    operations.push({
      type: operationTypes[Math.floor(Math.random() * operationTypes.length)],
      params: {
        limit: Math.floor(Math.random() * 10) + 1,
        timeout: Math.floor(Math.random() * 3) + 1
      }
    });
  }

  return operations;
}

// Generate spike-specific test scenarios
function generateSpikeScenarios(count) {
  const scenarios = [];
  const queries = [
    'fmri', 'brain', 'analysis', 'study', 'data',
    'cortex', 'connectivity', 'activation', 'network', 'roi'
  ];

  for (let i = 0; i < count; i++) {
    scenarios.push({
      query: queries[Math.floor(Math.random() * queries.length)],
      type: 'quick',
      expectedTime: Math.random() * 1000 + 500
    });
  }

  return scenarios;
}

// Capture baseline metrics
function captureBaselineMetrics(baseUrl) {
  const healthStatus = healthCheck(baseUrl);
  const scalingStatus = monitorAutoScaling(baseUrl);

  return {
    health: healthStatus,
    scaling: scalingStatus,
    timestamp: Date.now()
  };
}

export function teardown(data) {
  console.log('Tearing down spike test...');

  // Final health check
  const healthStatus = healthCheck(__ENV.BASE_URL || 'http://localhost');
  console.log('Final health status:', JSON.stringify(healthStatus, null, 2));

  // Generate spike test report
  const spikeReport = {
    totalSpikeErrors: spikeErrors.value,
    baselineEstablished: baselineEstablished,
    spikesDetected: spikeStartTime !== null,
    averageRecoveryTime: recoveryTime.values.length > 0 ?
      recoveryTime.values.reduce((a, b) => a + b, 0) / recoveryTime.values.length : 0,
    maxAutoScaleLatency: autoScaleLatency.values.length > 0 ?
      Math.max(...autoScaleLatency.values) : 0
  };

  console.log('Spike test report:', JSON.stringify(spikeReport, null, 2));

  // Performance validation
  const finalValidation = validator.generateReport();
  console.log('Performance validation results:', JSON.stringify(finalValidation, null, 2));

  console.log('Spike test teardown complete');
}