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

// Custom metrics for API endpoint testing
const customMetrics = createCustomMetrics();
const endpointErrors = new Counter('endpoint_errors');
const endpointLatencies = new Trend('endpoint_latencies');
const authFailures = new Counter('auth_failures');
const rateLimitHits = new Counter('rate_limit_hits');
const loadBalancerDistribution = new Counter('load_balancer_distribution');

// API endpoints test configuration
export let options = {
  stages: [
    { duration: '3m', target: 15 },    // Ramp up to 15 users
    { duration: '10m', target: 25 },   // Scale to 25 users
    { duration: '15m', target: 40 },   // Scale to 40 users - main test period
    { duration: '10m', target: 30 },   // Scale back slightly
    { duration: '5m', target: 15 },    // Scale down
    { duration: '2m', target: 0 },     // Ramp down
  ],
  thresholds: {
    'http_req_duration': ['p(95)<2000', 'p(99)<5000'],
    'http_req_failed': ['rate<0.01'], // 1% error rate
    'endpoint_latencies': ['p(95)<1500'],
    'auth_failures': ['rate<0.02'], // 2% auth failure rate
    'rate_limit_hits': ['rate<0.05'], // 5% rate limit threshold
  },
};

// Test data generator
const dataGen = new DataGenerator();

// Performance validator for API testing
const validator = new PerformanceValidator({
  maxResponseTime: 2000,
  maxErrorRate: 0.01,
  minThroughput: 25
});

// Define all API endpoints to test
const API_ENDPOINTS = {
  // Authentication endpoints
  auth: {
    login: { method: 'POST', path: '/api/auth/login', requiresAuth: false },
    logout: { method: 'POST', path: '/api/auth/logout', requiresAuth: true },
    refresh: { method: 'POST', path: '/api/auth/refresh', requiresAuth: true },
    profile: { method: 'GET', path: '/api/auth/profile', requiresAuth: true },
  },

  // Dataset endpoints
  datasets: {
    list: { method: 'GET', path: '/api/datasets', requiresAuth: true },
    get: { method: 'GET', path: '/api/datasets/{id}', requiresAuth: true },
    create: { method: 'POST', path: '/api/datasets', requiresAuth: true },
    update: { method: 'PUT', path: '/api/datasets/{id}', requiresAuth: true },
    delete: { method: 'DELETE', path: '/api/datasets/{id}', requiresAuth: true },
    upload: { method: 'POST', path: '/api/datasets/upload', requiresAuth: true },
    download: { method: 'GET', path: '/api/datasets/{id}/download', requiresAuth: true },
  },

  // Analysis endpoints
  analysis: {
    submit: { method: 'POST', path: '/api/analysis', requiresAuth: true },
    status: { method: 'GET', path: '/api/analysis/{id}/status', requiresAuth: true },
    results: { method: 'GET', path: '/api/analysis/{id}/results', requiresAuth: true },
    cancel: { method: 'DELETE', path: '/api/analysis/{id}', requiresAuth: true },
    list: { method: 'GET', path: '/api/analysis', requiresAuth: true },
    glm: { method: 'POST', path: '/api/analysis/glm', requiresAuth: true },
    connectivity: { method: 'POST', path: '/api/analysis/connectivity', requiresAuth: true },
    preprocessing: { method: 'POST', path: '/api/analysis/preprocessing', requiresAuth: true },
  },

  // Knowledge Graph endpoints
  kg: {
    search: { method: 'POST', path: '/api/kg/search', requiresAuth: true },
    entity: { method: 'GET', path: '/api/kg/entity/{id}', requiresAuth: true },
    relations: { method: 'GET', path: '/api/kg/entity/{id}/relations', requiresAuth: true },
    query: { method: 'POST', path: '/api/kg/query', requiresAuth: true },
    visualize: { method: 'POST', path: '/api/kg/visualize', requiresAuth: true },
  },

  // Visualization endpoints
  visualization: {
    brain: { method: 'POST', path: '/api/visualize/brain', requiresAuth: true },
    statistical: { method: 'POST', path: '/api/visualize/statistical', requiresAuth: true },
    connectivity: { method: 'POST', path: '/api/visualize/connectivity', requiresAuth: true },
    timeseries: { method: 'POST', path: '/api/visualize/timeseries', requiresAuth: true },
  },

  // System endpoints
  system: {
    health: { method: 'GET', path: '/health', requiresAuth: false },
    status: { method: 'GET', path: '/api/status', requiresAuth: true },
    metrics: { method: 'GET', path: '/api/metrics', requiresAuth: true },
    version: { method: 'GET', path: '/api/version', requiresAuth: false },
  },

  // User management endpoints
  users: {
    list: { method: 'GET', path: '/api/users', requiresAuth: true },
    get: { method: 'GET', path: '/api/users/{id}', requiresAuth: true },
    create: { method: 'POST', path: '/api/users', requiresAuth: true },
    update: { method: 'PUT', path: '/api/users/{id}', requiresAuth: true },
    settings: { method: 'GET', path: '/api/users/{id}/settings', requiresAuth: true },
    updateSettings: { method: 'PUT', path: '/api/users/{id}/settings', requiresAuth: true },
  },

  // File management endpoints
  files: {
    upload: { method: 'POST', path: '/api/files/upload', requiresAuth: true },
    download: { method: 'GET', path: '/api/files/{id}', requiresAuth: true },
    list: { method: 'GET', path: '/api/files', requiresAuth: true },
    delete: { method: 'DELETE', path: '/api/files/{id}', requiresAuth: true },
    metadata: { method: 'GET', path: '/api/files/{id}/metadata', requiresAuth: true },
  },
};

export function setup() {
  console.log('Setting up API endpoints test...');

  // Generate comprehensive test data
  const testData = {
    users: dataGen.generateUsers(100),
    datasets: generateDatasetData(50),
    analysisRequests: dataGen.generateAnalysisRequests(200),
    knowledgeGraphQueries: dataGen.generateKnowledgeGraphQueries(100),
    files: generateFileData(75),
    visualizationRequests: generateVisualizationData(100)
  };

  // Initial health check
  const healthStatus = healthCheck(__ENV.BASE_URL || 'http://localhost');
  if (!healthStatus.healthy) {
    throw new Error(`Health check failed: ${healthStatus.message}`);
  }

  // Test endpoint discovery
  const endpointDiscovery = discoverEndpoints(__ENV.BASE_URL || 'http://localhost');
  console.log('Available endpoints:', Object.keys(endpointDiscovery).length);

  console.log('API endpoints test setup complete');
  return testData;
}

export default function(data) {
  const baseUrl = __ENV.BASE_URL || 'http://localhost';
  const user = data.users[Math.floor(Math.random() * data.users.length)];
  const userSession = new UserSession(user, baseUrl);

  userSession.start();

  try {
    // Select test scenario based on probability
    const scenario = selectAPITestScenario();

    switch (scenario) {
      case 'comprehensive_workflow':
        comprehensiveWorkflowTest(userSession, data);
        break;
      case 'endpoint_coverage':
        endpointCoverageTest(userSession, data);
        break;
      case 'load_balancer_distribution':
        loadBalancerDistributionTest(userSession, data);
        break;
      case 'error_handling':
        errorHandlingTest(userSession, data);
        break;
      case 'authentication_flow':
        authenticationFlowTest(userSession, data);
        break;
      default:
        comprehensiveWorkflowTest(userSession, data);
    }

  } catch (error) {
    endpointErrors.add(1);
    console.error(`API test error for user ${user.username}: ${error}`);
  } finally {
    userSession.end();
  }

  sleep(Math.random() * 2 + 1);
}

// Select API test scenario
function selectAPITestScenario() {
  const rand = Math.random();
  if (rand < 0.4) return 'comprehensive_workflow';
  if (rand < 0.6) return 'endpoint_coverage';
  if (rand < 0.75) return 'load_balancer_distribution';
  if (rand < 0.9) return 'error_handling';
  return 'authentication_flow';
}

// Comprehensive workflow test - tests multiple endpoints in sequence
function comprehensiveWorkflowTest(userSession, data) {
  const baseUrl = userSession.baseUrl;

  // 1. Authentication workflow
  testEndpoint(userSession, 'auth', 'profile', {});

  // 2. Dataset workflow
  testEndpoint(userSession, 'datasets', 'list', {});

  const datasetData = data.datasets[Math.floor(Math.random() * data.datasets.length)];
  const createResponse = testEndpoint(userSession, 'datasets', 'create', datasetData);

  let datasetId = null;
  if (createResponse && createResponse.status === 201) {
    datasetId = createResponse.json('id');
  }

  if (datasetId) {
    testEndpoint(userSession, 'datasets', 'get', {}, { id: datasetId });
    testEndpoint(userSession, 'datasets', 'update', { name: 'Updated Dataset' }, { id: datasetId });
  }

  // 3. Analysis workflow
  const analysisRequest = data.analysisRequests[Math.floor(Math.random() * data.analysisRequests.length)];
  const analysisResponse = testEndpoint(userSession, 'analysis', 'submit', analysisRequest);

  let analysisId = null;
  if (analysisResponse && analysisResponse.status === 202) {
    analysisId = analysisResponse.json('job_id');
  }

  if (analysisId) {
    sleep(1);
    testEndpoint(userSession, 'analysis', 'status', {}, { id: analysisId });
    testEndpoint(userSession, 'analysis', 'results', {}, { id: analysisId });
  }

  // 4. Knowledge Graph workflow
  const kgQuery = data.knowledgeGraphQueries[Math.floor(Math.random() * data.knowledgeGraphQueries.length)];
  const kgResponse = testEndpoint(userSession, 'kg', 'search', { query: kgQuery.text });

  if (kgResponse && kgResponse.status === 200) {
    const results = kgResponse.json();
    if (results && results.length > 0) {
      const entityId = results[0].id;
      testEndpoint(userSession, 'kg', 'entity', {}, { id: entityId });
      testEndpoint(userSession, 'kg', 'relations', {}, { id: entityId });
    }
  }

  // 5. Visualization workflow
  const vizRequest = data.visualizationRequests[Math.floor(Math.random() * data.visualizationRequests.length)];
  testEndpoint(userSession, 'visualization', 'brain', vizRequest);

  // 6. System checks
  testEndpoint(userSession, 'system', 'status', {});
  testEndpoint(userSession, 'system', 'metrics', {});

  // Cleanup
  if (datasetId) {
    testEndpoint(userSession, 'datasets', 'delete', {}, { id: datasetId });
  }
}

// Endpoint coverage test - systematically test all endpoints
function endpointCoverageTest(userSession, data) {
  const endpointCategories = Object.keys(API_ENDPOINTS);
  const selectedCategory = endpointCategories[Math.floor(Math.random() * endpointCategories.length)];
  const endpoints = API_ENDPOINTS[selectedCategory];

  console.log(`Testing ${selectedCategory} endpoints`);

  // Test each endpoint in the category
  Object.keys(endpoints).forEach(endpointName => {
    const endpoint = endpoints[endpointName];

    // Generate appropriate test data
    let testData = {};
    let pathParams = {};

    switch (selectedCategory) {
      case 'datasets':
        testData = data.datasets[Math.floor(Math.random() * data.datasets.length)] || {};
        pathParams = { id: 'dataset_' + Math.floor(Math.random() * 100) };
        break;
      case 'analysis':
        testData = data.analysisRequests[Math.floor(Math.random() * data.analysisRequests.length)] || {};
        pathParams = { id: 'analysis_' + Math.floor(Math.random() * 100) };
        break;
      case 'kg':
        testData = { query: data.knowledgeGraphQueries[0]?.text || 'test query' };
        pathParams = { id: 'entity_' + Math.floor(Math.random() * 100) };
        break;
      case 'users':
        testData = data.users[Math.floor(Math.random() * data.users.length)] || {};
        pathParams = { id: 'user_' + Math.floor(Math.random() * 100) };
        break;
      case 'files':
        testData = data.files[Math.floor(Math.random() * data.files.length)] || {};
        pathParams = { id: 'file_' + Math.floor(Math.random() * 100) };
        break;
      case 'visualization':
        testData = data.visualizationRequests[Math.floor(Math.random() * data.visualizationRequests.length)] || {};
        break;
    }

    testEndpoint(userSession, selectedCategory, endpointName, testData, pathParams);

    // Small delay between endpoint tests
    sleep(0.5);
  });
}

// Load balancer distribution test
function loadBalancerDistributionTest(userSession, data) {
  // Test the same endpoint multiple times to check load balancing
  const testEndpointName = 'datasets.list';
  const iterations = 10;

  for (let i = 0; i < iterations; i++) {
    const response = testEndpoint(userSession, 'datasets', 'list', {});

    if (response) {
      // Track which backend served the request (if available in headers)
      const serverId = response.headers['X-Served-By'] || response.headers['Server-Id'] || 'unknown';
      loadBalancerDistribution.add(1, { server: serverId });
    }

    sleep(0.1); // Very short delay
  }
}

// Error handling test
function errorHandlingTest(userSession, data) {
  // Test various error conditions

  // 1. Invalid endpoint
  let response = withRetry(() =>
    http.get(`${userSession.baseUrl}/api/nonexistent`, {
      headers: userSession.getHeaders(),
    }),
    1 // Don't retry for this test
  );

  check(response, {
    'invalid endpoint returns 404': (r) => r.status === 404,
  });

  // 2. Invalid method
  response = withRetry(() =>
    http.patch(`${userSession.baseUrl}/api/datasets`, '{}', {
      headers: {
        ...userSession.getHeaders(),
        'Content-Type': 'application/json',
      },
    }),
    1
  );

  check(response, {
    'invalid method handled': (r) => r.status === 405 || r.status === 404,
  });

  // 3. Invalid JSON
  response = withRetry(() =>
    http.post(`${userSession.baseUrl}/api/analysis`, 'invalid json', {
      headers: {
        ...userSession.getHeaders(),
        'Content-Type': 'application/json',
      },
    }),
    1
  );

  check(response, {
    'invalid JSON handled': (r) => r.status === 400,
  });

  // 4. Missing required fields
  response = withRetry(() =>
    http.post(`${userSession.baseUrl}/api/datasets`, '{}', {
      headers: {
        ...userSession.getHeaders(),
        'Content-Type': 'application/json',
      },
    }),
    1
  );

  check(response, {
    'missing required fields handled': (r) => r.status === 400 || r.status === 422,
  });

  // 5. Non-existent resource
  response = testEndpoint(userSession, 'datasets', 'get', {}, { id: 'nonexistent_dataset' });

  check(response, {
    'non-existent resource returns 404': (r) => r.status === 404,
  });
}

// Authentication flow test
function authenticationFlowTest(userSession, data) {
  const baseUrl = userSession.baseUrl;

  // 1. Test unauthenticated access to protected endpoint
  let response = withRetry(() =>
    http.get(`${baseUrl}/api/datasets`, {
      // No authorization header
    }),
    1
  );

  check(response, {
    'unauthenticated access blocked': (r) => r.status === 401,
  });

  if (response.status === 401) {
    authFailures.add(1);
  }

  // 2. Test invalid token
  response = withRetry(() =>
    http.get(`${baseUrl}/api/datasets`, {
      headers: {
        'Authorization': 'Bearer invalid_token',
      },
    }),
    1
  );

  check(response, {
    'invalid token rejected': (r) => r.status === 401,
  });

  // 3. Test valid authentication
  testEndpoint(userSession, 'auth', 'profile', {});

  // 4. Test token refresh (if implemented)
  testEndpoint(userSession, 'auth', 'refresh', {});

  // 5. Test logout
  testEndpoint(userSession, 'auth', 'logout', {});
}

// Generic endpoint testing function
function testEndpoint(userSession, category, endpointName, data = {}, pathParams = {}) {
  const endpoint = API_ENDPOINTS[category]?.[endpointName];

  if (!endpoint) {
    console.error(`Unknown endpoint: ${category}.${endpointName}`);
    endpointErrors.add(1);
    return null;
  }

  // Replace path parameters
  let path = endpoint.path;
  Object.keys(pathParams).forEach(param => {
    path = path.replace(`{${param}}`, pathParams[param]);
  });

  const url = `${userSession.baseUrl}${path}`;
  const headers = endpoint.requiresAuth ? userSession.getHeaders() : {};

  const startTime = Date.now();
  let response;

  try {
    switch (endpoint.method) {
      case 'GET':
        response = withRetry(() => http.get(url, { headers }));
        break;
      case 'POST':
        response = withRetry(() => http.post(url, JSON.stringify(data), {
          headers: {
            ...headers,
            'Content-Type': 'application/json',
          },
        }));
        break;
      case 'PUT':
        response = withRetry(() => http.put(url, JSON.stringify(data), {
          headers: {
            ...headers,
            'Content-Type': 'application/json',
          },
        }));
        break;
      case 'DELETE':
        response = withRetry(() => http.del(url, null, { headers }));
        break;
      default:
        console.error(`Unsupported method: ${endpoint.method}`);
        endpointErrors.add(1);
        return null;
    }

    const latency = Date.now() - startTime;
    endpointLatencies.add(latency);

    // Check for rate limiting
    if (response.status === 429) {
      rateLimitHits.add(1);
    }

    // Basic response validation
    const success = check(response, {
      [`${category}.${endpointName} status OK`]: (r) =>
        r.status < 400 || r.status === 404 || r.status === 429,
      [`${category}.${endpointName} latency OK`]: (r) =>
        r.timings.duration < 5000,
    });

    if (!success) {
      endpointErrors.add(1);
      console.error(`Endpoint ${category}.${endpointName} failed: status ${response.status}`);
    }

    return response;

  } catch (error) {
    endpointErrors.add(1);
    console.error(`Error testing ${category}.${endpointName}:`, error);
    return null;
  }
}

// Generate dataset data for testing
function generateDatasetData(count) {
  const datasets = [];
  const datasetTypes = ['fmri', 'structural', 'dwi', 'pet', 'eeg'];
  const studyTypes = ['task', 'resting', 'clinical', 'developmental'];

  for (let i = 0; i < count; i++) {
    datasets.push({
      name: `Test Dataset ${i}`,
      type: datasetTypes[Math.floor(Math.random() * datasetTypes.length)],
      studyType: studyTypes[Math.floor(Math.random() * studyTypes.length)],
      subjects: Math.floor(Math.random() * 100) + 10,
      sessions: Math.floor(Math.random() * 3) + 1,
      description: `Generated test dataset ${i} for API testing`,
      public: Math.random() < 0.3,
      tags: ['test', 'api', 'generated']
    });
  }

  return datasets;
}

// Generate file data for testing
function generateFileData(count) {
  const files = [];
  const fileTypes = ['nii.gz', 'json', 'tsv', 'txt', 'mat'];

  for (let i = 0; i < count; i++) {
    files.push({
      name: `test_file_${i}.${fileTypes[Math.floor(Math.random() * fileTypes.length)]}`,
      size: Math.floor(Math.random() * 1000000) + 1000, // 1KB - 1MB
      type: fileTypes[Math.floor(Math.random() * fileTypes.length)],
      content: 'base64_encoded_content_placeholder'
    });
  }

  return files;
}

// Generate visualization data for testing
function generateVisualizationData(count) {
  const visualizations = [];
  const vizTypes = ['brain_surface', 'slice_viewer', 'connectivity_matrix', 'time_series'];
  const colorMaps = ['viridis', 'plasma', 'hot', 'cool', 'jet'];

  for (let i = 0; i < count; i++) {
    visualizations.push({
      type: vizTypes[Math.floor(Math.random() * vizTypes.length)],
      data: `statistical_map_${i}`,
      colormap: colorMaps[Math.floor(Math.random() * colorMaps.length)],
      threshold: Math.random() * 5 + 1,
      transparency: Math.random() * 0.5 + 0.5,
      resolution: Math.random() < 0.5 ? 'high' : 'medium'
    });
  }

  return visualizations;
}

// Discover available endpoints
function discoverEndpoints(baseUrl) {
  try {
    const response = http.get(`${baseUrl}/api/docs/openapi.json`, {
      timeout: '10s',
    });

    if (response.status === 200) {
      const openapi = response.json();
      return openapi.paths || {};
    }
  } catch (error) {
    console.warn('Could not discover endpoints via OpenAPI:', error);
  }

  return {};
}

export function teardown(data) {
  console.log('Tearing down API endpoints test...');

  // Generate comprehensive API test report
  const apiReport = {
    totalEndpointErrors: endpointErrors.value,
    averageEndpointLatency: endpointLatencies.values.length > 0 ?
      endpointLatencies.values.reduce((a, b) => a + b, 0) / endpointLatencies.values.length : 0,
    maxEndpointLatency: endpointLatencies.values.length > 0 ?
      Math.max(...endpointLatencies.values) : 0,
    authFailures: authFailures.value,
    rateLimitHits: rateLimitHits.value,
    loadBalancerDistribution: loadBalancerDistribution.value,
    testedEndpoints: Object.keys(API_ENDPOINTS).reduce((total, category) =>
      total + Object.keys(API_ENDPOINTS[category]).length, 0)
  };

  console.log('API endpoints test report:', JSON.stringify(apiReport, null, 2));

  // Performance validation
  const finalValidation = validator.generateReport();
  console.log('Performance validation results:', JSON.stringify(finalValidation, null, 2));

  console.log('API endpoints test teardown complete');
}