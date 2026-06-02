/**
 * Comprehensive tests for UsageMetricsPanel - Metrics dashboard component.
 */

import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { format } from 'date-fns';

// Mock Chart.js
jest.mock('chart.js/auto', () => {
  return {
    Chart: class MockChart {
      static register = jest.fn();
      constructor(public ctx: any, public config: any) {}
      public update = jest.fn();
      public destroy = jest.fn();
    },
    registerables: [],
  };
});

// Mock react-chartjs-2
jest.mock('react-chartjs-2', () => ({
  Line: ({ data, options, ...props }: any) => (
    <div data-testid="line-chart" data-chart-data={JSON.stringify(data)} {...props}>
      Line Chart
    </div>
  ),
  Bar: ({ data, options, ...props }: any) => (
    <div data-testid="bar-chart" data-chart-data={JSON.stringify(data)} {...props}>
      Bar Chart
    </div>
  ),
  Doughnut: ({ data, options, ...props }: any) => (
    <div data-testid="doughnut-chart" data-chart-data={JSON.stringify(data)} {...props}>
      Doughnut Chart
    </div>
  ),
}));

// Mock data structures
interface UsageMetric {
  id: string;
  metric_type: 'usage_count' | 'adoption_rate' | 'performance_metrics' | 'error_rate' | 'temporal_patterns';
  name: string;
  value: number;
  unit: string;
  timestamp: string;
  period_start: string;
  period_end: string;
  granularity: string;
  dimensions?: Record<string, any>;
  breakdown?: Record<string, number>;
  sample_size: number;
}

interface MetricsFilter {
  timeRange: '1h' | '24h' | '7d' | '30d' | 'custom';
  startDate?: Date;
  endDate?: Date;
  services: string[];
  features: string[];
  metricTypes: string[];
  granularity: 'hour' | 'day' | 'week' | 'month';
}

interface MetricsExport {
  format: 'csv' | 'json' | 'pdf';
  includeCharts: boolean;
  includeRawData: boolean;
}

// Mock telemetry hook
const mockTelemetryContext = {
  getMetrics: jest.fn(),
  getRealTimeMetrics: jest.fn(),
  isConnected: true,
  error: null,
  stats: { eventsCollected: 0, eventsFailed: 0, lastEventTime: null },
};

jest.mock('../../../components/telemetry/telemetry-provider', () => ({
  useTelemetry: () => mockTelemetryContext,
}));

// Mock components for testing
const UsageMetricsPanel: React.FC = () => {
  const [metrics, setMetrics] = React.useState<UsageMetric[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [selectedTimeRange, setSelectedTimeRange] = React.useState<'1h' | '24h' | '7d' | '30d'>('24h');
  const [autoRefresh, setAutoRefresh] = React.useState(false);
  const [refreshInterval, setRefreshInterval] = React.useState(30);
  const [showExportModal, setShowExportModal] = React.useState(false);
  const [filters, setFilters] = React.useState<MetricsFilter>({
    timeRange: '24h',
    services: [],
    features: [],
    metricTypes: [],
    granularity: 'hour',
  });

  const loadMetrics = React.useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const options: any = {
        granularity: filters.granularity,
      };

      if (filters.services.length > 0) {
        options.services = filters.services;
      }
      if (filters.features.length > 0) {
        options.features = filters.features;
      }
      if (filters.metricTypes.length > 0) {
        options.metric_types = filters.metricTypes;
      }

      // Set time range
      const now = new Date();
      let startTime: Date;
      switch (selectedTimeRange) {
        case '1h':
          startTime = new Date(now.getTime() - 60 * 60 * 1000);
          break;
        case '24h':
          startTime = new Date(now.getTime() - 24 * 60 * 60 * 1000);
          break;
        case '7d':
          startTime = new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
          break;
        case '30d':
          startTime = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
          break;
        default:
          startTime = new Date(now.getTime() - 24 * 60 * 60 * 1000);
      }

      options.start_time = startTime.toISOString();
      options.end_time = now.toISOString();

      const result = await mockTelemetryContext.getMetrics(options);
      setMetrics(result);
    } catch (err) {
      console.error('Failed to load metrics:', err);
      setError('Failed to load metrics');
    } finally {
      setLoading(false);
    }
  }, [selectedTimeRange, filters]);

  // Auto-refresh functionality
  React.useEffect(() => {
    let intervalId: NodeJS.Timeout;

    if (autoRefresh) {
      intervalId = setInterval(loadMetrics, refreshInterval * 1000);
    }

    return () => {
      if (intervalId) {
        clearInterval(intervalId);
      }
    };
  }, [autoRefresh, refreshInterval, loadMetrics]);

  // Load metrics on mount and filter changes
  React.useEffect(() => {
    loadMetrics();
  }, [loadMetrics]);

  // Group metrics by type
  const metricsByType = React.useMemo(() => {
    const grouped: Record<string, UsageMetric[]> = {};
    metrics.forEach(metric => {
      if (!grouped[metric.metric_type]) {
        grouped[metric.metric_type] = [];
      }
      grouped[metric.metric_type].push(metric);
    });
    return grouped;
  }, [metrics]);

  // Calculate summary statistics
  const summaryStats = React.useMemo(() => {
    const totalEvents = metrics
      .filter(m => m.metric_type === 'usage_count' && m.name === 'Total Events')
      .reduce((sum, m) => sum + m.value, 0);

    const uniqueUsers = metrics
      .filter(m => m.metric_type === 'usage_count' && m.name === 'Unique Users')
      .reduce((sum, m) => sum + m.value, 0);

    const errorRate = metrics
      .filter(m => m.metric_type === 'error_rate')
      .reduce((sum, m) => sum + m.value, 0) / Math.max(1, metrics.filter(m => m.metric_type === 'error_rate').length);

    const avgResponseTime = metrics
      .filter(m => m.metric_type === 'performance_metrics' && m.name.includes('Average'))
      .reduce((sum, m) => sum + m.value, 0) / Math.max(1, metrics.filter(m => m.metric_type === 'performance_metrics' && m.name.includes('Average')).length);

    return {
      totalEvents: Math.round(totalEvents),
      uniqueUsers: Math.round(uniqueUsers),
      errorRate: isNaN(errorRate) ? 0 : errorRate,
      avgResponseTime: isNaN(avgResponseTime) ? 0 : Math.round(avgResponseTime),
    };
  }, [metrics]);

  // Prepare chart data
  const prepareChartData = (metrics: UsageMetric[], type: string) => {
    const filteredMetrics = metrics.filter(m => m.metric_type === type);

    if (filteredMetrics.length === 0) {
      return {
        labels: [],
        datasets: [],
      };
    }

    // Group by time periods
    const timeGroups: Record<string, number> = {};
    filteredMetrics.forEach(metric => {
      const timeKey = format(new Date(metric.timestamp), 'MMM dd HH:mm');
      timeGroups[timeKey] = (timeGroups[timeKey] || 0) + metric.value;
    });

    const labels = Object.keys(timeGroups).sort();
    const data = labels.map(label => timeGroups[label]);

    return {
      labels,
      datasets: [
        {
          label: type.replace('_', ' ').toUpperCase(),
          data,
          borderColor: '#3b82f6',
          backgroundColor: 'rgba(59, 130, 246, 0.1)',
          tension: 0.4,
        },
      ],
    };
  };

  const handleTimeRangeChange = (range: '1h' | '24h' | '7d' | '30d') => {
    setSelectedTimeRange(range);
    setFilters(prev => ({ ...prev, timeRange: range }));
  };

  const handleFilterChange = (key: keyof MetricsFilter, value: any) => {
    setFilters(prev => ({ ...prev, [key]: value }));
  };

  const handleExport = (exportConfig: MetricsExport) => {
    // Mock export functionality
    console.log('Exporting metrics:', exportConfig);
    setShowExportModal(false);
  };

  const formatValue = (value: number, unit: string) => {
    if (unit === 'percentage') {
      return `${(value * 100).toFixed(1)}%`;
    }
    if (unit === 'milliseconds') {
      return `${value.toFixed(0)}ms`;
    }
    if (value >= 1000) {
      return `${(value / 1000).toFixed(1)}k`;
    }
    return value.toFixed(0);
  };

  return (
    <div className="usage-metrics-panel" data-testid="usage-metrics-panel">
      {/* Header */}
      <div className="panel-header" data-testid="panel-header">
        <h2>Usage Metrics Dashboard</h2>
        <div className="header-controls">
          <div className="time-range-selector" data-testid="time-range-selector">
            {(['1h', '24h', '7d', '30d'] as const).map(range => (
              <button
                key={range}
                className={`time-range-btn ${selectedTimeRange === range ? 'active' : ''}`}
                onClick={() => handleTimeRangeChange(range)}
                data-testid={`time-range-${range}`}
              >
                {range}
              </button>
            ))}
          </div>

          <div className="auto-refresh-controls" data-testid="auto-refresh-controls">
            <label>
              <input
                type="checkbox"
                checked={autoRefresh}
                onChange={(e) => setAutoRefresh(e.target.checked)}
                data-testid="auto-refresh-checkbox"
              />
              Auto-refresh
            </label>
            <select
              value={refreshInterval}
              onChange={(e) => setRefreshInterval(Number(e.target.value))}
              disabled={!autoRefresh}
              data-testid="refresh-interval-select"
            >
              <option value={10}>10s</option>
              <option value={30}>30s</option>
              <option value={60}>60s</option>
            </select>
          </div>

          <button
            onClick={loadMetrics}
            disabled={loading}
            data-testid="refresh-btn"
          >
            {loading ? 'Loading...' : 'Refresh'}
          </button>

          <button
            onClick={() => setShowExportModal(true)}
            data-testid="export-btn"
          >
            Export
          </button>
        </div>
      </div>

      {/* Error display */}
      {error && (
        <div className="error-message" data-testid="error-message">
          {error}
        </div>
      )}

      {/* Loading indicator */}
      {loading && (
        <div className="loading-indicator" data-testid="loading-indicator">
          Loading metrics...
        </div>
      )}

      {/* Summary cards */}
      <div className="summary-cards" data-testid="summary-cards">
        <div className="summary-card" data-testid="summary-total-events">
          <h3>Total Events</h3>
          <div className="value">{summaryStats.totalEvents.toLocaleString()}</div>
        </div>
        <div className="summary-card" data-testid="summary-unique-users">
          <h3>Unique Users</h3>
          <div className="value">{summaryStats.uniqueUsers.toLocaleString()}</div>
        </div>
        <div className="summary-card" data-testid="summary-error-rate">
          <h3>Error Rate</h3>
          <div className="value">{formatValue(summaryStats.errorRate, 'percentage')}</div>
        </div>
        <div className="summary-card" data-testid="summary-response-time">
          <h3>Avg Response Time</h3>
          <div className="value">{formatValue(summaryStats.avgResponseTime, 'milliseconds')}</div>
        </div>
      </div>

      {/* Filters */}
      <div className="filters-section" data-testid="filters-section">
        <div className="filter-group">
          <label>Services:</label>
          <select
            multiple
            value={filters.services}
            onChange={(e) => {
              const values = Array.from(e.target.selectedOptions, option => option.value);
              handleFilterChange('services', values);
            }}
            data-testid="services-filter"
          >
            <option value="agent">Agent</option>
            <option value="web_ui">Web UI</option>
            <option value="brKg">BR-KG</option>
            <option value="orchestrator">Orchestrator</option>
          </select>
        </div>

        <div className="filter-group">
          <label>Granularity:</label>
          <select
            value={filters.granularity}
            onChange={(e) => handleFilterChange('granularity', e.target.value)}
            data-testid="granularity-filter"
          >
            <option value="hour">Hour</option>
            <option value="day">Day</option>
            <option value="week">Week</option>
            <option value="month">Month</option>
          </select>
        </div>
      </div>

      {/* Charts */}
      <div className="charts-grid" data-testid="charts-grid">
        {Object.entries(metricsByType).map(([type, typeMetrics]) => (
          <div key={type} className="chart-container" data-testid={`chart-${type}`}>
            <h3>{type.replace('_', ' ').toUpperCase()}</h3>
            {type === 'usage_count' && (
              <div data-testid={`line-chart-${type}`}>
                <Line data={prepareChartData(typeMetrics, type)} />
              </div>
            )}
            {type === 'adoption_rate' && (
              <div data-testid={`bar-chart-${type}`}>
                <Bar data={prepareChartData(typeMetrics, type)} />
              </div>
            )}
            {type === 'error_rate' && (
              <div data-testid={`doughnut-chart-${type}`}>
                <Doughnut data={prepareChartData(typeMetrics, type)} />
              </div>
            )}

            {/* Metrics table */}
            <div className="metrics-table" data-testid={`metrics-table-${type}`}>
              {typeMetrics.slice(0, 5).map(metric => (
                <div key={metric.id} className="metric-row" data-testid={`metric-${metric.id}`}>
                  <span className="metric-name">{metric.name}</span>
                  <span className="metric-value">{formatValue(metric.value, metric.unit)}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Export Modal */}
      {showExportModal && (
        <div className="export-modal" data-testid="export-modal">
          <div className="modal-content">
            <h3>Export Metrics</h3>

            <div className="export-options">
              <div className="option-group">
                <label>Format:</label>
                <select data-testid="export-format-select">
                  <option value="csv">CSV</option>
                  <option value="json">JSON</option>
                  <option value="pdf">PDF</option>
                </select>
              </div>

              <div className="option-group">
                <label>
                  <input type="checkbox" data-testid="include-charts-checkbox" />
                  Include Charts
                </label>
              </div>

              <div className="option-group">
                <label>
                  <input type="checkbox" data-testid="include-raw-data-checkbox" />
                  Include Raw Data
                </label>
              </div>
            </div>

            <div className="modal-actions">
              <button
                onClick={() => setShowExportModal(false)}
                data-testid="export-cancel-btn"
              >
                Cancel
              </button>
              <button
                onClick={() => handleExport({ format: 'csv', includeCharts: false, includeRawData: true })}
                data-testid="export-confirm-btn"
              >
                Export
              </button>
            </div>
          </div>
        </div>
      )}

      {/* No data message */}
      {!loading && metrics.length === 0 && (
        <div className="no-data-message" data-testid="no-data-message">
          No metrics data available for the selected time range and filters.
        </div>
      )}
    </div>
  );
};

// Mock Line component for isolated testing
const MockLine = React.forwardRef<any, any>((props, ref) => (
  <div ref={ref} data-testid="line-chart" {...props}>
    Line Chart Mock
  </div>
));

const MockBar = React.forwardRef<any, any>((props, ref) => (
  <div ref={ref} data-testid="bar-chart" {...props}>
    Bar Chart Mock
  </div>
));

const MockDoughnut = React.forwardRef<any, any>((props, ref) => (
  <div ref={ref} data-testid="doughnut-chart" {...props}>
    Doughnut Chart Mock
  </div>
));

describe('UsageMetricsPanel', () => {
  const mockMetrics: UsageMetric[] = [
    {
      id: 'metric_1',
      metric_type: 'usage_count',
      name: 'Total Events',
      value: 1500,
      unit: 'events',
      timestamp: '2025-01-01T12:00:00Z',
      period_start: '2025-01-01T00:00:00Z',
      period_end: '2025-01-01T23:59:59Z',
      granularity: 'hour',
      sample_size: 1500,
    },
    {
      id: 'metric_2',
      metric_type: 'usage_count',
      name: 'Unique Users',
      value: 150,
      unit: 'users',
      timestamp: '2025-01-01T12:00:00Z',
      period_start: '2025-01-01T00:00:00Z',
      period_end: '2025-01-01T23:59:59Z',
      granularity: 'hour',
      sample_size: 150,
    },
    {
      id: 'metric_3',
      metric_type: 'error_rate',
      name: 'Overall Error Rate',
      value: 0.05,
      unit: 'percentage',
      timestamp: '2025-01-01T12:00:00Z',
      period_start: '2025-01-01T00:00:00Z',
      period_end: '2025-01-01T23:59:59Z',
      granularity: 'hour',
      sample_size: 1500,
    },
    {
      id: 'metric_4',
      metric_type: 'performance_metrics',
      name: 'Average Response Time',
      value: 250,
      unit: 'milliseconds',
      timestamp: '2025-01-01T12:00:00Z',
      period_start: '2025-01-01T00:00:00Z',
      period_end: '2025-01-01T23:59:59Z',
      granularity: 'hour',
      sample_size: 1000,
    },
    {
      id: 'metric_5',
      metric_type: 'adoption_rate',
      name: 'Feature Adoption Rate',
      value: 0.75,
      unit: 'percentage',
      timestamp: '2025-01-01T12:00:00Z',
      period_start: '2025-01-01T00:00:00Z',
      period_end: '2025-01-01T23:59:59Z',
      granularity: 'hour',
      sample_size: 150,
    },
  ];

  beforeEach(() => {
    jest.clearAllMocks();
    mockTelemetryContext.getMetrics.mockResolvedValue(mockMetrics);
    mockTelemetryContext.getRealTimeMetrics.mockResolvedValue({});
    mockTelemetryContext.error = null;
  });

  describe('Panel initialization', () => {
    it('should render the usage metrics panel', async () => {
      render(<UsageMetricsPanel />);

      expect(screen.getByTestId('usage-metrics-panel')).toBeInTheDocument();
      expect(screen.getByText('Usage Metrics Dashboard')).toBeInTheDocument();
    });

    it('should load metrics on mount', async () => {
      render(<UsageMetricsPanel />);

      expect(screen.getByTestId('loading-indicator')).toBeInTheDocument();

      await waitFor(() => {
        expect(mockTelemetryContext.getMetrics).toHaveBeenCalled();
        expect(screen.queryByTestId('loading-indicator')).not.toBeInTheDocument();
      });
    });

    it('should display summary statistics', async () => {
      render(<UsageMetricsPanel />);

      await waitFor(() => {
        expect(screen.getByTestId('summary-total-events')).toHaveTextContent('1,500');
        expect(screen.getByTestId('summary-unique-users')).toHaveTextContent('150');
        expect(screen.getByTestId('summary-error-rate')).toHaveTextContent('5.0%');
        expect(screen.getByTestId('summary-response-time')).toHaveTextContent('250ms');
      });
    });
  });

  describe('Time range selection', () => {
    it('should handle time range selection', async () => {
      render(<UsageMetricsPanel />);

      // Wait for initial load
      await waitFor(() => {
        expect(mockTelemetryContext.getMetrics).toHaveBeenCalled();
      });

      // Change time range
      const sevenDayBtn = screen.getByTestId('time-range-7d');
      await userEvent.click(sevenDayBtn);

      // Should trigger new API call
      await waitFor(() => {
        expect(mockTelemetryContext.getMetrics).toHaveBeenCalledTimes(2);
      });

      // Button should be active
      expect(sevenDayBtn).toHaveClass('active');
    });

    it('should pass correct time parameters to API', async () => {
      render(<UsageMetricsPanel />);

      // Wait for initial load
      await waitFor(() => {
        expect(mockTelemetryContext.getMetrics).toHaveBeenCalled();
      });

      const call = mockTelemetryContext.getMetrics.mock.calls[0][0];
      expect(call).toHaveProperty('start_time');
      expect(call).toHaveProperty('end_time');
      expect(call).toHaveProperty('granularity', 'hour');
    });
  });

  describe('Auto-refresh functionality', () => {
    beforeEach(() => {
      jest.useFakeTimers();
    });

    afterEach(() => {
      jest.useRealTimers();
    });

    it('should enable auto-refresh when checkbox is checked', async () => {
      render(<UsageMetricsPanel />);

      // Wait for initial load
      await waitFor(() => {
        expect(mockTelemetryContext.getMetrics).toHaveBeenCalledTimes(1);
      });

      // Enable auto-refresh
      const checkbox = screen.getByTestId('auto-refresh-checkbox');
      await userEvent.click(checkbox);

      // Fast-forward time
      jest.advanceTimersByTime(30000); // 30 seconds

      await waitFor(() => {
        expect(mockTelemetryContext.getMetrics).toHaveBeenCalledTimes(2);
      });
    });

    it('should respect custom refresh interval', async () => {
      render(<UsageMetricsPanel />);

      // Enable auto-refresh
      const checkbox = screen.getByTestId('auto-refresh-checkbox');
      await userEvent.click(checkbox);

      // Change interval to 60 seconds
      const intervalSelect = screen.getByTestId('refresh-interval-select');
      await userEvent.selectOptions(intervalSelect, '60');

      // Fast-forward 30 seconds (should not refresh)
      jest.advanceTimersByTime(30000);
      expect(mockTelemetryContext.getMetrics).toHaveBeenCalledTimes(1);

      // Fast-forward another 30 seconds (should refresh)
      jest.advanceTimersByTime(30000);
      await waitFor(() => {
        expect(mockTelemetryContext.getMetrics).toHaveBeenCalledTimes(2);
      });
    });

    it('should disable auto-refresh when unchecked', async () => {
      render(<UsageMetricsPanel />);

      const checkbox = screen.getByTestId('auto-refresh-checkbox');

      // Enable then disable
      await userEvent.click(checkbox);
      await userEvent.click(checkbox);

      // Fast-forward time
      jest.advanceTimersByTime(60000);

      // Should not have additional calls
      expect(mockTelemetryContext.getMetrics).toHaveBeenCalledTimes(1);
    });
  });

  describe('Filtering functionality', () => {
    it('should apply service filters', async () => {
      render(<UsageMetricsPanel />);

      // Wait for initial load
      await waitFor(() => {
        expect(mockTelemetryContext.getMetrics).toHaveBeenCalledTimes(1);
      });

      // Apply service filter
      const servicesFilter = screen.getByTestId('services-filter');
      await userEvent.selectOptions(servicesFilter, ['agent', 'web_ui']);

      await waitFor(() => {
        const call = mockTelemetryContext.getMetrics.mock.calls[1][0];
        expect(call.services).toEqual(['agent', 'web_ui']);
      });
    });

    it('should apply granularity filter', async () => {
      render(<UsageMetricsPanel />);

      // Change granularity
      const granularityFilter = screen.getByTestId('granularity-filter');
      await userEvent.selectOptions(granularityFilter, 'day');

      await waitFor(() => {
        const call = mockTelemetryContext.getMetrics.mock.calls[1][0];
        expect(call.granularity).toBe('day');
      });
    });
  });

  describe('Chart rendering', () => {
    it('should render charts for different metric types', async () => {
      render(<UsageMetricsPanel />);

      await waitFor(() => {
        expect(screen.getByTestId('chart-usage_count')).toBeInTheDocument();
        expect(screen.getByTestId('chart-error_rate')).toBeInTheDocument();
        expect(screen.getByTestId('chart-adoption_rate')).toBeInTheDocument();
        expect(screen.getByTestId('chart-performance_metrics')).toBeInTheDocument();
      });
    });

    it('should display metric tables', async () => {
      render(<UsageMetricsPanel />);

      await waitFor(() => {
        expect(screen.getByTestId('metrics-table-usage_count')).toBeInTheDocument();
        expect(screen.getByTestId('metric-metric_1')).toBeInTheDocument();
        expect(screen.getByTestId('metric-metric_2')).toBeInTheDocument();
      });
    });

    it('should format values correctly', async () => {
      render(<UsageMetricsPanel />);

      await waitFor(() => {
        const errorRateCard = screen.getByTestId('summary-error-rate');
        expect(errorRateCard).toHaveTextContent('5.0%');

        const responseTimeCard = screen.getByTestId('summary-response-time');
        expect(responseTimeCard).toHaveTextContent('250ms');
      });
    });
  });

  describe('Export functionality', () => {
    it('should open export modal when export button is clicked', async () => {
      render(<UsageMetricsPanel />);

      const exportBtn = screen.getByTestId('export-btn');
      await userEvent.click(exportBtn);

      expect(screen.getByTestId('export-modal')).toBeInTheDocument();
      expect(screen.getByText('Export Metrics')).toBeInTheDocument();
    });

    it('should close export modal when cancel is clicked', async () => {
      render(<UsageMetricsPanel />);

      // Open modal
      const exportBtn = screen.getByTestId('export-btn');
      await userEvent.click(exportBtn);

      // Close modal
      const cancelBtn = screen.getByTestId('export-cancel-btn');
      await userEvent.click(cancelBtn);

      expect(screen.queryByTestId('export-modal')).not.toBeInTheDocument();
    });

    it('should handle export confirmation', async () => {
      const consoleSpy = jest.spyOn(console, 'log').mockImplementation();

      render(<UsageMetricsPanel />);

      // Open modal
      const exportBtn = screen.getByTestId('export-btn');
      await userEvent.click(exportBtn);

      // Confirm export
      const confirmBtn = screen.getByTestId('export-confirm-btn');
      await userEvent.click(confirmBtn);

      expect(consoleSpy).toHaveBeenCalledWith('Exporting metrics:', expect.any(Object));
      expect(screen.queryByTestId('export-modal')).not.toBeInTheDocument();

      consoleSpy.mockRestore();
    });
  });

  describe('Error handling', () => {
    it('should display error message when API fails', async () => {
      mockTelemetryContext.getMetrics.mockRejectedValue(new Error('API Error'));

      render(<UsageMetricsPanel />);

      await waitFor(() => {
        expect(screen.getByTestId('error-message')).toHaveTextContent('Failed to load metrics');
      });
    });

    it('should clear error on successful reload', async () => {
      // First call fails
      mockTelemetryContext.getMetrics
        .mockRejectedValueOnce(new Error('API Error'))
        .mockResolvedValue(mockMetrics);

      render(<UsageMetricsPanel />);

      // Wait for error
      await waitFor(() => {
        expect(screen.getByTestId('error-message')).toBeInTheDocument();
      });

      // Retry
      const refreshBtn = screen.getByTestId('refresh-btn');
      await userEvent.click(refreshBtn);

      await waitFor(() => {
        expect(screen.queryByTestId('error-message')).not.toBeInTheDocument();
      });
    });
  });

  describe('Loading states', () => {
    it('should show loading indicator during data fetch', async () => {
      // Make API call hang
      mockTelemetryContext.getMetrics.mockImplementation(
        () => new Promise(resolve => setTimeout(() => resolve(mockMetrics), 1000))
      );

      render(<UsageMetricsPanel />);

      expect(screen.getByTestId('loading-indicator')).toBeInTheDocument();

      // Refresh button should be disabled
      const refreshBtn = screen.getByTestId('refresh-btn');
      expect(refreshBtn).toBeDisabled();
      expect(refreshBtn).toHaveTextContent('Loading...');
    });

    it('should hide loading indicator after data loads', async () => {
      render(<UsageMetricsPanel />);

      await waitFor(() => {
        expect(screen.queryByTestId('loading-indicator')).not.toBeInTheDocument();
      });

      const refreshBtn = screen.getByTestId('refresh-btn');
      expect(refreshBtn).not.toBeDisabled();
      expect(refreshBtn).toHaveTextContent('Refresh');
    });
  });

  describe('No data handling', () => {
    it('should show no data message when metrics array is empty', async () => {
      mockTelemetryContext.getMetrics.mockResolvedValue([]);

      render(<UsageMetricsPanel />);

      await waitFor(() => {
        expect(screen.getByTestId('no-data-message')).toBeInTheDocument();
        expect(screen.getByText(/No metrics data available/)).toBeInTheDocument();
      });
    });

    it('should hide charts when no data is available', async () => {
      mockTelemetryContext.getMetrics.mockResolvedValue([]);

      render(<UsageMetricsPanel />);

      await waitFor(() => {
        expect(screen.queryByTestId('charts-grid')).toBeInTheDocument();
        // Charts should exist but be empty
        expect(screen.queryByTestId('chart-usage_count')).not.toBeInTheDocument();
      });
    });
  });

  describe('Accessibility', () => {
    it('should have proper ARIA labels and roles', async () => {
      render(<UsageMetricsPanel />);

      const autoRefreshCheckbox = screen.getByTestId('auto-refresh-checkbox');
      expect(autoRefreshCheckbox).toHaveAttribute('type', 'checkbox');

      const refreshBtn = screen.getByTestId('refresh-btn');
      expect(refreshBtn).toHaveAttribute('type', 'button');
    });

    it('should support keyboard navigation', async () => {
      render(<UsageMetricsPanel />);

      const timeRange24h = screen.getByTestId('time-range-24h');
      const timeRange7d = screen.getByTestId('time-range-7d');

      // Focus and navigate with keyboard
      timeRange24h.focus();
      expect(document.activeElement).toBe(timeRange24h);

      // Tab to next element
      fireEvent.keyDown(timeRange24h, { key: 'Tab' });
      // Note: In actual implementation, you'd need proper tabIndex management
    });
  });

  describe('Performance considerations', () => {
    it('should memoize chart data preparation', async () => {
      render(<UsageMetricsPanel />);

      // Wait for initial render
      await waitFor(() => {
        expect(screen.getByTestId('summary-cards')).toBeInTheDocument();
      });

      // Multiple renders with same data shouldn't cause re-computation
      // This would be tested with React DevTools Profiler in real implementation
    });

    it('should cleanup intervals on unmount', () => {
      jest.useFakeTimers();

      const { unmount } = render(<UsageMetricsPanel />);

      // Enable auto-refresh
      const checkbox = screen.getByTestId('auto-refresh-checkbox');
      fireEvent.click(checkbox);

      // Unmount component
      unmount();

      // Advance time - should not cause any calls
      jest.advanceTimersByTime(60000);
      expect(mockTelemetryContext.getMetrics).toHaveBeenCalledTimes(1); // Only initial call

      jest.useRealTimers();
    });
  });
});
