/**
 * Test Setup for Analytics Dashboard Components
 * 
 * Global configuration and utilities for analytics testing
 */

import '@testing-library/jest-dom'

// Global WebSocket mock
;(global as any).WebSocket = class MockWebSocket {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSING = 2
  static CLOSED = 3

  readyState = MockWebSocket.CONNECTING
  url: string
  protocol?: string
  
  onopen: ((event: Event) => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  
  constructor(url: string, protocol?: string) {
    this.url = url
    this.protocol = protocol
    
    // Simulate connection opening
    setTimeout(() => {
      this.readyState = MockWebSocket.OPEN
      this.onopen?.(new Event('open'))
    }, 10)
  }
  
  send(data: string | ArrayBuffer | Blob) {
    if (this.readyState !== MockWebSocket.OPEN) {
      throw new Error('WebSocket is not open')
    }
  }
  
  close(code?: number, reason?: string) {
    this.readyState = MockWebSocket.CLOSING
    setTimeout(() => {
      this.readyState = MockWebSocket.CLOSED
      this.onclose?.(new CloseEvent('close', { code, reason }))
    }, 10)
  }
  
  addEventListener(type: string, listener: EventListener) {
    if (type === 'open') this.onopen = listener as any
    if (type === 'close') this.onclose = listener as any
    if (type === 'message') this.onmessage = listener as any
    if (type === 'error') this.onerror = listener as any
  }
  
  removeEventListener(type: string, listener: EventListener) {
    if (type === 'open') this.onopen = null
    if (type === 'close') this.onclose = null
    if (type === 'message') this.onmessage = null
    if (type === 'error') this.onerror = null
  }
}

// Mock ResizeObserver for responsive charts
;(global as any).ResizeObserver = class MockResizeObserver {
  constructor(callback: ResizeObserverCallback) {
    this.callback = callback
  }
  
  callback: ResizeObserverCallback
  
  observe() {
    // Simulate initial observation
    setTimeout(() => {
      this.callback([{
        target: document.createElement('div'),
        contentRect: new DOMRect(0, 0, 800, 600),
        borderBoxSize: [] as any,
        contentBoxSize: [] as any,
        devicePixelContentBoxSize: [] as any
      }], this)
    }, 10)
  }
  
  unobserve() {}
  disconnect() {}
}

// Mock IntersectionObserver for visibility detection
;(global as any).IntersectionObserver = class MockIntersectionObserver {
  constructor(callback: IntersectionObserverCallback) {
    this.callback = callback
  }
  
  callback: IntersectionObserverCallback
  
  observe() {
    // Simulate element being visible
    setTimeout(() => {
      this.callback([{
        target: document.createElement('div'),
        isIntersecting: true,
        intersectionRatio: 1,
        boundingClientRect: new DOMRect(0, 0, 800, 600),
        intersectionRect: new DOMRect(0, 0, 800, 600),
        rootBounds: new DOMRect(0, 0, 1024, 768),
        time: Date.now()
      }], this)
    }, 10)
  }
  
  unobserve() {}
  disconnect() {}
}

// Mock window.matchMedia for responsive design tests
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: jest.fn().mockImplementation(query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: jest.fn(),
    removeListener: jest.fn(),
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  })),
})

// Mock clipboard API for copy functionality
Object.defineProperty(navigator, 'clipboard', {
  value: {
    writeText: jest.fn().mockResolvedValue(undefined),
    readText: jest.fn().mockResolvedValue(''),
  },
  writable: true,
})

// Mock canvas for chart testing
HTMLCanvasElement.prototype.getContext = jest.fn().mockReturnValue({
  fillRect: jest.fn(),
  clearRect: jest.fn(),
  getImageData: jest.fn().mockReturnValue({
    data: new Uint8ClampedArray(4)
  }),
  putImageData: jest.fn(),
  createImageData: jest.fn().mockReturnValue([]),
  setTransform: jest.fn(),
  drawImage: jest.fn(),
  save: jest.fn(),
  fillText: jest.fn(),
  restore: jest.fn(),
  beginPath: jest.fn(),
  moveTo: jest.fn(),
  lineTo: jest.fn(),
  closePath: jest.fn(),
  stroke: jest.fn(),
  translate: jest.fn(),
  scale: jest.fn(),
  rotate: jest.fn(),
  arc: jest.fn(),
  fill: jest.fn(),
  measureText: jest.fn().mockReturnValue({ width: 0 }),
  transform: jest.fn(),
  rect: jest.fn(),
  clip: jest.fn(),
})

// Mock URL.createObjectURL for file download testing
;(global as any).URL = {
  createObjectURL: jest.fn().mockReturnValue('mock-url'),
  revokeObjectURL: jest.fn(),
}

// Mock performance API for timing measurements
;(global as any).performance = {
  now: jest.fn().mockReturnValue(Date.now()),
  mark: jest.fn(),
  measure: jest.fn(),
  getEntriesByName: jest.fn().mockReturnValue([]),
  getEntriesByType: jest.fn().mockReturnValue([]),
  clearMarks: jest.fn(),
  clearMeasures: jest.fn(),
}

// Utility functions for test setup
export const createMockAnalyticsData = (overrides: any = {}) => ({
  usage: {
    totalUsers: 12847,
    activeUsers: 8932,
    newUsers: 234,
    sessionsPerUser: 2.4,
    avgSessionDuration: 420,
    pageViewsPerSession: 4.2,
    bounceRate: 35.2,
    topPages: [
      { page: '/dashboard', views: 15234, uniqueUsers: 8932 },
      { page: '/datasets', views: 12847, uniqueUsers: 7654 },
    ],
    userGrowth: [
      { date: '2025-01-01', newUsers: 25, activeUsers: 220 },
    ],
    hourlyActivity: [
      { hour: 0, users: 50, sessions: 80 },
    ],
    ...overrides.usage
  },
  performance: {
    avgResponseTime: 245,
    p50ResponseTime: 180,
    p95ResponseTime: 450,
    p99ResponseTime: 890,
    successRate: 98.5,
    errorRate: 1.5,
    throughput: 145.3,
    uptime: 99.8,
    responseTimeHistory: [
      { timestamp: '2025-01-01T00:00:00Z', avgTime: 200, p95Time: 400 },
    ],
    errorBreakdown: [
      { type: '4xx Client Error', count: 234, percentage: 65.2 },
    ],
    endpointPerformance: [
      { endpoint: '/api/analytics/metrics', avgTime: 450, calls: 12847, errors: 23 },
    ],
    ...overrides.performance
  },
  research: {
    analysesRun: 1847,
    datasetsUsed: new Map([['OpenNeuro', 234]]),
    toolsUsed: new Map([['fmri_glm_analysis', 345]]),
    popularWorkflows: [
      { workflow: 'Preprocessing → GLM → Results Visualization', usage: 234, successRate: 89.5 },
    ],
    publicationMetrics: {
      totalCitations: 1247,
      hIndex: 23,
      recentPublications: 15
    },
    datasetStats: {
      totalDatasets: 487,
      totalSubjects: 23847,
      modalityBreakdown: { 'fMRI': 234 }
    },
    toolUsageTrends: [
      { date: '2025-01-01', toolUsage: { 'fmri_glm_analysis': 10 } },
    ],
    ...overrides.research
  },
  system: {
    cpuUsage: 45.3,
    memoryUsage: 62.8,
    gpuUsage: 78.2,
    storageUsage: 34.7,
    queueLength: 5,
    activeJobs: 8,
    completedJobs: 1247,
    failedJobs: 23,
    resourceHistory: [
      { timestamp: '2025-01-01T00:00:00Z', cpu: 30, memory: 40, gpu: 60, storage: 30 },
    ],
    jobQueue: [
      { id: 'job_1', type: 'analysis', status: 'running', startTime: '2025-01-01T00:00:00Z', duration: 3600, user: 'user_1' },
    ],
    ...overrides.system
  },
  engagement: {
    dailyActiveUsers: 2847,
    weeklyActiveUsers: 8932,
    monthlyActiveUsers: 23847,
    retentionRate: 78.5,
    churnRate: 12.3,
    avgTimeOnSite: 450,
    conversionFunnels: [
      {
        name: 'New User Onboarding',
        steps: [
          { step: 'Sign Up', users: 1000, conversionRate: 100 },
        ]
      }
    ],
    featureAdoption: [
      { feature: 'Dashboard', adoptionRate: 89.2, activeUsers: 7964 },
    ],
    userSegments: [
      { segment: 'Researchers', users: 5432, engagement: 85.3 },
    ],
    ...overrides.engagement
  },
  ...overrides
})

export const createMockTimeRange = (overrides: any = {}) => ({
  label: 'Last 7 Days',
  value: '7d',
  start: new Date(Date.now() - 7 * 24 * 60 * 60 * 1000),
  end: new Date(),
  ...overrides
})

export const mockWebSocketMessage = (type: string, data: any) => {
  const message = new MessageEvent('message', {
    data: JSON.stringify({ type, data })
  })
  return message
}

// Console warning suppression for known issues
const originalWarn = console.warn
beforeEach(() => {
  console.warn = (...args) => {
    if (
      typeof args[0] === 'string' && 
      (args[0].includes('React does not recognize') ||
       args[0].includes('Warning: Failed prop type') ||
       args[0].includes('Warning: componentWillReceiveProps'))
    ) {
      return
    }
    originalWarn(...args)
  }
})

afterEach(() => {
  console.warn = originalWarn
})

// Global test utilities
export const waitForNextTick = () => new Promise(resolve => setTimeout(resolve, 0))

export const flushPromises = () => new Promise(resolve => setImmediate(resolve))