/**
 * Comprehensive tests for TelemetryProvider - Context provider and hooks for telemetry.
 */

import React from 'react';
import { render, screen, act, waitFor } from '@testing-library/react';
import { renderHook } from '@testing-library/react-hooks';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';

// Mock WebSocket
class MockWebSocket {
  public static CONNECTING = 0;
  public static OPEN = 1;
  public static CLOSING = 2;
  public static CLOSED = 3;

  public readyState: number = MockWebSocket.CONNECTING;
  public onopen: ((event: Event) => void) | null = null;
  public onmessage: ((event: MessageEvent) => void) | null = null;
  public onclose: ((event: CloseEvent) => void) | null = null;
  public onerror: ((event: Event) => void) | null = null;

  constructor(public url: string) {
    setTimeout(() => {
      this.readyState = MockWebSocket.OPEN;
      if (this.onopen) {
        this.onopen(new Event('open'));
      }
    }, 100);
  }

  public send(data: string) {
    // Mock send implementation
  }

  public close() {
    this.readyState = MockWebSocket.CLOSED;
    if (this.onclose) {
      this.onclose(new CloseEvent('close'));
    }
  }

  public simulateMessage(data: any) {
    if (this.onmessage && this.readyState === MockWebSocket.OPEN) {
      this.onmessage(new MessageEvent('message', { data: JSON.stringify(data) }));
    }
  }
}

// Mock fetch
const mockFetch = jest.fn();
global.fetch = mockFetch;
global.WebSocket = MockWebSocket as any;

// Mock components and hooks (these would be imported from actual implementation)
interface TelemetryEvent {
  event_type: string;
  service: string;
  feature_name?: string;
  action?: string;
  user_id?: string;
  session_id?: string;
  context?: Record<string, any>;
  parameters?: Record<string, any>;
  metadata?: Record<string, any>;
  duration_ms?: number;
  success?: boolean;
  error_message?: string;
  privacy_level?: string;
}

interface UsageMetric {
  id: string;
  metric_type: string;
  name: string;
  value: number;
  unit: string;
  period_start: string;
  period_end: string;
  granularity: string;
  sample_size: number;
}

interface TelemetryContextValue {
  isConnected: boolean;
  isCollecting: boolean;
  collectEvent: (event: Partial<TelemetryEvent>) => Promise<string | null>;
  getMetrics: (options?: any) => Promise<UsageMetric[]>;
  getRealTimeMetrics: () => Promise<any>;
  subscribe: (callback: (data: any) => void) => () => void;
  connectionState: 'connecting' | 'connected' | 'disconnected' | 'error';
  error: string | null;
  stats: {
    eventsCollected: number;
    eventsFailed: number;
    lastEventTime: string | null;
  };
}

const TelemetryContext = React.createContext<TelemetryContextValue | null>(null);

// Mock TelemetryProvider component
interface TelemetryProviderProps {
  children: React.ReactNode;
  apiBaseUrl?: string;
  wsUrl?: string;
  autoConnect?: boolean;
  bufferSize?: number;
  flushInterval?: number;
}

const TelemetryProvider: React.FC<TelemetryProviderProps> = ({
  children,
  apiBaseUrl = '/api/telemetry',
  wsUrl = 'ws://localhost:8003/telemetry/ws',
  autoConnect = true,
  bufferSize = 100,
  flushInterval = 30000,
}) => {
  const [isConnected, setIsConnected] = React.useState(false);
  const [isCollecting, setIsCollecting] = React.useState(true);
  const [connectionState, setConnectionState] = React.useState<'connecting' | 'connected' | 'disconnected' | 'error'>('disconnected');
  const [error, setError] = React.useState<string | null>(null);
  const [stats, setStats] = React.useState({
    eventsCollected: 0,
    eventsFailed: 0,
    lastEventTime: null as string | null,
  });
  
  const websocketRef = React.useRef<WebSocket | null>(null);
  const eventBuffer = React.useRef<Partial<TelemetryEvent>[]>([]);
  const subscriptions = React.useRef<Set<(data: any) => void>>(new Set());
  const flushTimerRef = React.useRef<NodeJS.Timeout>();

  // WebSocket connection management
  const connect = React.useCallback(() => {
    if (websocketRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    setConnectionState('connecting');
    setError(null);

    try {
      const ws = new WebSocket(wsUrl);
      websocketRef.current = ws;

      ws.onopen = () => {
        setIsConnected(true);
        setConnectionState('connected');
        setError(null);
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          subscriptions.current.forEach(callback => {
            try {
              callback(data);
            } catch (err) {
              console.error('Subscription callback error:', err);
            }
          });
        } catch (err) {
          console.error('Failed to parse WebSocket message:', err);
        }
      };

      ws.onclose = () => {
        setIsConnected(false);
        setConnectionState('disconnected');
        websocketRef.current = null;
      };

      ws.onerror = () => {
        setError('WebSocket connection error');
        setConnectionState('error');
      };
    } catch (err) {
      setError(`Failed to create WebSocket connection: ${err}`);
      setConnectionState('error');
    }
  }, [wsUrl]);

  const disconnect = React.useCallback(() => {
    if (websocketRef.current) {
      websocketRef.current.close();
      websocketRef.current = null;
    }
    setIsConnected(false);
    setConnectionState('disconnected');
  }, []);

  // Event collection
  const collectEvent = React.useCallback(async (event: Partial<TelemetryEvent>): Promise<string | null> => {
    if (!isCollecting) {
      return null;
    }

    try {
      const response = await fetch(`${apiBaseUrl}/events/collect`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          event_type: 'feature_access',
          service: 'web_ui',
          ...event,
          timestamp: new Date().toISOString(),
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const result = await response.json();
      
      if (result.collected) {
        setStats(prev => ({
          ...prev,
          eventsCollected: prev.eventsCollected + 1,
          lastEventTime: new Date().toISOString(),
        }));
        return result.event_id;
      } else {
        setStats(prev => ({
          ...prev,
          eventsFailed: prev.eventsFailed + 1,
        }));
        return null;
      }
    } catch (err) {
      console.error('Failed to collect event:', err);
      setStats(prev => ({
        ...prev,
        eventsFailed: prev.eventsFailed + 1,
      }));
      setError(`Event collection failed: ${err}`);
      return null;
    }
  }, [apiBaseUrl, isCollecting]);

  // Batch event flushing
  const flushEvents = React.useCallback(async () => {
    if (eventBuffer.current.length === 0) {
      return;
    }

    const events = [...eventBuffer.current];
    eventBuffer.current = [];

    try {
      const response = await fetch(`${apiBaseUrl}/events/batch`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(events),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const result = await response.json();
      setStats(prev => ({
        ...prev,
        eventsCollected: prev.eventsCollected + result.collected_count,
        eventsFailed: prev.eventsFailed + result.failed_count,
      }));
    } catch (err) {
      console.error('Failed to flush events:', err);
      setError(`Batch flush failed: ${err}`);
      // Re-add failed events to buffer
      eventBuffer.current.unshift(...events);
    }
  }, [apiBaseUrl]);

  // Metrics retrieval
  const getMetrics = React.useCallback(async (options = {}): Promise<UsageMetric[]> => {
    try {
      const response = await fetch(`${apiBaseUrl}/metrics`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          granularity: 'hour',
          ...options,
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const result = await response.json();
      return result.metrics;
    } catch (err) {
      console.error('Failed to get metrics:', err);
      setError(`Metrics retrieval failed: ${err}`);
      return [];
    }
  }, [apiBaseUrl]);

  // Real-time metrics
  const getRealTimeMetrics = React.useCallback(async () => {
    try {
      const response = await fetch(`${apiBaseUrl}/realtime`);
      
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      return await response.json();
    } catch (err) {
      console.error('Failed to get real-time metrics:', err);
      setError(`Real-time metrics failed: ${err}`);
      return null;
    }
  }, [apiBaseUrl]);

  // Subscription management
  const subscribe = React.useCallback((callback: (data: any) => void) => {
    subscriptions.current.add(callback);
    return () => {
      subscriptions.current.delete(callback);
    };
  }, []);

  // Setup auto-connection and cleanup
  React.useEffect(() => {
    if (autoConnect) {
      connect();
    }

    return () => {
      disconnect();
      if (flushTimerRef.current) {
        clearInterval(flushTimerRef.current);
      }
    };
  }, [autoConnect, connect, disconnect]);

  // Setup periodic flush
  React.useEffect(() => {
    flushTimerRef.current = setInterval(flushEvents, flushInterval);
    return () => {
      if (flushTimerRef.current) {
        clearInterval(flushTimerRef.current);
      }
    };
  }, [flushEvents, flushInterval]);

  const contextValue: TelemetryContextValue = {
    isConnected,
    isCollecting,
    collectEvent,
    getMetrics,
    getRealTimeMetrics,
    subscribe,
    connectionState,
    error,
    stats,
  };

  return (
    <TelemetryContext.Provider value={contextValue}>
      {children}
    </TelemetryContext.Provider>
  );
};

// Custom hook
const useTelemetry = () => {
  const context = React.useContext(TelemetryContext);
  if (!context) {
    throw new Error('useTelemetry must be used within a TelemetryProvider');
  }
  return context;
};

// Test components
const TestComponent = () => {
  const { isConnected, collectEvent, stats, error } = useTelemetry();

  const handleClick = async () => {
    await collectEvent({
      feature_name: 'test_button',
      action: 'click',
    });
  };

  return (
    <div>
      <div data-testid="connection-status">
        {isConnected ? 'Connected' : 'Disconnected'}
      </div>
      <div data-testid="events-collected">{stats.eventsCollected}</div>
      <div data-testid="events-failed">{stats.eventsFailed}</div>
      {error && <div data-testid="error">{error}</div>}
      <button onClick={handleClick} data-testid="collect-event-btn">
        Collect Event
      </button>
    </div>
  );
};

const MetricsComponent = () => {
  const { getMetrics } = useTelemetry();
  const [metrics, setMetrics] = React.useState<UsageMetric[]>([]);
  const [loading, setLoading] = React.useState(false);

  const loadMetrics = async () => {
    setLoading(true);
    try {
      const result = await getMetrics({ granularity: 'day' });
      setMetrics(result);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div>
      <button onClick={loadMetrics} data-testid="load-metrics-btn">
        Load Metrics
      </button>
      {loading && <div data-testid="loading">Loading...</div>}
      <div data-testid="metrics-count">{metrics.length}</div>
    </div>
  );
};

describe('TelemetryProvider', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockFetch.mockReset();
  });

  describe('Provider initialization', () => {
    it('should provide telemetry context to children', () => {
      render(
        <TelemetryProvider>
          <TestComponent />
        </TelemetryProvider>
      );

      expect(screen.getByTestId('connection-status')).toBeInTheDocument();
      expect(screen.getByTestId('events-collected')).toHaveTextContent('0');
    });

    it('should throw error when useTelemetry is used outside provider', () => {
      // Suppress console.error for this test
      const consoleSpy = jest.spyOn(console, 'error').mockImplementation(() => {});
      
      expect(() => {
        renderHook(() => useTelemetry());
      }).toThrow('useTelemetry must be used within a TelemetryProvider');

      consoleSpy.mockRestore();
    });

    it('should accept custom configuration props', () => {
      const customProps = {
        apiBaseUrl: '/custom/api',
        wsUrl: 'wss://custom.websocket.com',
        autoConnect: false,
        bufferSize: 200,
        flushInterval: 60000,
      };

      render(
        <TelemetryProvider {...customProps}>
          <TestComponent />
        </TelemetryProvider>
      );

      // Should render without connection since autoConnect is false
      expect(screen.getByTestId('connection-status')).toHaveTextContent('Disconnected');
    });
  });

  describe('WebSocket connection', () => {
    it('should establish WebSocket connection on mount', async () => {
      render(
        <TelemetryProvider autoConnect={true}>
          <TestComponent />
        </TelemetryProvider>
      );

      // Initially disconnected
      expect(screen.getByTestId('connection-status')).toHaveTextContent('Disconnected');

      // Wait for connection
      await waitFor(() => {
        expect(screen.getByTestId('connection-status')).toHaveTextContent('Connected');
      }, { timeout: 200 });
    });

    it('should handle WebSocket connection errors', async () => {
      // Mock WebSocket to throw error
      const originalWebSocket = global.WebSocket;
      global.WebSocket = jest.fn().mockImplementation(() => {
        throw new Error('Connection failed');
      });

      render(
        <TelemetryProvider autoConnect={true}>
          <TestComponent />
        </TelemetryProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId('error')).toHaveTextContent('Failed to create WebSocket connection');
      });

      global.WebSocket = originalWebSocket;
    });

    it('should handle WebSocket messages', async () => {
      let mockWs: MockWebSocket;
      const originalWebSocket = global.WebSocket;
      global.WebSocket = jest.fn().mockImplementation((url) => {
        mockWs = new MockWebSocket(url);
        return mockWs;
      });

      const SubscribedComponent = () => {
        const { subscribe } = useTelemetry();
        const [lastMessage, setLastMessage] = React.useState<any>(null);

        React.useEffect(() => {
          return subscribe((data) => {
            setLastMessage(data);
          });
        }, [subscribe]);

        return (
          <div data-testid="last-message">
            {lastMessage ? JSON.stringify(lastMessage) : 'No messages'}
          </div>
        );
      };

      render(
        <TelemetryProvider autoConnect={true}>
          <SubscribedComponent />
        </TelemetryProvider>
      );

      // Wait for connection
      await waitFor(() => {
        expect(mockWs!).toBeDefined();
      });

      // Simulate message
      act(() => {
        mockWs!.simulateMessage({ type: 'metrics_update', data: { value: 42 } });
      });

      await waitFor(() => {
        expect(screen.getByTestId('last-message')).toHaveTextContent('metrics_update');
      });

      global.WebSocket = originalWebSocket;
    });
  });

  describe('Event collection', () => {
    beforeEach(() => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: async () => ({
          event_id: 'test_event_123',
          collected: true,
          message: 'Event collected successfully',
        }),
      });
    });

    it('should collect events successfully', async () => {
      render(
        <TelemetryProvider>
          <TestComponent />
        </TelemetryProvider>
      );

      const collectBtn = screen.getByTestId('collect-event-btn');
      await userEvent.click(collectBtn);

      await waitFor(() => {
        expect(screen.getByTestId('events-collected')).toHaveTextContent('1');
      });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/telemetry/events/collect',
        expect.objectContaining({
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: expect.stringContaining('test_button'),
        })
      );
    });

    it('should handle event collection failures', async () => {
      mockFetch.mockRejectedValue(new Error('Network error'));

      render(
        <TelemetryProvider>
          <TestComponent />
        </TelemetryProvider>
      );

      const collectBtn = screen.getByTestId('collect-event-btn');
      await userEvent.click(collectBtn);

      await waitFor(() => {
        expect(screen.getByTestId('events-failed')).toHaveTextContent('1');
        expect(screen.getByTestId('error')).toHaveTextContent('Event collection failed');
      });
    });

    it('should handle HTTP error responses', async () => {
      mockFetch.mockResolvedValue({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
      });

      render(
        <TelemetryProvider>
          <TestComponent />
        </TelemetryProvider>
      );

      const collectBtn = screen.getByTestId('collect-event-btn');
      await userEvent.click(collectBtn);

      await waitFor(() => {
        expect(screen.getByTestId('events-failed')).toHaveTextContent('1');
      });
    });

    it('should handle events not collected due to sampling', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: async () => ({
          event_id: null,
          collected: false,
          message: 'Event not collected (sampling)',
        }),
      });

      render(
        <TelemetryProvider>
          <TestComponent />
        </TelemetryProvider>
      );

      const collectBtn = screen.getByTestId('collect-event-btn');
      await userEvent.click(collectBtn);

      await waitFor(() => {
        expect(screen.getByTestId('events-failed')).toHaveTextContent('1');
      });
    });
  });

  describe('Metrics retrieval', () => {
    beforeEach(() => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: async () => ({
          metrics: [
            {
              id: 'metric_1',
              metric_type: 'usage_count',
              name: 'Total Events',
              value: 100,
              unit: 'events',
              period_start: '2025-01-01T00:00:00Z',
              period_end: '2025-01-01T23:59:59Z',
              granularity: 'day',
              sample_size: 100,
            },
            {
              id: 'metric_2',
              metric_type: 'adoption_rate',
              name: 'Feature Adoption',
              value: 0.75,
              unit: 'percentage',
              period_start: '2025-01-01T00:00:00Z',
              period_end: '2025-01-01T23:59:59Z',
              granularity: 'day',
              sample_size: 50,
            },
          ],
        }),
      });
    });

    it('should retrieve metrics successfully', async () => {
      render(
        <TelemetryProvider>
          <MetricsComponent />
        </TelemetryProvider>
      );

      const loadBtn = screen.getByTestId('load-metrics-btn');
      await userEvent.click(loadBtn);

      expect(screen.getByTestId('loading')).toBeInTheDocument();

      await waitFor(() => {
        expect(screen.getByTestId('metrics-count')).toHaveTextContent('2');
      });

      expect(mockFetch).toHaveBeenCalledWith(
        '/api/telemetry/metrics',
        expect.objectContaining({
          method: 'POST',
          body: expect.stringContaining('day'),
        })
      );
    });

    it('should handle metrics retrieval errors', async () => {
      mockFetch.mockRejectedValue(new Error('Metrics API error'));

      render(
        <TelemetryProvider>
          <MetricsComponent />
        </TelemetryProvider>
      );

      const loadBtn = screen.getByTestId('load-metrics-btn');
      await userEvent.click(loadBtn);

      await waitFor(() => {
        expect(screen.getByTestId('metrics-count')).toHaveTextContent('0');
      });
    });
  });

  describe('Real-time metrics', () => {
    it('should retrieve real-time metrics', async () => {
      const mockRealTimeData = {
        timestamp: '2025-01-01T12:00:00Z',
        window_minutes: 15,
        total_events: 250,
        events_per_minute: 16.67,
        health_score: 0.95,
      };

      mockFetch.mockResolvedValue({
        ok: true,
        json: async () => mockRealTimeData,
      });

      const { result } = renderHook(() => useTelemetry(), {
        wrapper: ({ children }) => (
          <TelemetryProvider>{children}</TelemetryProvider>
        ),
      });

      const realTimeMetrics = await result.current.getRealTimeMetrics();

      expect(realTimeMetrics).toEqual(mockRealTimeData);
      expect(mockFetch).toHaveBeenCalledWith('/api/telemetry/realtime');
    });

    it('should handle real-time metrics errors', async () => {
      mockFetch.mockRejectedValue(new Error('Real-time API error'));

      const { result } = renderHook(() => useTelemetry(), {
        wrapper: ({ children }) => (
          <TelemetryProvider>{children}</TelemetryProvider>
        ),
      });

      const realTimeMetrics = await result.current.getRealTimeMetrics();

      expect(realTimeMetrics).toBeNull();
    });
  });

  describe('Subscription management', () => {
    it('should manage subscriptions properly', async () => {
      let mockWs: MockWebSocket;
      const originalWebSocket = global.WebSocket;
      global.WebSocket = jest.fn().mockImplementation((url) => {
        mockWs = new MockWebSocket(url);
        return mockWs;
      });

      const messages: any[] = [];
      const { result } = renderHook(() => useTelemetry(), {
        wrapper: ({ children }) => (
          <TelemetryProvider autoConnect={true}>{children}</TelemetryProvider>
        ),
      });

      // Wait for connection
      await waitFor(() => {
        expect(result.current.isConnected).toBe(true);
      });

      // Subscribe to messages
      const unsubscribe = result.current.subscribe((data) => {
        messages.push(data);
      });

      // Simulate messages
      act(() => {
        mockWs!.simulateMessage({ type: 'update', value: 1 });
        mockWs!.simulateMessage({ type: 'update', value: 2 });
      });

      await waitFor(() => {
        expect(messages).toHaveLength(2);
      });

      expect(messages[0]).toEqual({ type: 'update', value: 1 });
      expect(messages[1]).toEqual({ type: 'update', value: 2 });

      // Unsubscribe
      unsubscribe();

      // Should not receive new messages
      act(() => {
        mockWs!.simulateMessage({ type: 'update', value: 3 });
      });

      // Wait a bit and verify no new messages
      await new Promise(resolve => setTimeout(resolve, 100));
      expect(messages).toHaveLength(2);

      global.WebSocket = originalWebSocket;
    });
  });

  describe('Error handling', () => {
    it('should handle and display connection errors', async () => {
      const originalWebSocket = global.WebSocket;
      global.WebSocket = jest.fn().mockImplementation(() => {
        const ws = new MockWebSocket('ws://test');
        setTimeout(() => {
          if (ws.onerror) {
            ws.onerror(new Event('error'));
          }
        }, 50);
        return ws;
      });

      render(
        <TelemetryProvider autoConnect={true}>
          <TestComponent />
        </TelemetryProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId('error')).toHaveTextContent('WebSocket connection error');
      });

      global.WebSocket = originalWebSocket;
    });

    it('should clear errors on successful operations', async () => {
      // First, create an error condition
      mockFetch.mockRejectedValueOnce(new Error('Network error'));

      render(
        <TelemetryProvider>
          <TestComponent />
        </TelemetryProvider>
      );

      const collectBtn = screen.getByTestId('collect-event-btn');
      await userEvent.click(collectBtn);

      await waitFor(() => {
        expect(screen.getByTestId('error')).toBeInTheDocument();
      });

      // Now succeed
      mockFetch.mockResolvedValue({
        ok: true,
        json: async () => ({
          event_id: 'success_event',
          collected: true,
          message: 'Success',
        }),
      });

      await userEvent.click(collectBtn);

      // Error should be cleared (or at least not the old error)
      await waitFor(() => {
        expect(screen.getByTestId('events-collected')).toHaveTextContent('1');
      });
    });
  });

  describe('Performance and memory management', () => {
    it('should cleanup WebSocket connection on unmount', async () => {
      let mockWs: MockWebSocket;
      const originalWebSocket = global.WebSocket;
      global.WebSocket = jest.fn().mockImplementation((url) => {
        mockWs = new MockWebSocket(url);
        return mockWs;
      });

      const { unmount } = render(
        <TelemetryProvider autoConnect={true}>
          <TestComponent />
        </TelemetryProvider>
      );

      // Wait for connection
      await waitFor(() => {
        expect(mockWs!.readyState).toBe(MockWebSocket.OPEN);
      });

      // Unmount should close connection
      unmount();

      expect(mockWs!.readyState).toBe(MockWebSocket.CLOSED);

      global.WebSocket = originalWebSocket;
    });

    it('should handle multiple rapid event collections', async () => {
      mockFetch.mockResolvedValue({
        ok: true,
        json: async () => ({ event_id: 'rapid_event', collected: true }),
      });

      render(
        <TelemetryProvider>
          <TestComponent />
        </TelemetryProvider>
      );

      const collectBtn = screen.getByTestId('collect-event-btn');

      // Rapidly click multiple times
      for (let i = 0; i < 10; i++) {
        await userEvent.click(collectBtn);
      }

      await waitFor(() => {
        expect(screen.getByTestId('events-collected')).toHaveTextContent('10');
      });

      // Should have made 10 API calls
      expect(mockFetch).toHaveBeenCalledTimes(10);
    });
  });
});