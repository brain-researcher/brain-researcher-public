/**
 * K6 Configuration for Brain Researcher Backend Services Performance Testing
 *
 * This configuration defines performance thresholds, load profiles, and test scenarios
 * for comprehensive testing of the Orchestrator, BR-KG, and Agent services.
 */

export const CONFIG = {
  // Service endpoints
  ORCHESTRATOR_URL: __ENV.ORCHESTRATOR_URL || 'http://localhost:3001',
  BR_KG_URL: __ENV.BR_KG_URL || 'http://localhost:5000',
  AGENT_URL: __ENV.AGENT_URL || 'http://localhost:8000',

  // Performance thresholds
  THRESHOLDS: {
    // Response time thresholds
    'http_req_duration': ['p(50)<500', 'p(95)<2000', 'p(99)<5000'],
    'http_req_duration{group:::orchestrator_api}': ['p(95)<1000'],
    'http_req_duration{group:::brKg_api}': ['p(95)<1500'],
    'http_req_duration{group:::agent_api}': ['p(95)<3000'],

    // Throughput requirements
    'http_reqs': ['rate>100'], // Minimum 100 requests per second

    // Error rate thresholds
    'http_req_failed': ['rate<0.05'], // Less than 5% error rate
    'http_req_failed{group:::critical}': ['rate<0.01'], // Less than 1% for critical endpoints

    // WebSocket connection success
    'ws_connecting': ['p(95)<1000'],
    'ws_msgs_sent': ['count>0'],
    'ws_msgs_received': ['count>0'],

    // Database query performance
    'brKg_query_duration': ['p(95)<1000'],
    'agent_tool_execution': ['p(95)<5000'],

    // Resource utilization (will be tracked via custom metrics)
    'memory_usage': ['value<80'], // Less than 80% memory usage
    'cpu_usage': ['value<70'], // Less than 70% CPU usage
  },

  // Load profiles for different test scenarios
  LOAD_PROFILES: {
    SMOKE: {
      vus: 1,
      duration: '30s',
    },
    LOAD: {
      stages: [
        { duration: '2m', target: 10 },  // Ramp up
        { duration: '5m', target: 50 },  // Normal load
        { duration: '2m', target: 0 },   // Ramp down
      ],
    },
    STRESS: {
      stages: [
        { duration: '2m', target: 50 },   // Ramp up to normal
        { duration: '5m', target: 100 },  // Stress load
        { duration: '2m', target: 150 },  // Peak stress
        { duration: '2m', target: 0 },    // Ramp down
      ],
    },
    SPIKE: {
      stages: [
        { duration: '1m', target: 10 },   // Normal load
        { duration: '30s', target: 200 }, // Sudden spike
        { duration: '1m', target: 10 },   // Back to normal
        { duration: '30s', target: 200 }, // Another spike
        { duration: '1m', target: 0 },    // Ramp down
      ],
    },
    SOAK: {
      stages: [
        { duration: '5m', target: 30 },   // Ramp up
        { duration: '30m', target: 30 },  // Extended load
        { duration: '2m', target: 0 },    // Ramp down
      ],
    },
  },

  // Test data and scenarios
  TEST_DATA: {
    // Sample queries for agent service
    AGENT_QUERIES: [
      'Show me brain activation patterns for working memory tasks',
      'Analyze the relationship between age and cortical thickness',
      'Find studies related to depression and amygdala activity',
      'Compare motor cortex activation across different tasks',
      'Search for papers on default mode network connectivity',
    ],

    // Sample GraphQL queries for BR-KG
    BR_KG_QUERIES: [
      'query { datasets(limit: 10) { id name description subjects } }',
      'query { brainRegions(limit: 20) { name coordinates studies { title } } }',
      'query { studies(taskType: "working_memory") { title authors activations } }',
      'query { contrasts { name condition studies { pmid } } }',
      'mutation { createStudy(input: { title: "Test Study", pmid: "12345" }) { id } }',
    ],

    // Sample dataset IDs for testing
    DATASET_IDS: [
      'ds000001',
      'ds000114',
      'ds000210',
      'motor-task-sample',
    ],

    // Sample analysis pipelines
    PIPELINES: [
      'glm',
      'connectivity',
      'decoding',
      'meta_analysis',
    ],
  },

  // WebSocket test configuration
  WEBSOCKET_CONFIG: {
    RECONNECTION_ATTEMPTS: 3,
    MESSAGE_TIMEOUT: 10000,
    HEARTBEAT_INTERVAL: 30000,
  },

  // Resource monitoring configuration
  MONITORING: {
    SAMPLE_RATE: 1, // Sample every request
    SYSTEM_METRICS: true,
    CUSTOM_METRICS: true,
  },
};

// Export load profiles for easy access
export const SMOKE_PROFILE = CONFIG.LOAD_PROFILES.SMOKE;
export const LOAD_PROFILE = CONFIG.LOAD_PROFILES.LOAD;
export const STRESS_PROFILE = CONFIG.LOAD_PROFILES.STRESS;
export const SPIKE_PROFILE = CONFIG.LOAD_PROFILES.SPIKE;
export const SOAK_PROFILE = CONFIG.LOAD_PROFILES.SOAK;

// Utility functions for test setup
export function getRandomQuery(service) {
  const queries = CONFIG.TEST_DATA[`${service.toUpperCase()}_QUERIES`];
  return queries[Math.floor(Math.random() * queries.length)];
}

export function getRandomDatasetId() {
  const datasets = CONFIG.TEST_DATA.DATASET_IDS;
  return datasets[Math.floor(Math.random() * datasets.length)];
}

export function getRandomPipeline() {
  const pipelines = CONFIG.TEST_DATA.PIPELINES;
  return pipelines[Math.floor(Math.random() * pipelines.length)];
}

export default CONFIG;
