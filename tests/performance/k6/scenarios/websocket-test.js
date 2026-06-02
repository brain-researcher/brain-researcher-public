/**
 * WebSocket Testing Scenario for Brain Researcher Real-time Features
 *
 * This test validates WebSocket connections, real-time job updates,
 * and concurrent connection handling for the orchestrator service.
 */

import { check, group, sleep, fail } from 'k6';
import ws from 'k6/ws';
import { CONFIG } from '../config/k6.config.js';
import {
  OrchestratorAPI,
  WebSocketManager,
  TestDataGenerator,
  wsConnectTime,
  successfulRequests,
  failedRequests
} from '../scripts/utils.js';
import { Counter, Rate, Gauge, Trend } from 'k6/metrics';

// WebSocket-specific metrics
const wsConnections = new Counter('ws_connections');
const wsConnectionFailures = new Counter('ws_connection_failures');
const wsMessagesReceived = new Counter('ws_messages_received');
const wsMessagesSent = new Counter('ws_messages_sent');
const wsConnectionDuration = new Trend('ws_connection_duration', true);
const wsMessageLatency = new Trend('ws_message_latency', true);
const activeConcurrentConnections = new Gauge('ws_concurrent_connections');

// WebSocket test configuration
export let options = {
  stages: [
    { duration: '1m', target: 5 },   // Start with few connections
    { duration: '3m', target: 20 },  // Scale up to moderate load
    { duration: '2m', target: 50 },  // Test higher concurrent connections
    { duration: '2m', target: 20 },  // Scale back down
    { duration: '1m', target: 0 },   // Clean shutdown
  ],
  thresholds: {
    // WebSocket connection thresholds
    'ws_connecting': ['p(95)<2000'], // Connection establishment under 2s
    'ws_connection_duration': ['avg>10000'], // Connections should stay alive
    'ws_messages_received': ['count>100'], // Should receive messages
    'ws_messages_sent': ['count>50'], // Should send messages
    'ws_message_latency': ['p(95)<1000'], // Message round-trip under 1s

    // Connection stability
    'ws_connection_failures': ['rate<0.1'], // Less than 10% connection failures
    'ws_concurrent_connections': ['value>0'], // Should maintain connections

    // HTTP fallback performance
    'http_req_duration': ['p(95)<3000'],
    'http_req_failed': ['rate<0.05'],
  },
  summaryTrendStats: ['avg', 'min', 'med', 'max', 'p(90)', 'p(95)', 'p(99)'],
};

// Initialize clients
const orchestrator = new OrchestratorAPI();
const wsManager = new WebSocketManager(CONFIG.ORCHESTRATOR_URL);

// Connection tracking
let connectionTracker = {
  activeConnections: new Map(),
  connectionStats: {
    total: 0,
    successful: 0,
    failed: 0,
    closed: 0
  },
  messageStats: {
    sent: 0,
    received: 0,
    pingPong: 0
  }
};

export function setup() {
  console.log('Starting WebSocket test setup...');

  // Verify HTTP endpoints are working
  const healthCheck = orchestrator.healthCheck();
  if (!healthCheck) {
    throw new Error('Orchestrator service not available for WebSocket testing');
  }

  // Create a test job to monitor
  const testJobResult = orchestrator.createRun(
    'Test job for WebSocket monitoring',
    'glm',
    'ds000001'
  );

  console.log('WebSocket test environment ready');

  return {
    setupTime: Date.now(),
    testJobCreated: testJobResult
  };
}

export default function(data) {
  const connectionId = `ws_${__VU}_${__ITER}`;

  // Run different WebSocket scenarios
  const scenario = __ITER % 3;

  switch (scenario) {
    case 0:
      testJobUpdatesWebSocket(connectionId);
      break;
    case 1:
      testLongLivedConnection(connectionId);
      break;
    case 2:
      testReconnectionScenario(connectionId);
      break;
  }

  sleep(2 + Math.random() * 3); // 2-5 second intervals
}

function testJobUpdatesWebSocket(connectionId) {
  group('WebSocket Job Updates Test', () => {
    // First create a job to monitor
    const createJobResult = orchestrator.createRun(
      TestDataGenerator.generateFMRIQuery(),
      'connectivity',
      'motor-task-sample'
    );

    if (!createJobResult) {
      console.log('Failed to create job for WebSocket test');
      return;
    }

    // Simulate extracting job_id from response
    const mockJobId = `job_ws_${Date.now()}_${__VU}`;

    // Connect to WebSocket for job updates
    const wsUrl = `${CONFIG.ORCHESTRATOR_URL.replace('http', 'ws')}/ws/jobs/${mockJobId}`;
    const connectionStart = Date.now();

    wsConnections.add(1);
    connectionTracker.connectionStats.total++;

    const response = ws.connect(wsUrl, {}, function(socket) {
      const connectionTime = Date.now() - connectionStart;
      wsConnectTime.add(connectionTime);
      wsConnectionDuration.add(connectionTime);

      connectionTracker.connectionStats.successful++;
      connectionTracker.activeConnections.set(connectionId, {
        socket,
        startTime: Date.now(),
        messagesReceived: 0,
        messagesSent: 0
      });

      activeConcurrentConnections.add(connectionTracker.activeConnections.size);

      socket.on('open', () => {
        console.log(`WebSocket connected: ${connectionId}`);
      });

      socket.on('message', (data) => {
        const message = JSON.parse(data);
        wsMessagesReceived.add(1);
        connectionTracker.messageStats.received++;

        const connection = connectionTracker.activeConnections.get(connectionId);
        if (connection) {
          connection.messagesReceived++;
        }

        // Handle different message types
        switch (message.type) {
          case 'init':
            validateInitMessage(message, connectionId);
            break;
          case 'status':
            validateStatusMessage(message, connectionId);
            break;
          case 'step':
            validateStepMessage(message, connectionId);
            break;
          case 'artifact':
            validateArtifactMessage(message, connectionId);
            break;
          default:
            console.log(`Unknown message type: ${message.type}`);
        }

        // Send acknowledgment
        const ackMessage = JSON.stringify({
          type: 'ack',
          messageId: message.id || Date.now(),
          timestamp: Date.now()
        });

        socket.send(ackMessage);
        wsMessagesSent.add(1);
        connectionTracker.messageStats.sent++;
      });

      socket.on('error', (e) => {
        console.log(`WebSocket error for ${connectionId}: ${e}`);
        wsConnectionFailures.add(1);
        connectionTracker.connectionStats.failed++;
      });

      socket.on('close', () => {
        console.log(`WebSocket closed: ${connectionId}`);
        connectionTracker.activeConnections.delete(connectionId);
        connectionTracker.connectionStats.closed++;
        activeConcurrentConnections.add(connectionTracker.activeConnections.size);
      });

      // Send periodic ping messages
      const pingInterval = setInterval(() => {
        if (socket.readyState === 1) { // OPEN
          const pingMessage = JSON.stringify({
            type: 'ping',
            timestamp: Date.now(),
            connectionId: connectionId
          });

          socket.send(pingMessage);
          wsMessagesSent.add(1);
          connectionTracker.messageStats.pingPong++;
        }
      }, 10000); // Ping every 10 seconds

      // Keep connection alive for testing duration
      sleep(15 + Math.random() * 10); // 15-25 seconds

      clearInterval(pingInterval);
    });

    // Validate WebSocket connection
    check(response, {
      'websocket_connection_established': (r) => r && r.status === 101,
    });
  });
}

function testLongLivedConnection(connectionId) {
  group('Long-lived WebSocket Connection Test', () => {
    const wsUrl = `${CONFIG.ORCHESTRATOR_URL.replace('http', 'ws')}/ws/jobs/long_lived_${connectionId}`;

    const response = ws.connect(wsUrl, {}, function(socket) {
      connectionTracker.activeConnections.set(connectionId, {
        socket,
        startTime: Date.now(),
        messagesReceived: 0,
        messagesSent: 0
      });

      let messageCount = 0;
      const maxMessages = 20;

      socket.on('open', () => {
        console.log(`Long-lived connection established: ${connectionId}`);

        // Send initial message
        const initialMessage = JSON.stringify({
          type: 'subscribe',
          topics: ['job_updates', 'system_status'],
          connectionId: connectionId
        });

        socket.send(initialMessage);
        wsMessagesSent.add(1);
      });

      socket.on('message', (data) => {
        const message = JSON.parse(data);
        wsMessagesReceived.add(1);
        messageCount++;

        const latency = Date.now() - (message.timestamp || Date.now());
        wsMessageLatency.add(latency);

        // Send response to keep conversation going
        if (messageCount < maxMessages) {
          const responseMessage = JSON.stringify({
            type: 'response',
            originalType: message.type,
            messageNumber: messageCount,
            timestamp: Date.now()
          });

          setTimeout(() => {
            socket.send(responseMessage);
            wsMessagesSent.add(1);
          }, 500 + Math.random() * 1000); // Random delay 0.5-1.5s
        }
      });

      // Keep connection alive longer for long-lived test
      sleep(30 + Math.random() * 15); // 30-45 seconds
    });

    check(response, {
      'long_lived_connection_successful': (r) => r && r.status === 101,
    });
  });
}

function testReconnectionScenario(connectionId) {
  group('WebSocket Reconnection Test', () => {
    let reconnectAttempts = 0;
    const maxReconnects = 3;

    function attemptConnection(attempt = 1) {
      const wsUrl = `${CONFIG.ORCHESTRATOR_URL.replace('http', 'ws')}/ws/jobs/reconnect_${connectionId}_${attempt}`;

      console.log(`Connection attempt ${attempt} for ${connectionId}`);

      const response = ws.connect(wsUrl, {}, function(socket) {
        connectionTracker.activeConnections.set(`${connectionId}_${attempt}`, {
          socket,
          startTime: Date.now(),
          attempt: attempt
        });

        socket.on('open', () => {
          console.log(`Reconnection attempt ${attempt} successful: ${connectionId}`);

          // Send test messages
          for (let i = 0; i < 5; i++) {
            setTimeout(() => {
              const testMessage = JSON.stringify({
                type: 'test',
                attempt: attempt,
                messageNumber: i,
                timestamp: Date.now()
              });

              socket.send(testMessage);
              wsMessagesSent.add(1);
            }, i * 1000);
          }
        });

        socket.on('message', (data) => {
          wsMessagesReceived.add(1);
        });

        socket.on('error', (e) => {
          console.log(`Connection attempt ${attempt} failed: ${e}`);
          wsConnectionFailures.add(1);

          if (attempt < maxReconnects) {
            console.log(`Retrying connection for ${connectionId}, attempt ${attempt + 1}`);
            sleep(1); // Wait before retry
            attemptConnection(attempt + 1);
          }
        });

        // Simulate connection drop for testing reconnection
        if (attempt === 1) {
          setTimeout(() => {
            console.log(`Simulating connection drop for ${connectionId}`);
            socket.close();
          }, 10000); // Close after 10 seconds
        }

        sleep(20); // Keep connection for 20 seconds
      });

      return response;
    }

    const finalResponse = attemptConnection(1);

    check(finalResponse, {
      'reconnection_scenario_completed': (r) => r !== null,
    });
  });
}

function validateInitMessage(message, connectionId) {
  const valid = check(message, {
    'init_message_has_job_data': (m) => m.job && typeof m.job === 'object',
    'init_message_has_type': (m) => m.type === 'init',
  });

  if (!valid) {
    console.log(`Invalid init message for ${connectionId}`);
  }
}

function validateStatusMessage(message, connectionId) {
  const valid = check(message, {
    'status_message_has_status': (m) => m.status && typeof m.status === 'string',
    'status_message_valid_status': (m) => ['pending', 'running', 'completed', 'failed'].includes(m.status),
  });

  if (!valid) {
    console.log(`Invalid status message for ${connectionId}`);
  }
}

function validateStepMessage(message, connectionId) {
  const valid = check(message, {
    'step_message_has_step_data': (m) => m.step && typeof m.step === 'object',
    'step_message_has_step_id': (m) => m.step && m.step.id,
  });

  if (!valid) {
    console.log(`Invalid step message for ${connectionId}`);
  }
}

function validateArtifactMessage(message, connectionId) {
  const valid = check(message, {
    'artifact_message_has_artifact': (m) => m.artifact && typeof m.artifact === 'object',
    'artifact_message_has_url': (m) => m.artifact && m.artifact.url,
  });

  if (!valid) {
    console.log(`Invalid artifact message for ${connectionId}`);
  }
}

export function teardown(data) {
  console.log('WebSocket test completed');

  // Close any remaining connections
  connectionTracker.activeConnections.forEach((connection, id) => {
    if (connection.socket && connection.socket.readyState === 1) {
      connection.socket.close();
    }
  });

  console.log('=== WEBSOCKET TEST STATISTICS ===');
  console.log(`Total connections attempted: ${connectionTracker.connectionStats.total}`);
  console.log(`Successful connections: ${connectionTracker.connectionStats.successful}`);
  console.log(`Failed connections: ${connectionTracker.connectionStats.failed}`);
  console.log(`Messages sent: ${connectionTracker.messageStats.sent}`);
  console.log(`Messages received: ${connectionTracker.messageStats.received}`);
  console.log(`Ping/pong messages: ${connectionTracker.messageStats.pingPong}`);

  return { connectionTracker };
}

export function handleSummary(data) {
  const summary = {
    'websocket_test_summary.json': JSON.stringify({
      ...data,
      connectionTracker: connectionTracker
    }, null, 2),
    'websocket_test_summary.html': generateWebSocketReport(data),
    stdout: generateWebSocketConsoleReport(data)
  };

  return summary;
}

function generateWebSocketConsoleReport(data) {
  const duration = data.state.testRunDurationMs / 1000;
  const wsConnectionsTotal = connectionTracker.connectionStats.total;
  const wsSuccessRate = wsConnectionsTotal > 0 ?
    (connectionTracker.connectionStats.successful / wsConnectionsTotal * 100).toFixed(2) : 0;

  return `
=== WEBSOCKET TEST SUMMARY ===
Test Duration: ${duration.toFixed(2)}s
WebSocket Connections: ${wsConnectionsTotal}
Connection Success Rate: ${wsSuccessRate}%

Real-time Communication:
- Messages Sent: ${connectionTracker.messageStats.sent}
- Messages Received: ${connectionTracker.messageStats.received}
- Ping/Pong Exchanges: ${connectionTracker.messageStats.pingPong}
- Average Message Rate: ${((connectionTracker.messageStats.sent + connectionTracker.messageStats.received) / duration).toFixed(2)}/s

Connection Stability:
- Successful Connections: ${connectionTracker.connectionStats.successful}
- Failed Connections: ${connectionTracker.connectionStats.failed}
- Closed Connections: ${connectionTracker.connectionStats.closed}

Performance Metrics:
- Avg Connection Time: ${data.metrics.ws_connecting?.values?.avg?.toFixed(2) || 'N/A'}ms
- P95 Connection Time: ${data.metrics.ws_connecting?.values?.['p(95)']?.toFixed(2) || 'N/A'}ms
- Avg Message Latency: ${data.metrics.ws_message_latency?.values?.avg?.toFixed(2) || 'N/A'}ms

WebSocket Health:
${wsSuccessRate > 90 ? '✅ Excellent connection reliability' : '⚠️ Connection issues detected'}
${connectionTracker.messageStats.received > 100 ? '✅ Good message throughput' : '⚠️ Low message activity'}
${connectionTracker.connectionStats.failed < 2 ? '✅ Minimal connection failures' : '⚠️ Multiple connection failures'}

Real-time Features:
${generateWebSocketRecommendations(data, connectionTracker)}
========================
  `;
}

function generateWebSocketRecommendations(data, tracker) {
  const recommendations = [];
  const successRate = tracker.connectionStats.total > 0 ?
    (tracker.connectionStats.successful / tracker.connectionStats.total) : 1;

  if (successRate < 0.9) {
    recommendations.push('- Investigate WebSocket connection reliability issues');
  }

  if (tracker.connectionStats.failed > 5) {
    recommendations.push('- Review WebSocket server configuration and capacity');
  }

  if (tracker.messageStats.received < tracker.messageStats.sent * 0.5) {
    recommendations.push('- Check message handling and response mechanisms');
  }

  const avgLatency = data.metrics.ws_message_latency?.values?.avg;
  if (avgLatency && avgLatency > 1000) {
    recommendations.push('- Optimize message processing for better real-time performance');
  }

  if (tracker.messageStats.pingPong < 10) {
    recommendations.push('- Implement proper keepalive mechanisms for long-lived connections');
  }

  if (recommendations.length === 0) {
    recommendations.push('- WebSocket implementation performs well');
    recommendations.push('- Consider testing with higher concurrent connection loads');
  }

  return recommendations.join('\n');
}

function generateWebSocketReport(data) {
  const timestamp = new Date().toISOString();
  const duration = data.state.testRunDurationMs / 1000;
  const successRate = connectionTracker.connectionStats.total > 0 ?
    (connectionTracker.connectionStats.successful / connectionTracker.connectionStats.total * 100).toFixed(2) : 0;

  return `
<!DOCTYPE html>
<html>
<head>
    <title>Brain Researcher WebSocket Test Report</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background-color: #f8f9fa; }
        .header { background: linear-gradient(135deg, #20c997, #17a2b8); color: white; padding: 20px; border-radius: 5px; }
        .realtime-indicator { background: #d1ecf1; border-left: 4px solid #17a2b8; padding: 15px; margin: 15px 0; }
        .connection-stats { display: flex; justify-content: space-around; margin: 20px 0; }
        .stat-box { background: white; padding: 20px; border-radius: 5px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .stat-value { font-size: 2em; font-weight: bold; color: #17a2b8; }
        .metric-group { background: white; margin: 20px 0; padding: 20px; border-radius: 5px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .success { color: #28a745; }
        .warning { color: #ffc107; }
        .error { color: #dc3545; }
        .summary-table { width: 100%; border-collapse: collapse; margin: 20px 0; }
        .summary-table th, .summary-table td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
        .summary-table th { background-color: #17a2b8; color: white; }
        .message-flow { background: #f8f9fa; padding: 15px; border-radius: 5px; margin: 15px 0; text-align: center; }
    </style>
</head>
<body>
    <div class="header">
        <h1>🔌 Brain Researcher WebSocket Test Report</h1>
        <p><strong>Generated:</strong> ${timestamp}</p>
        <p><strong>Duration:</strong> ${duration.toFixed(2)} seconds</p>
        <p><strong>Real-time Connection Testing</strong></p>
    </div>

    <div class="realtime-indicator">
        <h3>⚡ Real-time Communication Analysis</h3>
        <p>This test validates WebSocket connections for job updates, system notifications, and bidirectional real-time communication between the web UI and backend services.</p>
    </div>

    <div class="connection-stats">
        <div class="stat-box">
            <div class="stat-value ${successRate > 90 ? 'success' : successRate > 70 ? 'warning' : 'error'}">${successRate}%</div>
            <div>Connection Success Rate</div>
        </div>
        <div class="stat-box">
            <div class="stat-value">${connectionTracker.connectionStats.total}</div>
            <div>Total Connections</div>
        </div>
        <div class="stat-box">
            <div class="stat-value">${connectionTracker.messageStats.received}</div>
            <div>Messages Received</div>
        </div>
        <div class="stat-box">
            <div class="stat-value">${connectionTracker.messageStats.sent}</div>
            <div>Messages Sent</div>
        </div>
    </div>

    <div class="message-flow">
        <h4>📡 Message Flow Analysis</h4>
        <p><strong>Sent:</strong> ${connectionTracker.messageStats.sent} |
           <strong>Received:</strong> ${connectionTracker.messageStats.received} |
           <strong>Ping/Pong:</strong> ${connectionTracker.messageStats.pingPong}</p>
        <p><strong>Message Rate:</strong> ${((connectionTracker.messageStats.sent + connectionTracker.messageStats.received) / duration).toFixed(2)} messages/second</p>
    </div>

    <div class="metric-group">
        <h2>📊 Connection Performance</h2>
        <table class="summary-table">
            <tr><th>Metric</th><th>Value</th><th>Assessment</th></tr>
            <tr><td>Total Connection Attempts</td><td>${connectionTracker.connectionStats.total}</td><td>-</td></tr>
            <tr><td>Successful Connections</td><td>${connectionTracker.connectionStats.successful}</td>
                <td class="${connectionTracker.connectionStats.successful === connectionTracker.connectionStats.total ? 'success' : 'warning'}">
                    ${connectionTracker.connectionStats.successful === connectionTracker.connectionStats.total ? '✅ Perfect' : '⚠️ Some Issues'}
                </td></tr>
            <tr><td>Failed Connections</td><td>${connectionTracker.connectionStats.failed}</td>
                <td class="${connectionTracker.connectionStats.failed === 0 ? 'success' : 'warning'}">
                    ${connectionTracker.connectionStats.failed === 0 ? '✅ None' : '⚠️ Investigate'}
                </td></tr>
            <tr><td>Average Connection Time</td><td>${data.metrics.ws_connecting?.values?.avg?.toFixed(2) || 'N/A'}ms</td>
                <td>${(data.metrics.ws_connecting?.values?.avg || 0) < 1000 ? '✅ Fast' : '⚠️ Slow'}</td></tr>
            <tr><td>P95 Connection Time</td><td>${data.metrics.ws_connecting?.values?.['p(95)']?.toFixed(2) || 'N/A'}ms</td>
                <td>${(data.metrics.ws_connecting?.values?.['p(95)'] || 0) < 2000 ? '✅ Good' : '⚠️ High Latency'}</td></tr>
        </table>
    </div>

    <div class="metric-group">
        <h2>🔄 Real-time Message Analysis</h2>
        <table class="summary-table">
            <tr><th>Message Type</th><th>Count</th><th>Performance</th></tr>
            <tr><td>Total Messages Sent</td><td>${connectionTracker.messageStats.sent}</td><td>-</td></tr>
            <tr><td>Total Messages Received</td><td>${connectionTracker.messageStats.received}</td><td>-</td></tr>
            <tr><td>Ping/Pong Keepalive</td><td>${connectionTracker.messageStats.pingPong}</td>
                <td>${connectionTracker.messageStats.pingPong > 0 ? '✅ Active' : '⚠️ No Keepalive'}</td></tr>
            <tr><td>Average Message Latency</td><td>${data.metrics.ws_message_latency?.values?.avg?.toFixed(2) || 'N/A'}ms</td>
                <td>${(data.metrics.ws_message_latency?.values?.avg || 0) < 500 ? '✅ Fast' : '⚠️ Slow'}</td></tr>
        </table>
    </div>

    <div class="metric-group">
        <h2>💡 WebSocket Implementation Assessment</h2>
        ${generateWebSocketRecommendations(data, connectionTracker).split('\n').map(rec =>
          rec.trim() ? `<div style="padding: 8px; margin: 5px 0; border-left: 3px solid #17a2b8; background: #d1ecf1;">${rec}</div>` : ''
        ).join('')}
    </div>

    <div class="metric-group">
        <h2>📋 Technical WebSocket Details</h2>
        <details>
            <summary>Click to view detailed connection and message data</summary>
            <pre style="background: #f8f9fa; padding: 20px; border-radius: 5px; overflow-x: auto; max-height: 400px;">${JSON.stringify({...data, connectionTracker}, null, 2)}</pre>
        </details>
    </div>
</body>
</html>
  `;
}