#!/usr/bin/env node

/**
 * Test script to verify Knowledge Graph Explorer integration
 * Tests the real BR-KG backend connections
 */

const http = require('http');

// Test endpoints
const BR_KG_BASE = 'http://localhost:5000';
const endpoints = [
  '/api/glmfitlins/stats',
  '/health',
  '/api/search?query=memory', // POST endpoint
  '/graphql' // GraphQL endpoint
];

function testEndpoint(path) {
  return new Promise((resolve, reject) => {
    const url = `${BR_KG_BASE}${path}`;
    console.log(`Testing: ${url}`);

    // Handle POST endpoints differently
    const isPostSearch = path.includes('/api/search');

    if (isPostSearch) {
      // POST request for search
      const postData = JSON.stringify({ query: 'memory', limit: 10 });
      const options = {
        hostname: 'localhost',
        port: 5000,
        path: '/api/search',
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Content-Length': Buffer.byteLength(postData)
        }
      };

      const req = http.request(options, (res) => {
        let data = '';
        res.on('data', (chunk) => data += chunk);
        res.on('end', () => {
          try {
            const parsed = JSON.parse(data);
            const results = Array.isArray(parsed) ? parsed : (parsed.results || []);
            console.log(`✅ ${path}: Status ${res.statusCode}`);
            console.log(`   Response: Found ${results.length} results`);
            resolve({ path, status: res.statusCode, data: parsed });
          } catch (e) {
            console.log(`⚠️  ${path}: Status ${res.statusCode}, Parse error`);
            resolve({ path, status: res.statusCode, data: null });
          }
        });
      });

      req.on('error', (err) => {
        console.log(`❌ ${path}: ${err.message}`);
        resolve({ path, status: 'error', error: err.message });
      });

      req.setTimeout(5000, () => {
        req.abort();
        console.log(`⏰ ${path}: Timeout`);
        resolve({ path, status: 'timeout' });
      });

      req.write(postData);
      req.end();
    } else {
      // Regular GET request
      const req = http.get(url, (res) => {
        let data = '';

        res.on('data', (chunk) => {
          data += chunk;
        });

        res.on('end', () => {
          try {
            const parsed = JSON.parse(data);
            console.log(`✅ ${path}: Status ${res.statusCode}`);
            console.log(`   Response: ${JSON.stringify(parsed).slice(0, 200)}...`);
            resolve({ path, status: res.statusCode, data: parsed });
          } catch (e) {
            console.log(`⚠️  ${path}: Status ${res.statusCode}, Non-JSON response`);
            console.log(`   Response: ${data.slice(0, 200)}...`);
            resolve({ path, status: res.statusCode, data: null });
          }
        });
      });

      req.on('error', (err) => {
        console.log(`❌ ${path}: ${err.message}`);
        resolve({ path, status: 'error', error: err.message });
      });

      req.setTimeout(5000, () => {
        req.abort();
        console.log(`⏰ ${path}: Timeout`);
        resolve({ path, status: 'timeout' });
      });
    }
  });
}

async function testKnowledgeGraphIntegration() {
  console.log('🧠 Testing Knowledge Graph Explorer Backend Integration\n');

  const results = [];

  for (const endpoint of endpoints) {
    const result = await testEndpoint(endpoint);
    results.push(result);
    console.log(''); // Add spacing
  }

  // Summary
  console.log('📊 Test Summary:');
  const working = results.filter(r => r.status === 200).length;
  const total = results.length;

  console.log(`   ✅ Working: ${working}/${total}`);
  console.log(`   ❌ Failed: ${total - working}/${total}`);

  if (working === total) {
    console.log('\n🎉 All endpoints working! Knowledge Graph Explorer backend integration ready.');
  } else {
    console.log('\n⚠️  Some endpoints failed. Check BR-KG service status.');
    console.log('   Make sure BR-KG service is running on http://localhost:5000');
  }

  // Test API format compatibility
  const statsResult = results.find(r => r.path === '/api/stats');
  if (statsResult && statsResult.data) {
    console.log('\n🔍 API Format Check:');
    const stats = statsResult.data;

    if (stats.total_nodes !== undefined) {
      console.log(`   ✅ total_nodes: ${stats.total_nodes}`);
    } else {
      console.log('   ❌ Missing total_nodes in stats');
    }

    if (stats.total_relationships !== undefined) {
      console.log(`   ✅ total_relationships: ${stats.total_relationships}`);
    } else {
      console.log('   ❌ Missing total_relationships in stats');
    }
  }

  const searchResult = results.find(r => r.path.includes('search_and_expand'));
  if (searchResult && searchResult.data) {
    console.log('\n🔍 Search API Format Check:');
    const search = searchResult.data;

    if (search.nodes !== undefined) {
      console.log(`   ✅ nodes array: ${Array.isArray(search.nodes) ? search.nodes.length + ' items' : 'not array'}`);
    } else {
      console.log('   ❌ Missing nodes array in search results');
    }

    if (search.edges !== undefined) {
      console.log(`   ✅ edges array: ${Array.isArray(search.edges) ? search.edges.length + ' items' : 'not array'}`);
    } else {
      console.log('   ❌ Missing edges array in search results');
    }
  }
}

// Run the test
testKnowledgeGraphIntegration().catch(console.error);
