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

// Custom metrics for soak testing
const customMetrics = createCustomMetrics();
const memoryLeakIndicator = new Gauge('memory_leak_indicator');
const connectionLeaks = new Counter('connection_leaks');
const performanceDrift = new Trend('performance_drift');
const resourceExhaustion = new Counter('resource_exhaustion_events');
const longRunningOperations = new Trend('long_running_operations');

// Soak test configuration - extended duration with moderate load
export let options = {
  stages: [
    { duration: '5m', target: 20 },    // Ramp up to moderate load
    { duration: '15m', target: 30 },   // Increase slightly
    { duration: '2h', target: 30 },    // Main soak period - 2 hours
    { duration: '15m', target: 25 },   // Slight decrease
    { duration: '1h', target: 25 },    // Continue soak - 1 hour
    { duration: '15m', target: 20 },   // Decrease
    { duration: '30m', target: 20 },   // Final soak period
    { duration: '5m', target: 0 },     // Ramp down
  ],
  thresholds: {
    'http_req_duration': ['p(95)<1000', 'p(99)<2000'],
    'http_req_failed': ['rate<0.005'], // Very low error rate for soak
    'analysis_request_duration': ['p(90)<45000'],
    'websocket_connection_time': ['p(95)<2000'],
    'memory_leak_indicator': ['value<1000'], // Memory growth threshold
    'performance_drift': ['p(95)<200'], // Performance degradation threshold
    'long_running_operations': ['p(90)<300000'], // 5 minute max for long ops
  },
};

// Test data generator
const dataGen = new DataGenerator();

// Performance validator for soak testing
const validator = new PerformanceValidator({
  maxResponseTime: 1000,
  maxErrorRate: 0.005,
  minThroughput: 15
});

// Soak test monitoring variables
let testStartTime = Date.now();
let baselineMetrics = null;
let memoryBaseline = null;
let performanceBaseline = null;
let checkpointInterval = 300000; // 5 minutes
let nextCheckpoint = Date.now() + checkpointInterval;

export function setup() {
  console.log('Setting up soak test...');

  // Generate comprehensive test data for long duration
  const testData = {
    users: dataGen.generateUsers(200),
    analysisRequests: dataGen.generateAnalysisRequests(500),
    knowledgeGraphQueries: dataGen.generateKnowledgeGraphQueries(300),
    longRunningTasks: generateLongRunningTasks(100),
    periodicTasks: generatePeriodicTasks(50),
    stressOperations: generateStressOperations(200)
  };

  // Initial health check and baseline establishment
  const healthStatus = healthCheck(__ENV.BASE_URL || 'http://localhost');
  if (!healthStatus.healthy) {
    throw new Error(`Health check failed: ${healthStatus.message}`);
  }

  // Capture baseline metrics
  baselineMetrics = captureDetailedMetrics(__ENV.BASE_URL || 'http://localhost');
  console.log('Baseline metrics established:', JSON.stringify(baselineMetrics, null, 2));

  // Set memory and performance baselines
  memoryBaseline = baselineMetrics.memory || 0;
  performanceBaseline = baselineMetrics.avgResponseTime || 0;

  console.log('Soak test setup complete - starting long duration test');
  return testData;
}

export default function(data) {
  const baseUrl = __ENV.BASE_URL || 'http://localhost';
  const user = data.users[Math.floor(Math.random() * data.users.length)];
  const userSession = new UserSession(user, baseUrl);

  userSession.start();

  try {
    // Checkpoint monitoring
    if (Date.now() >= nextCheckpoint) {
      performCheckpointMonitoring(baseUrl);
      nextCheckpoint = Date.now() + checkpointInterval;
    }

    // Scenario selection based on test duration
    const elapsedTime = Date.now() - testStartTime;
    const scenario = selectSoakScenario(elapsedTime);

    switch (scenario) {
      case 'standard_workflow':
        standardWorkflowScenario(userSession, data);
        break;
      case 'long_running_analysis':
        longRunningAnalysisScenario(userSession, data);
        break;
      case 'memory_intensive':
        memoryIntensiveScenario(userSession, data);
        break;
      case 'connection_heavy':
        connectionHeavyScenario(userSession, data);
        break;
      case 'periodic_tasks':
        periodicTasksScenario(userSession, data);
        break;
      default:
        standardWorkflowScenario(userSession, data);
    }

  } catch (error) {
    console.error(`Soak test error for user ${user.username}: ${error}`);
  } finally {
    userSession.end();
  }

  // Monitor for memory leaks and performance drift
  monitorResourceHealth(baseUrl);

  // Variable sleep to simulate realistic user behavior
  const elapsedHours = (Date.now() - testStartTime) / 3600000;
  const sleepTime = Math.random() * 3 + 1 + (elapsedHours * 0.1); // Slightly longer sleep over time
  sleep(sleepTime);
}

// Select scenario based on test duration
function selectSoakScenario(elapsedTime) {
  const elapsedHours = elapsedTime / 3600000;

  // First hour: standard workflows
  if (elapsedHours < 1) {
    return Math.random() < 0.8 ? 'standard_workflow' : 'memory_intensive';
  }
  // Second hour: introduce long-running tasks
  else if (elapsedHours < 2) {
    const rand = Math.random();
    if (rand < 0.4) return 'standard_workflow';
    if (rand < 0.7) return 'long_running_analysis';
    if (rand < 0.9) return 'memory_intensive';
    return 'connection_heavy';
  }
  // Third hour and beyond: full scenario mix with periodic tasks
  else {
    const rand = Math.random();
    if (rand < 0.3) return 'standard_workflow';
    if (rand < 0.5) return 'long_running_analysis';
    if (rand < 0.7) return 'memory_intensive';
    if (rand < 0.85) return 'connection_heavy';
    return 'periodic_tasks';
  }
}

// Standard workflow scenario for baseline operations
function standardWorkflowScenario(userSession, data) {
  const baseUrl = userSession.baseUrl;

  // 1. Dataset browsing
  let response = withRetry(() =>
    http.get(`${baseUrl}/api/datasets?limit=20`, {
      headers: userSession.getHeaders(),
    })
  );

  check(response, {
    'datasets loaded': (r) => r.status === 200,
    'datasets response time': (r) => r.timings.duration < 2000,
  });

  sleep(Math.random() * 2 + 1);

  // 2. Simple analysis submission
  const analysisRequest = data.analysisRequests[Math.floor(Math.random() * data.analysisRequests.length)];

  response = withRetry(() =>
    http.post(`${baseUrl}/api/analysis`, JSON.stringify(analysisRequest), {
      headers: {
        ...userSession.getHeaders(),
        'Content-Type': 'application/json',
      },
    })
  );

  check(response, {
    'analysis submitted': (r) => r.status === 202,
    'submission response time': (r) => r.timings.duration < 3000,
  });

  const jobId = response.json('job_id');

  // 3. Status monitoring
  if (jobId) {
    monitorJobProgress(userSession, jobId, 30000); // Monitor for 30 seconds
  }

  sleep(Math.random() * 3 + 2);

  // 4. Knowledge graph exploration
  const kgQuery = data.knowledgeGraphQueries[Math.floor(Math.random() * data.knowledgeGraphQueries.length)];

  response = withRetry(() =>
    http.post(`${baseUrl}/api/kg/search`, JSON.stringify({ query: kgQuery.text }), {
      headers: {
        ...userSession.getHeaders(),
        'Content-Type': 'application/json',
      },
    })
  );

  check(response, {
    'KG search completed': (r) => r.status === 200,
    'KG search response time': (r) => r.timings.duration < 5000,
  });
}

// Long-running analysis scenario
function longRunningAnalysisScenario(userSession, data) {
  const baseUrl = userSession.baseUrl;

  const longTask = data.longRunningTasks[Math.floor(Math.random() * data.longRunningTasks.length)];

  const taskStart = Date.now();
  let response = withRetry(() =>
    http.post(`${baseUrl}/api/analysis/long-running`, JSON.stringify(longTask), {
      headers: {
        ...userSession.getHeaders(),
        'Content-Type': 'application/json',
      },
      timeout: '60s',
    })
  );

  check(response, {
    'long task submitted': (r) => r.status === 202,
    'long task submission time': (r) => r.timings.duration < 60000,
  });

  const jobId = response.json('job_id');

  if (jobId) {
    // Monitor long-running task for extended period
    const finalDuration = monitorJobProgress(userSession, jobId, 300000); // 5 minutes max
    longRunningOperations.add(finalDuration);
  }
}

// Memory intensive scenario to detect leaks
function memoryIntensiveScenario(userSession, data) {
  const baseUrl = userSession.baseUrl;

  // 1. Large dataset processing
  let response = withRetry(() =>
    http.post(`${baseUrl}/api/datasets/process-large`, JSON.stringify({
      operation: 'load_and_analyze',
      cacheResults: false, // Force memory usage
      processInMemory: true
    }), {
      headers: {
        ...userSession.getHeaders(),
        'Content-Type': 'application/json',
      },
      timeout: '120s',
    })
  );

  check(response, {
    'large dataset processing': (r) => r.status === 202 || r.status === 507, // Allow out of memory
    'processing submission time': (r) => r.timings.duration < 120000,
  });

  sleep(5);

  // 2. Memory-intensive visualization
  response = withRetry(() =>
    http.post(`${baseUrl}/api/visualize/memory-intensive`, JSON.stringify({
      type: '4d_brain_activation',
      resolution: 'high',
      timePoints: 500,
      generateThumbnails: true
    }), {
      headers: {
        ...userSession.getHeaders(),
        'Content-Type': 'application/json',
      },
      timeout: '90s',
    })
  );

  check(response, {
    'memory visualization': (r) => r.status === 200 || r.status === 507,
  });

  sleep(10);

  // 3. Bulk operations
  const bulkOperations = Array.from({ length: 10 }, (_, i) => ({
    operation: `bulk_op_${i}`,
    data: data.stressOperations[i % data.stressOperations.length]
  }));

  response = withRetry(() =>
    http.post(`${baseUrl}/api/bulk/process`, JSON.stringify(bulkOperations), {
      headers: {
        ...userSession.getHeaders(),
        'Content-Type': 'application/json',
      },
    })
  );

  check(response, {
    'bulk operations': (r) => r.status === 202,
  });
}

// Connection-heavy scenario to test connection pooling
function connectionHeavyScenario(userSession, data) {
  const baseUrl = userSession.baseUrl;

  // Create multiple concurrent connections
  const concurrentRequests = Array.from({ length: 5 }, (_, i) =>
    withRetry(() =>
      http.get(`${baseUrl}/api/concurrent-test/${i}`, {
        headers: userSession.getHeaders(),
      })
    )
  );

  // Check if connections are handled properly
  concurrentRequests.forEach((response, index) => {
    const success = check(response, {
      [`concurrent request ${index}`]: (r) => r.status === 200 || r.status === 503,
    });

    if (!success) {
      connectionLeaks.add(1);
    }
  });

  sleep(2);

  // Database connection stress
  let response = withRetry(() =>
    http.post(`${baseUrl}/api/database/stress-test`, JSON.stringify({
      connections: 20,
      duration: 30000,
      queries: ['SELECT', 'INSERT', 'UPDATE']
    }), {
      headers: {
        ...userSession.getHeaders(),
        'Content-Type': 'application/json',
      },
    })
  );

  check(response, {
    'database stress test': (r) => r.status === 200 || r.status === 503,
  });
}

// Periodic tasks scenario
function periodicTasksScenario(userSession, data) {
  const baseUrl = userSession.baseUrl;

  const periodicTask = data.periodicTasks[Math.floor(Math.random() * data.periodicTasks.length)];

  let response = withRetry(() =>
    http.post(`${baseUrl}/api/tasks/periodic`, JSON.stringify(periodicTask), {
      headers: {
        ...userSession.getHeaders(),
        'Content-Type': 'application/json',
      },
    })
  );

  check(response, {
    'periodic task scheduled': (r) => r.status === 200,
  });

  // Check task status
  sleep(5);

  response = withRetry(() =>
    http.get(`${baseUrl}/api/tasks/status`, {
      headers: userSession.getHeaders(),
    })
  );

  check(response, {
    'task status retrieved': (r) => r.status === 200,
  });
}

// Monitor job progress for a specified duration
function monitorJobProgress(userSession, jobId, maxDuration) {
  const baseUrl = userSession.baseUrl;
  const startTime = Date.now();

  while (Date.now() - startTime < maxDuration) {
    const response = withRetry(() =>
      http.get(`${baseUrl}/api/analysis/${jobId}/status`, {
        headers: userSession.getHeaders(),
      })
    );

    if (response.status === 200) {
      const status = response.json();
      if (status && (status.status === 'completed' || status.status === 'failed')) {
        return Date.now() - startTime;
      }
    }

    sleep(10);
  }

  return maxDuration; // Timeout reached
}

// Perform checkpoint monitoring every 5 minutes
function performCheckpointMonitoring(baseUrl) {
  console.log('Performing checkpoint monitoring...');

  const currentMetrics = captureDetailedMetrics(baseUrl);

  // Check for memory leaks
  if (memoryBaseline && currentMetrics.memory) {
    const memoryIncrease = currentMetrics.memory - memoryBaseline;
    const memoryIncreasePercent = (memoryIncrease / memoryBaseline) * 100;

    memoryLeakIndicator.set(memoryIncreasePercent);

    if (memoryIncreasePercent > 50) {
      console.warn(`Potential memory leak detected: ${memoryIncreasePercent}% increase`);
    }
  }

  // Check for performance drift
  if (performanceBaseline && currentMetrics.avgResponseTime) {
    const performanceChange = currentMetrics.avgResponseTime - performanceBaseline;
    const performanceChangePercent = (performanceChange / performanceBaseline) * 100;

    performanceDrift.add(performanceChangePercent);

    if (performanceChangePercent > 25) {
      console.warn(`Performance drift detected: ${performanceChangePercent}% slower`);
    }
  }

  // Check for resource exhaustion
  if (currentMetrics.resourceExhausted) {
    resourceExhaustion.add(1);
    console.warn('Resource exhaustion detected');
  }

  console.log('Checkpoint metrics:', JSON.stringify(currentMetrics, null, 2));
}

// Monitor resource health continuously
function monitorResourceHealth(baseUrl) {
  const response = http.get(`${baseUrl}/api/health/resources`, {
    timeout: '5s',
  });

  if (response.status === 200) {
    const resources = response.json();

    // Check for resource warning signs
    if (resources.memory && resources.memory.usage > 90) {
      console.warn('High memory usage:', resources.memory.usage);
    }

    if (resources.connections && resources.connections.active > resources.connections.max * 0.9) {
      console.warn('High connection usage:', resources.connections.active);
    }

    if (resources.cpu && resources.cpu.usage > 85) {
      console.warn('High CPU usage:', resources.cpu.usage);
    }
  }
}

// Generate long-running task configurations
function generateLongRunningTasks(count) {
  const tasks = [];
  const taskTypes = ['connectivity_analysis', 'group_comparison', 'machine_learning', 'preprocessing'];

  for (let i = 0; i < count; i++) {
    tasks.push({
      type: taskTypes[Math.floor(Math.random() * taskTypes.length)],
      duration: Math.random() * 240000 + 60000, // 1-5 minutes
      complexity: 'high',
      resources: {
        memory: Math.random() * 4 + 2, // 2-6GB
        cpu: Math.random() * 4 + 2     // 2-6 cores
      }
    });
  }

  return tasks;
}

// Generate periodic task configurations
function generatePeriodicTasks(count) {
  const tasks = [];
  const intervals = [60000, 300000, 600000, 1800000]; // 1min, 5min, 10min, 30min

  for (let i = 0; i < count; i++) {
    tasks.push({
      name: `periodic_task_${i}`,
      interval: intervals[Math.floor(Math.random() * intervals.length)],
      action: 'cleanup',
      enabled: true
    });
  }

  return tasks;
}

// Generate stress operation configurations
function generateStressOperations(count) {
  const operations = [];

  for (let i = 0; i < count; i++) {
    operations.push({
      id: `stress_op_${i}`,
      type: 'computation',
      intensity: Math.random() * 0.8 + 0.2, // 20-100% intensity
      duration: Math.random() * 30000 + 5000 // 5-35 seconds
    });
  }

  return operations;
}

// Capture detailed system metrics
function captureDetailedMetrics(baseUrl) {
  try {
    const response = http.get(`${baseUrl}/api/metrics/detailed`, {
      timeout: '10s',
    });

    if (response.status === 200) {
      return response.json();
    }
  } catch (error) {
    console.warn('Failed to capture detailed metrics:', error);
  }

  return {
    memory: 0,
    avgResponseTime: 0,
    resourceExhausted: false,
    timestamp: Date.now()
  };
}

export function teardown(data) {
  console.log('Tearing down soak test...');

  const testDuration = Date.now() - testStartTime;
  const testHours = testDuration / 3600000;

  console.log(`Soak test completed after ${testHours.toFixed(2)} hours`);

  // Final comprehensive health check
  const healthStatus = healthCheck(__ENV.BASE_URL || 'http://localhost');
  const finalMetrics = captureDetailedMetrics(__ENV.BASE_URL || 'http://localhost');

  // Generate comprehensive soak test report
  const soakReport = {
    testDuration: testDuration,
    testDurationHours: testHours,
    finalHealthStatus: healthStatus,
    memoryLeakDetected: memoryLeakIndicator.value > 25,
    maxMemoryIncrease: memoryLeakIndicator.value,
    performanceDriftDetected: performanceDrift.values.some(v => v > 25),
    maxPerformanceDrift: Math.max(...(performanceDrift.values.length > 0 ? performanceDrift.values : [0])),
    connectionLeaks: connectionLeaks.value,
    resourceExhaustionEvents: resourceExhaustion.value,
    averageLongRunningTaskDuration: longRunningOperations.values.length > 0 ?
      longRunningOperations.values.reduce((a, b) => a + b, 0) / longRunningOperations.values.length : 0,
    finalMetrics: finalMetrics
  };

  console.log('Comprehensive soak test report:', JSON.stringify(soakReport, null, 2));

  // Performance validation
  const finalValidation = validator.generateReport();
  console.log('Performance validation results:', JSON.stringify(finalValidation, null, 2));

  console.log('Soak test teardown complete');
}