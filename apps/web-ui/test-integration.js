#!/usr/bin/env node
/**
 * Integration Test Script for Web UI <-> Backend Services
 * Run this to verify all connections are working
 */

const AGENT_URL =
  process.env.BR_AGENT_URL ||
  process.env.AGENT_BASE_URL ||
  process.env.AGENT_URL ||
  'http://localhost:8000';
const ORCHESTRATOR_URL =
  process.env.BR_ORCHESTRATOR_URL ||
  process.env.ORCHESTRATOR_BASE_URL ||
  process.env.ORCHESTRATOR_URL ||
  'http://localhost:3001';
const NEUROKG_URL =
  process.env.BR_NEUROKG_URL ||
  process.env.NEUROKG_API_URL ||
  process.env.NEUROKG_URL ||
  'http://localhost:5000';

// Color codes for console output
const colors = {
  reset: '\x1b[0m',
  green: '\x1b[32m',
  red: '\x1b[31m',
  yellow: '\x1b[33m',
  blue: '\x1b[34m'
};

async function testEndpoint(name, url, options = {}) {
  process.stdout.write(`Testing ${name}... `);
  try {
    const response = await fetch(url, options);
    if (response.ok) {
      console.log(`${colors.green}✓${colors.reset}`);
      return true;
    } else {
      console.log(`${colors.red}✗ (${response.status})${colors.reset}`);
      return false;
    }
  } catch (error) {
    console.log(`${colors.red}✗ (${error.message})${colors.reset}`);
    return false;
  }
}

async function runTests() {
  console.log(`${colors.blue}=== Brain Researcher Integration Tests ===${colors.reset}\n`);
  
  let passedTests = 0;
  let totalTests = 0;
  
  // Test Agent
  console.log(`${colors.yellow}Agent Service:${colors.reset}`);
  totalTests++;
  if (await testEndpoint('Health Check', `${AGENT_URL}/health`)) {
    passedTests++;
  }
  
  // Test Dataset Endpoint
  totalTests++;
  if (await testEndpoint('Dataset Search', `${AGENT_URL}/api/datasets/search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query: 'brain', limit: 1 })
  })) {
    passedTests++;
  }
  
  console.log();

  // Test Orchestrator
  console.log(`${colors.yellow}Orchestrator Service:${colors.reset}`);
  totalTests++;
  if (await testEndpoint('Health Check', `${ORCHESTRATOR_URL}/health`)) {
    passedTests++;
  }

  console.log();
  
  // Test BR-KG Service
  console.log(`${colors.yellow}BR-KG Service:${colors.reset}`);
  totalTests++;
  if (await testEndpoint('BR-KG Health', `${NEUROKG_URL}/health`)) {
    passedTests++;
  }
  
  totalTests++;
  if (await testEndpoint('Graph Stats', `${NEUROKG_URL}/api/statistics`)) {
    passedTests++;
  }
  
  totalTests++;
  if (await testEndpoint('GraphQL Endpoint', `${NEUROKG_URL}/graphql`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ 
      query: '{ concepts(limit: 1) { id name } }' 
    })
  })) {
    passedTests++;
  }
  
  console.log();
  console.log(`${colors.blue}=== Test Results ===${colors.reset}`);
  console.log(`Passed: ${colors.green}${passedTests}${colors.reset}/${totalTests}`);
  
  if (passedTests === totalTests) {
    console.log(`${colors.green}✓ All tests passed! Integration is ready.${colors.reset}`);
    process.exit(0);
  } else {
    console.log(`${colors.red}✗ Some tests failed. Please check service status.${colors.reset}`);
    console.log(`\nTroubleshooting:`);
    console.log(`1. Make sure all services are running:`);
    console.log(`   - br serve agent (port 8000)`);
    console.log(`   - br serve orchestrator (port 3001)`);
    console.log(`   - br serve kg (port 5000)`);
    console.log(`   - cd apps/web-ui && npm run dev:3002`);
    console.log(`2. Check service logs for errors`);
    console.log(`3. Verify BR_AGENT_URL / BR_ORCHESTRATOR_URL / BR_NEUROKG_URL overrides if you are not using local defaults`);
    process.exit(1);
  }
}

// Run tests
runTests().catch(error => {
  console.error(`${colors.red}Test runner error:${colors.reset}`, error);
  process.exit(1);
});
