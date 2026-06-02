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

// Import environment configuration
import config from '../config/development.json';

// Custom metrics
const customMetrics = createCustomMetrics();

// Test configuration
export let options = {
  stages: [
    { duration: '2m', target: 10 },   // Ramp-up to 10 users
    { duration: '5m', target: 20 },   // Stay at 20 users
    { duration: '3m', target: 30 },   // Ramp to 30 users
    { duration: '5m', target: 30 },   // Stay at 30 users
    { duration: '2m', target: 0 },    // Ramp-down to 0 users
  ],
  thresholds: {
    'http_req_duration': ['p(95)<500'],
    'http_req_failed': ['rate<0.01'],
    'analysis_request_duration': ['p(90)<30000'],
    'websocket_connection_time': ['p(95)<1000'],
    'file_upload_duration': ['p(90)<60000'],
    'auto_scaling_response_time': ['p(95)<120000'],
  },
};

// Test data generator
const dataGen = new DataGenerator();

// Performance validator
const validator = new PerformanceValidator({
  maxResponseTime: 500,
  maxErrorRate: 0.01,
  minThroughput: 10
});

// Load test setup
export function setup() {
  console.log('Setting up load test...');

  // Generate test data
  const testData = {
    users: dataGen.generateUsers(50),
    analysisRequests: dataGen.generateAnalysisRequests(100),
    knowledgeGraphQueries: dataGen.generateKnowledgeGraphQueries(50)
  };

  // Perform initial health check
  const healthStatus = healthCheck(__ENV.BASE_URL || 'http://localhost');
  if (!healthStatus.healthy) {
    throw new Error(`Health check failed: ${healthStatus.message}`);
  }

  console.log('Load test setup complete');
  return testData;
}

// Main load test scenario
export default function(data) {
  const baseUrl = __ENV.BASE_URL || 'http://localhost';
  const user = data.users[Math.floor(Math.random() * data.users.length)];
  const userSession = new UserSession(user, baseUrl);

  // Start user session
  userSession.start();

  try {
    // Scenario 1: Researcher Workflow (60% of users)
    if (Math.random() < 0.6) {
      researcherWorkflow(userSession, data);
    }
    // Scenario 2: Data Analysis Session (30% of users)
    else if (Math.random() < 0.9) {
      dataAnalysisSession(userSession, data);
    }
    // Scenario 3: Knowledge Graph Exploration (10% of users)
    else {
      knowledgeGraphExploration(userSession, data);
    }

  } catch (error) {
    console.error(`Test error for user ${user.username}: ${error}`);
  } finally {
    userSession.end();
  }

  // Validate performance
  validator.validateResponse(userSession.getLastResponse());

  // Random think time
  sleep(Math.random() * 2 + 1);
}

// Researcher workflow scenario
function researcherWorkflow(userSession, data) {
  const baseUrl = userSession.baseUrl;

  // 1. Browse datasets
  let response = withRetry(() =>
    http.get(`${baseUrl}/api/datasets`, {
      headers: userSession.getHeaders(),
    })
  );

  check(response, {
    'datasets list loaded': (r) => r.status === 200,
    'datasets response time OK': (r) => r.timings.duration < 1000,
  });

  sleep(1);

  // 2. Select and view dataset details
  const datasets = response.json('datasets') || [];
  if (datasets.length > 0) {
    const selectedDataset = datasets[Math.floor(Math.random() * datasets.length)];

    response = withRetry(() =>
      http.get(`${baseUrl}/api/datasets/${selectedDataset.id}`, {
        headers: userSession.getHeaders(),
      })
    );

    check(response, {
      'dataset details loaded': (r) => r.status === 200,
      'dataset details response time OK': (r) => r.timings.duration < 2000,
    });
  }

  sleep(2);

  // 3. Run simple analysis
  const analysisRequest = data.analysisRequests[Math.floor(Math.random() * data.analysisRequests.length)];

  const analysisStart = Date.now();
  response = withRetry(() =>
    http.post(`${baseUrl}/api/analysis`, JSON.stringify(analysisRequest), {
      headers: {
        ...userSession.getHeaders(),
        'Content-Type': 'application/json',
      },
    })
  );

  const analysisDuration = Date.now() - analysisStart;
  customMetrics.analysisRequestDuration.add(analysisDuration);

  check(response, {
    'analysis submitted': (r) => r.status === 202,
    'analysis submission time OK': (r) => r.timings.duration < 5000,
  });

  const jobId = response.json('job_id');
  if (jobId) {
    // Poll for results
    pollAnalysisResults(userSession, jobId);
  }

  sleep(1);

  // 4. View results
  if (jobId) {
    response = withRetry(() =>
      http.get(`${baseUrl}/api/analysis/${jobId}/results`, {
        headers: userSession.getHeaders(),
      })
    );

    check(response, {
      'results retrieved': (r) => r.status === 200 || r.status === 202,
      'results response time OK': (r) => r.timings.duration < 3000,
    });
  }
}

// Data analysis session scenario
function dataAnalysisSession(userSession, data) {
  const baseUrl = userSession.baseUrl;

  // 1. Upload data file (simulated)
  const uploadStart = Date.now();
  const fileData = dataGen.generateFileUpload();

  let response = withRetry(() =>
    http.post(`${baseUrl}/api/upload`, fileData, {
      headers: {
        ...userSession.getHeaders(),
        'Content-Type': 'multipart/form-data',
      },
      timeout: '60s',
    })
  );

  const uploadDuration = Date.now() - uploadStart;
  customMetrics.fileUploadDuration.add(uploadDuration);

  check(response, {
    'file uploaded': (r) => r.status === 200,
    'upload time reasonable': (r) => r.timings.duration < 60000,
  });

  sleep(2);

  // 2. Configure complex analysis
  const complexAnalysis = data.analysisRequests.find(req => req.complexity === 'high') ||
                         data.analysisRequests[0];

  const analysisStart = Date.now();
  response = withRetry(() =>
    http.post(`${baseUrl}/api/analysis/complex`, JSON.stringify(complexAnalysis), {
      headers: {
        ...userSession.getHeaders(),
        'Content-Type': 'application/json',
      },
      timeout: '30s',
    })
  );

  const analysisDuration = Date.now() - analysisStart;
  customMetrics.analysisRequestDuration.add(analysisDuration);

  check(response, {
    'complex analysis submitted': (r) => r.status === 202,
    'complex analysis submission OK': (r) => r.timings.duration < 10000,
  });

  const jobId = response.json('job_id');

  // 3. Monitor progress
  if (jobId) {
    monitorAnalysisProgress(userSession, jobId);
  }

  sleep(3);

  // 4. Download results
  if (jobId) {
    response = withRetry(() =>
      http.get(`${baseUrl}/api/analysis/${jobId}/download`, {
        headers: userSession.getHeaders(),
      })
    );

    check(response, {
      'results downloaded': (r) => r.status === 200,
      'download response time OK': (r) => r.timings.duration < 30000,
    });
  }
}

// Knowledge graph exploration scenario
function knowledgeGraphExploration(userSession, data) {
  const baseUrl = userSession.baseUrl;

  // 1. Search knowledge graph
  const query = data.knowledgeGraphQueries[Math.floor(Math.random() * data.knowledgeGraphQueries.length)];

  let response = withRetry(() =>
    http.post(`${baseUrl}/api/kg/search`, JSON.stringify({ query: query.text }), {
      headers: {
        ...userSession.getHeaders(),
        'Content-Type': 'application/json',
      },
    })
  );

  check(response, {
    'KG search executed': (r) => r.status === 200,
    'KG search response time OK': (r) => r.timings.duration < 5000,
  });

  sleep(1);

  // 2. Explore related entities
  const searchResults = response.json() || [];
  if (searchResults.length > 0) {
    const entity = searchResults[0];

    response = withRetry(() =>
      http.get(`${baseUrl}/api/kg/entity/${entity.id}/related`, {
        headers: userSession.getHeaders(),
      })
    );

    check(response, {
      'related entities loaded': (r) => r.status === 200,
      'related entities response time OK': (r) => r.timings.duration < 3000,
    });
  }

  sleep(2);

  // 3. Visualize subgraph
  if (searchResults.length > 0) {
    response = withRetry(() =>
      http.get(`${baseUrl}/api/kg/visualize?entities=${searchResults.map(r => r.id).join(',')}`, {
        headers: userSession.getHeaders(),
      })
    );

    check(response, {
      'subgraph visualization loaded': (r) => r.status === 200,
      'visualization response time OK': (r) => r.timings.duration < 8000,
    });
  }
}

// Helper function to poll analysis results
function pollAnalysisResults(userSession, jobId) {
  const baseUrl = userSession.baseUrl;
  const maxPolls = 10;
  let polls = 0;

  while (polls < maxPolls) {
    const response = withRetry(() =>
      http.get(`${baseUrl}/api/analysis/${jobId}/status`, {
        headers: userSession.getHeaders(),
      })
    );

    check(response, {
      'status check successful': (r) => r.status === 200,
    });

    const status = response.json();
    if (status && (status.status === 'completed' || status.status === 'failed')) {
      break;
    }

    sleep(5);
    polls++;
  }
}

// Helper function to monitor analysis progress
function monitorAnalysisProgress(userSession, jobId) {
  const baseUrl = userSession.baseUrl;
  const startTime = Date.now();

  // Monitor for up to 2 minutes
  while (Date.now() - startTime < 120000) {
    const response = withRetry(() =>
      http.get(`${baseUrl}/api/analysis/${jobId}/progress`, {
        headers: userSession.getHeaders(),
      })
    );

    check(response, {
      'progress check successful': (r) => r.status === 200,
    });

    const progress = response.json();
    if (progress && progress.status === 'completed') {
      const totalTime = Date.now() - startTime;
      customMetrics.analysisRequestDuration.add(totalTime);
      break;
    }

    sleep(10);
  }
}

// Test teardown
export function teardown(data) {
  console.log('Tearing down load test...');

  // Monitor auto-scaling behavior
  const scalingMetrics = monitorAutoScaling(__ENV.BASE_URL || 'http://localhost');
  if (scalingMetrics.responseTime) {
    customMetrics.autoScalingResponseTime.add(scalingMetrics.responseTime);
  }

  // Validate final performance
  const finalValidation = validator.generateReport();
  console.log('Performance validation results:', JSON.stringify(finalValidation, null, 2));

  console.log('Load test teardown complete');
}