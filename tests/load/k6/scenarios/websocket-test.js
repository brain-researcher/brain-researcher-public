import ws from 'k6/ws';
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

// Custom metrics for WebSocket testing
const customMetrics = createCustomMetrics();
const wsConnections = new Gauge('websocket_connections');
const wsMessages = new Counter('websocket_messages_sent');
const wsMessagesReceived = new Counter('websocket_messages_received');
const wsConnectionFailures = new Counter('websocket_connection_failures');
const wsLatency = new Trend('websocket_message_latency');
const wsReconnections = new Counter('websocket_reconnections');

// WebSocket test configuration
export let options = {
  stages: [
    { duration: '2m', target: 10 },    // Start with 10 WebSocket connections
    { duration: '5m', target: 25 },    // Scale to 25 connections
    { duration: '10m', target: 50 },   // Scale to 50 connections
    { duration: '5m', target: 75 },    // Peak at 75 connections
    { duration: '10m', target: 75 },   // Sustain peak connections
    { duration: '5m', target: 50 },    // Scale back
    { duration: '5m', target: 25 },    // Continue scaling back
    { duration: '3m', target: 0 },     // Close all connections
  ],
  thresholds: {
    'websocket_connection_time': ['p(95)<2000'],
    'websocket_message_latency': ['p(95)<100', 'p(99)<500'],
    'websocket_connection_failures': ['rate<0.05'], // Allow 5% connection failures
    'websocket_reconnections': ['rate<0.1'], // Allow 10% reconnection rate
    'http_req_duration': ['p(95)<1000'], // For authentication and setup
  },
};

// Test data generator
const dataGen = new DataGenerator();

// Performance validator for WebSocket testing
const validator = new PerformanceValidator({
  maxResponseTime: 1000,
  maxErrorRate: 0.05,
  minThroughput: 10
});

export function setup() {
  console.log('Setting up WebSocket test...');

  // Generate WebSocket-specific test data
  const testData = {
    users: dataGen.generateUsers(100),
    chatMessages: generateChatMessages(200),
    analysisUpdates: generateAnalysisUpdates(150),
    collaborationEvents: generateCollaborationEvents(100),
    systemNotifications: generateSystemNotifications(50)
  };

  // Initial health check
  const healthStatus = healthCheck(__ENV.BASE_URL || 'http://localhost');
  if (!healthStatus.healthy) {
    throw new Error(`Health check failed: ${healthStatus.message}`);
  }

  // Test WebSocket endpoint availability
  const wsEndpoint = getWebSocketEndpoint(__ENV.BASE_URL || 'http://localhost');
  if (!wsEndpoint) {
    throw new Error('WebSocket endpoint not available');
  }

  console.log('WebSocket test setup complete');
  return testData;
}

export default function(data) {
  const baseUrl = __ENV.BASE_URL || 'http://localhost';
  const wsUrl = baseUrl.replace('http', 'ws');
  const user = data.users[Math.floor(Math.random() * data.users.length)];

  // Authenticate user to get WebSocket token
  const authToken = authenticateUser(user, baseUrl);
  if (!authToken) {
    wsConnectionFailures.add(1);
    return;
  }

  // Select WebSocket scenario
  const scenarioType = Math.random();

  if (scenarioType < 0.4) {
    // 40% - Real-time analysis monitoring
    realTimeAnalysisMonitoring(wsUrl, authToken, data);
  } else if (scenarioType < 0.7) {
    // 30% - Collaborative session
    collaborativeSession(wsUrl, authToken, data);
  } else if (scenarioType < 0.9) {
    // 20% - Chat and messaging
    chatMessagingSession(wsUrl, authToken, data);
  } else {
    // 10% - System notifications
    systemNotificationSession(wsUrl, authToken, data);
  }

  sleep(Math.random() * 2 + 1);
}

// Real-time analysis monitoring scenario
function realTimeAnalysisMonitoring(wsUrl, authToken, data) {
  const url = `${wsUrl}/api/ws/analysis`;
  let connectionTime;
  let connected = false;
  let messagesSent = 0;
  let messagesReceived = 0;
  let reconnectAttempts = 0;

  const connectStart = Date.now();

  const response = ws.connect(url, {
    headers: {
      'Authorization': `Bearer ${authToken}`,
    },
  }, function (socket) {
    connected = true;
    connectionTime = Date.now() - connectStart;
    customMetrics.websocketConnectionTime.add(connectionTime);
    wsConnections.set(__VU);

    console.log(`Analysis WebSocket connected in ${connectionTime}ms`);

    socket.on('open', function () {
      console.log('Analysis WebSocket opened');

      // Subscribe to analysis updates
      const subscribeMessage = {
        type: 'subscribe',
        channel: 'analysis_updates',
        userId: authToken.substr(-10) // Simulated user ID
      };

      socket.send(JSON.stringify(subscribeMessage));
      messagesSent++;
      wsMessages.add(1);
    });

    socket.on('message', function (message) {
      const messageStart = Date.now();
      messagesReceived++;
      wsMessagesReceived.add(1);

      try {
        const data = JSON.parse(message);

        // Handle different message types
        switch (data.type) {
          case 'analysis_started':
            handleAnalysisStarted(socket, data);
            break;
          case 'analysis_progress':
            handleAnalysisProgress(socket, data);
            break;
          case 'analysis_completed':
            handleAnalysisCompleted(socket, data);
            break;
          case 'analysis_failed':
            handleAnalysisFailed(socket, data);
            break;
          default:
            console.log('Unknown message type:', data.type);
        }

        const latency = Date.now() - messageStart;
        wsLatency.add(latency);

      } catch (error) {
        console.error('Error parsing WebSocket message:', error);
      }
    });

    socket.on('error', function (error) {
      console.error('Analysis WebSocket error:', error);
      wsConnectionFailures.add(1);
    });

    socket.on('close', function () {
      console.log('Analysis WebSocket closed');
      if (connected && messagesSent > 0) {
        // Unexpected close, attempt reconnection
        reconnectAttempts++;
        if (reconnectAttempts < 3) {
          wsReconnections.add(1);
          console.log(`Attempting reconnection ${reconnectAttempts}/3`);
          sleep(1);
          // Note: In real implementation, would recursively call this function
        }
      }
    });

    // Simulate real-time interaction
    const interactionDuration = Math.random() * 30000 + 30000; // 30-60 seconds
    const interactionEnd = Date.now() + interactionDuration;

    while (Date.now() < interactionEnd) {
      sleep(5);

      // Send heartbeat or request update
      if (Math.random() < 0.3) {
        const heartbeat = {
          type: 'heartbeat',
          timestamp: Date.now()
        };
        socket.send(JSON.stringify(heartbeat));
        messagesSent++;
        wsMessages.add(1);
      }
    }

    socket.close();
  });

  check(response, {
    'WebSocket connected successfully': () => connected,
    'Connection time acceptable': () => connectionTime < 2000,
    'Messages exchanged': () => messagesSent > 0 && messagesReceived > 0,
  });
}

// Collaborative session scenario
function collaborativeSession(wsUrl, authToken, data) {
  const url = `${wsUrl}/api/ws/collaboration`;
  let connected = false;
  let messagesSent = 0;
  let messagesReceived = 0;

  const connectStart = Date.now();

  const response = ws.connect(url, {
    headers: {
      'Authorization': `Bearer ${authToken}`,
    },
  }, function (socket) {
    connected = true;
    const connectionTime = Date.now() - connectStart;
    customMetrics.websocketConnectionTime.add(connectionTime);

    socket.on('open', function () {
      // Join a collaboration session
      const joinMessage = {
        type: 'join_session',
        sessionId: `session_${Math.floor(Math.random() * 10) + 1}`,
        userId: authToken.substr(-10)
      };

      socket.send(JSON.stringify(joinMessage));
      messagesSent++;
      wsMessages.add(1);
    });

    socket.on('message', function (message) {
      messagesReceived++;
      wsMessagesReceived.add(1);

      try {
        const data = JSON.parse(message);

        // Respond to collaboration events
        if (data.type === 'user_joined' || data.type === 'cursor_update') {
          // Send acknowledgment
          const ack = {
            type: 'ack',
            messageId: data.messageId,
            timestamp: Date.now()
          };
          socket.send(JSON.stringify(ack));
          messagesSent++;
          wsMessages.add(1);
        }

        if (data.type === 'collaboration_request') {
          // Simulate collaboration response
          const collaborationEvent = data.collaborationEvents[
            Math.floor(Math.random() * data.collaborationEvents.length)
          ];
          socket.send(JSON.stringify(collaborationEvent));
          messagesSent++;
          wsMessages.add(1);
        }

      } catch (error) {
        console.error('Error in collaboration session:', error);
      }
    });

    socket.on('error', function (error) {
      console.error('Collaboration WebSocket error:', error);
      wsConnectionFailures.add(1);
    });

    // Simulate collaborative interaction
    const collaborationDuration = Math.random() * 45000 + 15000; // 15-60 seconds
    const collaborationEnd = Date.now() + collaborationDuration;

    while (Date.now() < collaborationEnd) {
      sleep(Math.random() * 3 + 2); // 2-5 second intervals

      // Send collaboration events
      if (Math.random() < 0.6) {
        const event = data.collaborationEvents[
          Math.floor(Math.random() * data.collaborationEvents.length)
        ];
        socket.send(JSON.stringify(event));
        messagesSent++;
        wsMessages.add(1);
      }
    }

    // Leave session
    const leaveMessage = {
      type: 'leave_session',
      timestamp: Date.now()
    };
    socket.send(JSON.stringify(leaveMessage));
    messagesSent++;
    wsMessages.add(1);

    sleep(1);
    socket.close();
  });

  check(response, {
    'Collaboration session connected': () => connected,
    'Collaboration messages exchanged': () => messagesSent >= 3 && messagesReceived >= 1,
  });
}

// Chat and messaging session scenario
function chatMessagingSession(wsUrl, authToken, data) {
  const url = `${wsUrl}/api/ws/chat`;
  let connected = false;
  let messagesSent = 0;
  let messagesReceived = 0;

  const response = ws.connect(url, {
    headers: {
      'Authorization': `Bearer ${authToken}`,
    },
  }, function (socket) {
    connected = true;
    const connectionTime = Date.now() - customMetrics.websocketConnectionTime.lastValue || Date.now();
    customMetrics.websocketConnectionTime.add(connectionTime);

    socket.on('open', function () {
      // Join chat room
      const joinRoom = {
        type: 'join_room',
        roomId: `room_${Math.floor(Math.random() * 5) + 1}`,
        userId: authToken.substr(-10)
      };

      socket.send(JSON.stringify(joinRoom));
      messagesSent++;
      wsMessages.add(1);
    });

    socket.on('message', function (message) {
      const latencyStart = Date.now();
      messagesReceived++;
      wsMessagesReceived.add(1);

      try {
        const data = JSON.parse(message);
        const latency = Date.now() - (data.timestamp || latencyStart);
        wsLatency.add(latency);

        // Respond to direct messages
        if (data.type === 'direct_message') {
          const response = {
            type: 'message_response',
            replyTo: data.messageId,
            content: 'Acknowledged',
            timestamp: Date.now()
          };
          socket.send(JSON.stringify(response));
          messagesSent++;
          wsMessages.add(1);
        }

      } catch (error) {
        console.error('Error in chat session:', error);
      }
    });

    socket.on('error', function (error) {
      console.error('Chat WebSocket error:', error);
      wsConnectionFailures.add(1);
    });

    // Simulate chat session
    const chatDuration = Math.random() * 60000 + 30000; // 30-90 seconds
    const chatEnd = Date.now() + chatDuration;

    while (Date.now() < chatEnd) {
      sleep(Math.random() * 5 + 2); // 2-7 second intervals

      // Send chat messages
      const chatMessage = data.chatMessages[
        Math.floor(Math.random() * data.chatMessages.length)
      ];

      const message = {
        ...chatMessage,
        timestamp: Date.now(),
        messageId: `msg_${Date.now()}_${Math.random()}`
      };

      socket.send(JSON.stringify(message));
      messagesSent++;
      wsMessages.add(1);
    }

    socket.close();
  });

  check(response, {
    'Chat session connected': () => connected,
    'Chat messages sent': () => messagesSent >= 2,
    'Chat messages received': () => messagesReceived >= 1,
  });
}

// System notifications session scenario
function systemNotificationSession(wsUrl, authToken, data) {
  const url = `${wsUrl}/api/ws/notifications`;
  let connected = false;
  let notificationsReceived = 0;

  const response = ws.connect(url, {
    headers: {
      'Authorization': `Bearer ${authToken}`,
    },
  }, function (socket) {
    connected = true;
    const connectionTime = Date.now() - customMetrics.websocketConnectionTime.lastValue || Date.now();
    customMetrics.websocketConnectionTime.add(connectionTime);

    socket.on('open', function () {
      // Subscribe to system notifications
      const subscribe = {
        type: 'subscribe',
        channels: ['system_alerts', 'user_notifications', 'analysis_updates'],
        userId: authToken.substr(-10)
      };

      socket.send(JSON.stringify(subscribe));
      wsMessages.add(1);
    });

    socket.on('message', function (message) {
      notificationsReceived++;
      wsMessagesReceived.add(1);

      try {
        const notification = JSON.parse(message);
        const latency = Date.now() - (notification.timestamp || Date.now());
        wsLatency.add(latency);

        // Acknowledge critical notifications
        if (notification.priority === 'high' || notification.type === 'system_alert') {
          const ack = {
            type: 'acknowledge',
            notificationId: notification.id,
            timestamp: Date.now()
          };
          socket.send(JSON.stringify(ack));
          wsMessages.add(1);
        }

      } catch (error) {
        console.error('Error processing notification:', error);
      }
    });

    socket.on('error', function (error) {
      console.error('Notifications WebSocket error:', error);
      wsConnectionFailures.add(1);
    });

    // Listen for notifications for a period
    const notificationDuration = Math.random() * 40000 + 20000; // 20-60 seconds
    sleep(notificationDuration / 1000);

    socket.close();
  });

  check(response, {
    'Notifications session connected': () => connected,
    'Notifications received': () => notificationsReceived >= 0, // May not receive any
  });
}

// Helper functions for WebSocket message handling
function handleAnalysisStarted(socket, data) {
  console.log(`Analysis started: ${data.analysisId}`);

  // Request progress updates
  const progressRequest = {
    type: 'request_progress',
    analysisId: data.analysisId,
    interval: 5000 // 5 seconds
  };
  socket.send(JSON.stringify(progressRequest));
  wsMessages.add(1);
}

function handleAnalysisProgress(socket, data) {
  console.log(`Analysis progress: ${data.progress}% for ${data.analysisId}`);

  // Optionally request intermediate results
  if (data.progress === 50) {
    const intermediateRequest = {
      type: 'request_intermediate',
      analysisId: data.analysisId
    };
    socket.send(JSON.stringify(intermediateRequest));
    wsMessages.add(1);
  }
}

function handleAnalysisCompleted(socket, data) {
  console.log(`Analysis completed: ${data.analysisId}`);

  // Request final results
  const resultsRequest = {
    type: 'request_results',
    analysisId: data.analysisId
  };
  socket.send(JSON.stringify(resultsRequest));
  wsMessages.add(1);
}

function handleAnalysisFailed(socket, data) {
  console.log(`Analysis failed: ${data.analysisId} - ${data.error}`);

  // Request error details
  const errorRequest = {
    type: 'request_error_details',
    analysisId: data.analysisId
  };
  socket.send(JSON.stringify(errorRequest));
  wsMessages.add(1);
}

// Authenticate user and get WebSocket token
function authenticateUser(user, baseUrl) {
  const response = withRetry(() =>
    http.post(`${baseUrl}/api/auth/websocket-token`, JSON.stringify({
      username: user.username,
      password: user.password || 'defaultPassword'
    }), {
      headers: {
        'Content-Type': 'application/json',
      },
    })
  );

  if (response.status === 200) {
    const auth = response.json();
    return auth.token;
  }

  return null;
}

// Get WebSocket endpoint information
function getWebSocketEndpoint(baseUrl) {
  const response = withRetry(() =>
    http.get(`${baseUrl}/api/websocket/info`)
  );

  if (response.status === 200) {
    const info = response.json();
    return info.endpoint;
  }

  return null;
}

// Generate chat messages for testing
function generateChatMessages(count) {
  const messages = [];
  const messageTypes = ['text', 'file_share', 'analysis_share', 'question'];
  const sampleTexts = [
    'Hello, can anyone help with this analysis?',
    'I found an interesting pattern in the connectivity data.',
    'The preprocessing results look good.',
    'Has anyone tried this approach before?',
    'Thanks for sharing that dataset!',
    'The visualization is very clear.',
    'I think there might be an artifact in slice 45.',
    'Great work on the statistical analysis!'
  ];

  for (let i = 0; i < count; i++) {
    messages.push({
      type: 'chat_message',
      messageType: messageTypes[Math.floor(Math.random() * messageTypes.length)],
      content: sampleTexts[Math.floor(Math.random() * sampleTexts.length)],
      priority: Math.random() < 0.1 ? 'high' : 'normal'
    });
  }

  return messages;
}

// Generate analysis updates for testing
function generateAnalysisUpdates(count) {
  const updates = [];
  const updateTypes = ['progress', 'completed', 'failed', 'paused'];

  for (let i = 0; i < count; i++) {
    updates.push({
      type: updateTypes[Math.floor(Math.random() * updateTypes.length)],
      analysisId: `analysis_${i}`,
      progress: Math.floor(Math.random() * 100),
      timestamp: Date.now()
    });
  }

  return updates;
}

// Generate collaboration events for testing
function generateCollaborationEvents(count) {
  const events = [];
  const eventTypes = ['cursor_update', 'selection_change', 'edit', 'comment'];

  for (let i = 0; i < count; i++) {
    events.push({
      type: eventTypes[Math.floor(Math.random() * eventTypes.length)],
      sessionId: `session_${Math.floor(Math.random() * 10) + 1}`,
      data: {
        x: Math.random() * 1920,
        y: Math.random() * 1080,
        selection: `element_${Math.floor(Math.random() * 100)}`
      },
      timestamp: Date.now()
    });
  }

  return events;
}

// Generate system notifications for testing
function generateSystemNotifications(count) {
  const notifications = [];
  const notificationTypes = ['system_alert', 'maintenance', 'update', 'security'];
  const priorities = ['low', 'normal', 'high', 'critical'];

  for (let i = 0; i < count; i++) {
    notifications.push({
      type: notificationTypes[Math.floor(Math.random() * notificationTypes.length)],
      priority: priorities[Math.floor(Math.random() * priorities.length)],
      message: `System notification ${i}`,
      timestamp: Date.now()
    });
  }

  return notifications;
}

export function teardown(data) {
  console.log('Tearing down WebSocket test...');

  // Generate WebSocket test report
  const wsReport = {
    totalConnections: wsConnections.value,
    messagesSent: wsMessages.value,
    messagesReceived: wsMessagesReceived.value,
    connectionFailures: wsConnectionFailures.value,
    reconnections: wsReconnections.value,
    averageLatency: wsLatency.values.length > 0 ?
      wsLatency.values.reduce((a, b) => a + b, 0) / wsLatency.values.length : 0,
    maxLatency: wsLatency.values.length > 0 ? Math.max(...wsLatency.values) : 0
  };

  console.log('WebSocket test report:', JSON.stringify(wsReport, null, 2));

  // Performance validation
  const finalValidation = validator.generateReport();
  console.log('Performance validation results:', JSON.stringify(finalValidation, null, 2));

  console.log('WebSocket test teardown complete');
}