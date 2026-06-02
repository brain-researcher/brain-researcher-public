/**
 * Utility functions for K6 performance tests
 *
 * This module provides common functions for HTTP requests, WebSocket handling,
 * data generation, and result validation across all test scenarios.
 */

import { check, group, sleep } from 'k6';
import { Rate, Counter, Gauge, Trend } from 'k6/metrics';
import ws from 'k6/ws';
import { CONFIG } from '../config/k6.config.js';

// Custom metrics for detailed performance tracking
export const errorRate = new Rate('errors');
export const requestDuration = new Trend('request_duration', true);
export const wsConnectTime = new Trend('ws_connect_time', true);
export const queryExecutionTime = new Trend('query_execution_time', true);
export const memoryUsage = new Gauge('memory_usage_percent');
export const cpuUsage = new Gauge('cpu_usage_percent');
export const successfulRequests = new Counter('successful_requests');
export const failedRequests = new Counter('failed_requests');

/**
 * Enhanced HTTP request with comprehensive error handling and metrics
 */
export function makeRequest(method, url, payload = null, params = {}) {
  const defaultParams = {
    timeout: '30s',
    headers: {
      'Content-Type': 'application/json',
      'User-Agent': 'k6-performance-test',
      'Accept': 'application/json',
    },
    ...params
  };

  const startTime = Date.now();
  const response = method === 'GET'
    ? http.get(url, defaultParams)
    : http.post(url, payload, defaultParams);

  const duration = Date.now() - startTime;
  requestDuration.add(duration);

  // Record success/failure
  if (response.status >= 200 && response.status < 400) {
    successfulRequests.add(1);
  } else {
    failedRequests.add(1);
    errorRate.add(1);
  }

  return response;
}

/**
 * Orchestrator service API calls
 */
export class OrchestratorAPI {
  constructor(baseUrl = CONFIG.ORCHESTRATOR_URL) {
    this.baseUrl = baseUrl;
  }

  healthCheck() {
    return group('Orchestrator Health Check', () => {
      const response = makeRequest('GET', `${this.baseUrl}/health`);
      return check(response, {
        'health check status is 200': (r) => r.status === 200,
        'health check response time < 500ms': (r) => r.timings.duration < 500,
        'health check has required fields': (r) => {
          const body = JSON.parse(r.body);
          return body.status && body.services;
        },
      });
    });
  }

  createRun(prompt, pipeline = 'glm', datasetId = null) {
    return group('Orchestrator Create Run', () => {
      const payload = JSON.stringify({
        prompt: prompt,
        pipeline: pipeline,
        dataset_id: datasetId,
        parameters: {
          timeout: 300,
          max_retries: 3
        }
      });

      const response = makeRequest('POST', `${this.baseUrl}/run`, payload);
      return check(response, {
        'create run status is 200': (r) => r.status === 200,
        'create run returns job_id': (r) => {
          const body = JSON.parse(r.body);
          return body.job_id && typeof body.job_id === 'string';
        },
        'create run response time < 1000ms': (r) => r.timings.duration < 1000,
      });
    });
  }

  getJob(jobId) {
    return group('Orchestrator Get Job', () => {
      const response = makeRequest('GET', `${this.baseUrl}/jobs/${jobId}`);
      return check(response, {
        'get job status is 200 or 404': (r) => r.status === 200 || r.status === 404,
        'get job response time < 500ms': (r) => r.timings.duration < 500,
      });
    });
  }

  listDatasets(query = null) {
    return group('Orchestrator List Datasets', () => {
      const url = query ? `${this.baseUrl}/datasets?q=${encodeURIComponent(query)}` : `${this.baseUrl}/datasets`;
      const response = makeRequest('GET', url);
      return check(response, {
        'list datasets status is 200': (r) => r.status === 200,
        'list datasets returns array': (r) => {
          const body = JSON.parse(r.body);
          return Array.isArray(body.datasets);
        },
        'list datasets response time < 1000ms': (r) => r.timings.duration < 1000,
      });
    });
  }

  listTools() {
    return group('Orchestrator List Tools', () => {
      const response = makeRequest('GET', `${this.baseUrl}/tools`);
      return check(response, {
        'list tools status is 200': (r) => r.status === 200,
        'list tools returns array': (r) => {
          const body = JSON.parse(r.body);
          return Array.isArray(body.tools);
        },
        'list tools response time < 500ms': (r) => r.timings.duration < 500,
      });
    });
  }
}

/**
 * BR-KG service API calls
 */
export class BRKGAPI {
  constructor(baseUrl = CONFIG.BR_KG_URL) {
    this.baseUrl = baseUrl;
  }

  healthCheck() {
    return group('BR-KG Health Check', () => {
      const response = makeRequest('GET', `${this.baseUrl}/health`);
      return check(response, {
        'brKg health status is 200': (r) => r.status === 200,
        'brKg health response time < 500ms': (r) => r.timings.duration < 500,
      });
    });
  }

  executeGraphQLQuery(query, variables = {}) {
    return group('BR-KG GraphQL Query', () => {
      const payload = JSON.stringify({
        query: query,
        variables: variables
      });

      const startTime = Date.now();
      const response = makeRequest('POST', `${this.baseUrl}/graphql`, payload);
      const queryTime = Date.now() - startTime;

      queryExecutionTime.add(queryTime, { query_type: 'graphql' });

      return check(response, {
        'graphql query status is 200': (r) => r.status === 200,
        'graphql query has data or errors': (r) => {
          const body = JSON.parse(r.body);
          return body.data !== undefined || body.errors !== undefined;
        },
        'graphql query response time < 2000ms': (r) => r.timings.duration < 2000,
      });
    });
  }

  searchDatasets(query, limit = 20) {
    return group('BR-KG Search Datasets', () => {
      const url = `${this.baseUrl}/api/datasets?q=${encodeURIComponent(query)}&limit=${limit}`;
      const response = makeRequest('GET', url);
      return check(response, {
        'search datasets status is 200': (r) => r.status === 200,
        'search datasets response time < 1500ms': (r) => r.timings.duration < 1500,
      });
    });
  }

  executeSearch(query, nodeTypes = null, limit = 100) {
    return group('BR-KG Full-Text Search', () => {
      const payload = JSON.stringify({
        query: query,
        node_types: nodeTypes,
        limit: limit
      });

      const response = makeRequest('POST', `${this.baseUrl}/api/search`, payload);
      return check(response, {
        'search status is 200': (r) => r.status === 200,
        'search returns results array': (r) => {
          try {
            const parsed = JSON.parse(r.body);
            if (Array.isArray(parsed)) {
              return true;
            }
            return Array.isArray(parsed?.results);
          } catch (e) {
            return false;
          }
        },
        'search response time < 2000ms': (r) => r.timings.duration < 2000,
      });
    });
  }

  executeSPARQLQuery(query) {
    return group('BR-KG SPARQL Query', () => {
      const params = new URLSearchParams();
      params.append('query', query);
      params.append('format', 'json');

      const response = makeRequest('POST', `${this.baseUrl}/sparql`, params.toString(), {
        headers: {
          'Content-Type': 'application/x-www-form-urlencoded',
          'Accept': 'application/sparql-results+json'
        }
      });

      return check(response, {
        'sparql query status is 200': (r) => r.status === 200,
        'sparql query response time < 3000ms': (r) => r.timings.duration < 3000,
      });
    });
  }

  getPerformanceMetrics() {
    return group('BR-KG Performance Metrics', () => {
      const response = makeRequest('GET', `${this.baseUrl}/api/performance/metrics`);
      return check(response, {
        'performance metrics status is 200': (r) => r.status === 200,
        'performance metrics response time < 1000ms': (r) => r.timings.duration < 1000,
      });
    });
  }
}

/**
 * Agent service API calls
 */
export class AgentAPI {
  constructor(baseUrl = CONFIG.AGENT_URL) {
    this.baseUrl = baseUrl;
  }

  healthCheck() {
    return group('Agent Health Check', () => {
      const response = makeRequest('GET', `${this.baseUrl}/health`);
      return check(response, {
        'agent health status is 200': (r) => r.status === 200,
        'agent health response time < 500ms': (r) => r.timings.duration < 500,
      });
    });
  }

  executeQuery(query, userId = 'test_user', parameters = {}) {
    return group('Agent Execute Query', () => {
      const payload = JSON.stringify({
        query: query,
        user_id: userId,
        ...parameters
      });

      const startTime = Date.now();
      const response = makeRequest('POST', `${this.baseUrl}/query`, payload);
      const queryTime = Date.now() - startTime;

      queryExecutionTime.add(queryTime, { query_type: 'agent' });

      return check(response, {
        'agent query status is 200': (r) => r.status === 200,
        'agent query returns response': (r) => {
          const body = JSON.parse(r.body);
          return body.response || body.result;
        },
        'agent query response time < 30000ms': (r) => r.timings.duration < 30000,
      });
    });
  }

  listTools() {
    return group('Agent List Tools', () => {
      const response = makeRequest('GET', `${this.baseUrl}/tools`);
      return check(response, {
        'agent tools status is 200': (r) => r.status === 200,
        'agent tools returns array': (r) => {
          const body = JSON.parse(r.body);
          return Array.isArray(body.tools);
        },
        'agent tools response time < 1000ms': (r) => r.timings.duration < 1000,
      });
    });
  }
}

/**
 * WebSocket connection manager
 */
export class WebSocketManager {
  constructor(baseUrl) {
    this.baseUrl = baseUrl;
    this.connections = new Map();
  }

  connectToJobUpdates(jobId, onMessage = null, onError = null) {
    return group('WebSocket Job Updates', () => {
      const url = `${this.baseUrl.replace('http', 'ws')}/ws/jobs/${jobId}`;
      const startTime = Date.now();

      const response = ws.connect(url, {}, (socket) => {
        const connectTime = Date.now() - startTime;
        wsConnectTime.add(connectTime);

        socket.on('open', () => {
          console.log(`Connected to WebSocket for job ${jobId}`);
        });

        socket.on('message', (data) => {
          if (onMessage) onMessage(JSON.parse(data));
        });

        socket.on('error', (e) => {
          console.log(`WebSocket error: ${e}`);
          if (onError) onError(e);
        });

        // Send a test message
        socket.send(JSON.stringify({ type: 'ping' }));

        // Keep connection alive for a short time
        sleep(5);
      });

      return check(response, {
        'websocket connection successful': (r) => r && r.status === 101,
      });
    });
  }
}

/**
 * Data generators for realistic test scenarios
 */
export class TestDataGenerator {
  static generateFMRIQuery() {
    const tasks = ['working_memory', 'attention', 'emotion', 'motor', 'language'];
    const analyses = ['activation', 'connectivity', 'decoding', 'classification'];
    const regions = ['prefrontal_cortex', 'amygdala', 'hippocampus', 'motor_cortex', 'visual_cortex'];

    const task = tasks[Math.floor(Math.random() * tasks.length)];
    const analysis = analyses[Math.floor(Math.random() * analyses.length)];
    const region = regions[Math.floor(Math.random() * regions.length)];

    return `Analyze ${analysis} patterns in ${region} during ${task} tasks`;
  }

  static generateComplexGraphQLQuery() {
    return `
      query ComplexBrainQuery($limit: Int!, $taskType: String!) {
        studies(taskType: $taskType, limit: $limit) {
          id
          title
          pmid
          authors {
            name
            affiliation
          }
          activations {
            coordinates {
              x
              y
              z
            }
            brainRegion {
              name
              atlas
            }
            statisticValue
            threshold
          }
          contrasts {
            name
            condition
            controlCondition
          }
        }
      }
    `;
  }

  static generateSPARQLQuery() {
    return `
      PREFIX brain: <https://br-kg.org/ontology/>
      SELECT ?study ?title ?region ?activation
      WHERE {
        ?study brain:hasTitle ?title .
        ?study brain:hasActivation ?activation .
        ?activation brain:locatedIn ?region .
        ?region brain:partOf brain:prefrontal_cortex .
      }
      LIMIT 50
    `;
  }

  static generateRandomParameters() {
    return {
      threshold: 0.001 + Math.random() * 0.099, // Random threshold between 0.001 and 0.1
      cluster_size: Math.floor(Math.random() * 50) + 10, // Random cluster size between 10-60
      fdr_correction: Math.random() > 0.5,
      smoothing_fwhm: 4 + Math.random() * 4, // Random smoothing between 4-8mm
    };
  }
}

/**
 * Performance benchmark comparisons
 */
export function checkPerformanceBenchmarks(response, benchmarks = {}) {
  const defaultBenchmarks = {
    responseTime: 2000,
    successRate: 0.95,
    errorRate: 0.05,
  };

  const checks = { ...defaultBenchmarks, ...benchmarks };

  return {
    'response_time_within_benchmark': response.timings.duration < checks.responseTime,
    'status_indicates_success': response.status >= 200 && response.status < 400,
    'response_has_content': response.body && response.body.length > 0,
  };
}

/**
 * Scenario execution wrapper with retry logic
 */
export function executeWithRetry(fn, maxRetries = 3, delay = 1000) {
  let lastError;

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      return fn();
    } catch (error) {
      lastError = error;
      console.log(`Attempt ${attempt} failed: ${error.message}`);

      if (attempt < maxRetries) {
        sleep(delay / 1000); // Convert to seconds for k6
        delay *= 2; // Exponential backoff
      }
    }
  }

  throw lastError;
}

export default {
  OrchestratorAPI,
  BRKGAPI,
  AgentAPI,
  WebSocketManager,
  TestDataGenerator,
  makeRequest,
  checkPerformanceBenchmarks,
  executeWithRetry,
};
