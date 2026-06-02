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

// Custom metrics
const customMetrics = createCustomMetrics();

// Stress test configuration - aggressive scaling to find breaking point
export let options = {
  stages: [
    { duration: '2m', target: 20 },    // Ramp-up to 20 users
    { duration: '5m', target: 50 },    // Scale to 50 users
    { duration: '5m', target: 100 },   // Scale to 100 users
    { duration: '5m', target: 200 },   // Scale to 200 users
    { duration: '5m', target: 300 },   // Scale to 300 users (stress level)
    { duration: '5m', target: 500 },   // Scale to 500 users (high stress)
    { duration: '10m', target: 500 },  // Sustain high stress
    { duration: '5m', target: 300 },   // Scale back down
    { duration: '5m', target: 100 },   // Continue scaling down
    { duration: '3m', target: 0 },     // Ramp down to 0
  ],
  thresholds: {
    'http_req_duration': ['p(95)<2000', 'p(99)<5000'], // More lenient for stress test
    'http_req_failed': ['rate<0.05'], // Allow higher error rate
    'analysis_request_duration': ['p(90)<60000'], // Allow longer analysis times
    'websocket_connection_time': ['p(95)<3000'],
    'file_upload_duration': ['p(90)<120000'],
    'auto_scaling_response_time': ['p(95)<300000'], // 5 minutes for scaling
  },
};

// Test data generator
const dataGen = new DataGenerator();

// Performance validator with stress test settings
const validator = new PerformanceValidator({
  maxResponseTime: 2000, // More lenient
  maxErrorRate: 0.05,    // Allow 5% error rate
  minThroughput: 50      // Higher throughput requirement
});

// Error tracking
const stressErrors = new Counter('stress_test_errors');
const degradationStart = new Gauge('degradation_start_time');
const recoveryTime = new Trend('recovery_time');

export function setup() {
  console.log('Setting up stress test...');

  // Generate more test data for stress test
  const testData = {
    users: dataGen.generateUsers(1000), // More users for stress
    analysisRequests: dataGen.generateAnalysisRequests(500),
    knowledgeGraphQueries: dataGen.generateKnowledgeGraphQueries(200),
    heavyQueries: dataGen.generateHeavyAnalysisRequests(50) // CPU intensive requests
  };

  // Initial health check
  const healthStatus = healthCheck(__ENV.BASE_URL || 'http://localhost');
  if (!healthStatus.healthy) {
    throw new Error(`Health check failed: ${healthStatus.message}`);
  }

  // Check auto-scaling status
  const scalingStatus = monitorAutoScaling(__ENV.BASE_URL || 'http://localhost');
  console.log('Initial scaling status:', JSON.stringify(scalingStatus, null, 2));

  console.log('Stress test setup complete');
  return testData;
}

export default function(data) {
  const baseUrl = __ENV.BASE_URL || 'http://localhost';
  const user = data.users[Math.floor(Math.random() * data.users.length)];
  const userSession = new UserSession(user, baseUrl);

  userSession.start();

  try {
    const scenarioType = Math.random();

    // Scenario distribution for stress test
    if (scenarioType < 0.4) {
      // 40% - Heavy computational workload
      heavyComputationScenario(userSession, data);
    } else if (scenarioType < 0.7) {
      // 30% - Concurrent file uploads
      concurrentUploadScenario(userSession, data);
    } else if (scenarioType < 0.9) {
      // 20% - Database intensive queries
      databaseIntensiveScenario(userSession, data);
    } else {
      // 10% - Memory intensive operations
      memoryIntensiveScenario(userSession, data);
    }

  } catch (error) {
    stressErrors.add(1);
    console.error(`Stress test error for user ${user.username}: ${error}`);
  } finally {
    userSession.end();
  }

  // Monitor system health during stress
  monitorSystemHealth(baseUrl);

  // Minimal sleep during stress test
  sleep(Math.random() * 0.5);
}

// Heavy computation scenario
function heavyComputationScenario(userSession, data) {
  const baseUrl = userSession.baseUrl;

  // 1. Submit multiple heavy analysis requests
  const heavyRequest = data.heavyQueries[Math.floor(Math.random() * data.heavyQueries.length)];

  const analysisStart = Date.now();
  let response = withRetry(() =>
    http.post(`${baseUrl}/api/analysis/heavy`, JSON.stringify(heavyRequest), {
      headers: {
        ...userSession.getHeaders(),
        'Content-Type': 'application/json',
      },
      timeout: '60s',
    }),
    3 // More retries for stress test
  );

  const analysisDuration = Date.now() - analysisStart;
  customMetrics.analysisRequestDuration.add(analysisDuration);

  const success = check(response, {
    'heavy analysis submitted': (r) => r.status === 202 || r.status === 503, // Allow service unavailable
    'analysis not timing out': (r) => r.timings.duration < 60000,
  });

  if (!success) {
    stressErrors.add(1);
  }

  // 2. Parallel GLM analysis requests
  const glmRequests = data.analysisRequests.filter(req => req.type === 'glm').slice(0, 3);
  const promises = glmRequests.map(req =>
    http.post(`${baseUrl}/api/analysis/glm`, JSON.stringify(req), {
      headers: {
        ...userSession.getHeaders(),
        'Content-Type': 'application/json',
      },
    })
  );

  // Simulate parallel execution
  promises.forEach((response, index) => {
    check(response, {
      [`parallel GLM ${index} submitted`]: (r) => r.status === 202 || r.status === 429, // Allow rate limiting
    });
  });

  sleep(0.1); // Minimal sleep
}

// Concurrent file upload scenario
function concurrentUploadScenario(userSession, data) {
  const baseUrl = userSession.baseUrl;

  // 1. Upload multiple files concurrently
  const fileCount = Math.floor(Math.random() * 5) + 1;

  for (let i = 0; i < fileCount; i++) {
    const fileData = dataGen.generateFileUpload(Math.random() * 100 + 50); // 50-150MB files

    const uploadStart = Date.now();
    let response = withRetry(() =>
      http.post(`${baseUrl}/api/upload`, fileData, {
        headers: {
          ...userSession.getHeaders(),
          'Content-Type': 'multipart/form-data',
        },
        timeout: '120s',
      }),
      2
    );

    const uploadDuration = Date.now() - uploadStart;
    customMetrics.fileUploadDuration.add(uploadDuration);

    const success = check(response, {
      [`file upload ${i} handled`]: (r) => r.status === 200 || r.status === 413 || r.status === 507, // Allow file size/space errors
      [`upload ${i} reasonable time`]: (r) => r.timings.duration < 120000,
    });

    if (!success) {
      stressErrors.add(1);
    }

    // Small gap between uploads
    sleep(0.05);
  }

  // 2. Process uploaded files
  let response = withRetry(() =>
    http.post(`${baseUrl}/api/process/batch`, JSON.stringify({
      operation: 'preprocess',
      parallel: true
    }), {
      headers: {
        ...userSession.getHeaders(),
        'Content-Type': 'application/json',
      },
    })
  );

  check(response, {
    'batch processing initiated': (r) => r.status === 202 || r.status === 503,
  });
}

// Database intensive scenario
function databaseIntensiveScenario(userSession, data) {
  const baseUrl = userSession.baseUrl;

  // 1. Complex knowledge graph queries
  const complexQueries = data.knowledgeGraphQueries.filter(q => q.complexity === 'high');

  complexQueries.slice(0, 5).forEach((query, index) => {
    let response = withRetry(() =>
      http.post(`${baseUrl}/api/kg/query/complex`, JSON.stringify({
        query: query.text,
        depth: 5,
        limit: 1000
      }), {
        headers: {
          ...userSession.getHeaders(),
          'Content-Type': 'application/json',
        },
        timeout: '30s',
      })
    );

    const success = check(response, {
      [`complex query ${index} handled`]: (r) => r.status === 200 || r.status === 504, // Allow gateway timeout
      [`query ${index} reasonable time`]: (r) => r.timings.duration < 30000,
    });

    if (!success) {
      stressErrors.add(1);
    }
  });

  // 2. Aggregate data queries
  let response = withRetry(() =>
    http.get(`${baseUrl}/api/analytics/aggregates?timeRange=all&groupBy=multiple`, {
      headers: userSession.getHeaders(),
      timeout: '45s',
    })
  );

  check(response, {
    'aggregates query handled': (r) => r.status === 200 || r.status === 504,
    'aggregates reasonable time': (r) => r.timings.duration < 45000,
  });

  // 3. Full-text search
  response = withRetry(() =>
    http.get(`${baseUrl}/api/search?q=fmri+analysis+connectivity&limit=500`, {
      headers: userSession.getHeaders(),
    })
  );

  check(response, {
    'full-text search handled': (r) => r.status === 200 || r.status === 503,
  });
}

// Memory intensive scenario
function memoryIntensiveScenario(userSession, data) {
  const baseUrl = userSession.baseUrl;

  // 1. Large dataset loading
  let response = withRetry(() =>
    http.post(`${baseUrl}/api/datasets/load/large`, JSON.stringify({
      datasetId: 'large_fmri_dataset',
      loadInMemory: true,
      preprocessing: ['smooth', 'normalize', 'mask']
    }), {
      headers: {
        ...userSession.getHeaders(),
        'Content-Type': 'application/json',
      },
      timeout: '90s',
    })
  );

  const success = check(response, {
    'large dataset loading handled': (r) => r.status === 202 || r.status === 507, // Allow insufficient storage
    'dataset loading reasonable time': (r) => r.timings.duration < 90000,
  });

  if (!success) {
    stressErrors.add(1);
  }

  // 2. Memory intensive visualization
  response = withRetry(() =>
    http.post(`${baseUrl}/api/visualize/brain/4d`, JSON.stringify({
      resolution: 'high',
      timePoints: 200,
      overlays: ['statistical', 'anatomical', 'functional']
    }), {
      headers: {
        ...userSession.getHeaders(),
        'Content-Type': 'application/json',
      },
      timeout: '60s',
    })
  );

  check(response, {
    '4D visualization handled': (r) => r.status === 200 || r.status === 507,
    'visualization reasonable time': (r) => r.timings.duration < 60000,
  });

  // 3. In-memory analytics
  response = withRetry(() =>
    http.get(`${baseUrl}/api/analytics/memory-intensive?operation=pca&components=50`, {
      headers: userSession.getHeaders(),
      timeout: '120s',
    })
  );

  check(response, {
    'memory analytics handled': (r) => r.status === 200 || r.status === 507,
  });
}

// System health monitoring during stress
function monitorSystemHealth(baseUrl) {
  // Check system metrics
  let response = http.get(`${baseUrl}/api/health/metrics`, {
    timeout: '5s',
  });

  if (response.status === 200) {
    const metrics = response.json();

    // Track CPU usage
    if (metrics.cpu && metrics.cpu.usage > 90) {
      console.warn('High CPU usage detected:', metrics.cpu.usage);
    }

    // Track memory usage
    if (metrics.memory && metrics.memory.usage > 85) {
      console.warn('High memory usage detected:', metrics.memory.usage);
    }

    // Track response times
    if (metrics.responseTime && metrics.responseTime > 5000) {
      console.warn('High response times detected:', metrics.responseTime);

      // Mark potential degradation start
      if (!degradationStart.value) {
        degradationStart.set(Date.now());
      }
    } else if (degradationStart.value && metrics.responseTime < 1000) {
      // System recovered
      const recoveryDuration = Date.now() - degradationStart.value;
      recoveryTime.add(recoveryDuration);
      degradationStart.set(0);
      console.log('System recovery detected, duration:', recoveryDuration);
    }
  }

  // Check auto-scaling response
  const scalingMetrics = monitorAutoScaling(baseUrl);
  if (scalingMetrics.responseTime) {
    customMetrics.autoScalingResponseTime.add(scalingMetrics.responseTime);
  }
}

export function teardown(data) {
  console.log('Tearing down stress test...');

  // Final health check
  const healthStatus = healthCheck(__ENV.BASE_URL || 'http://localhost');
  console.log('Final health status:', JSON.stringify(healthStatus, null, 2));

  // Final scaling check
  const scalingStatus = monitorAutoScaling(__ENV.BASE_URL || 'http://localhost');
  console.log('Final scaling status:', JSON.stringify(scalingStatus, null, 2));

  // Generate stress test report
  const stressReport = {
    totalErrors: stressErrors.value,
    degradationDetected: degradationStart.value > 0,
    systemRecovered: recoveryTime.values.length > 0,
    averageRecoveryTime: recoveryTime.values.length > 0 ?
      recoveryTime.values.reduce((a, b) => a + b, 0) / recoveryTime.values.length : 0
  };

  console.log('Stress test report:', JSON.stringify(stressReport, null, 2));

  // Performance validation
  const finalValidation = validator.generateReport();
  console.log('Performance validation results:', JSON.stringify(finalValidation, null, 2));

  console.log('Stress test teardown complete');
}