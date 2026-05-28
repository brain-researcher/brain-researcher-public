/**
 * Jest Configuration for Analytics Dashboard Tests
 * 
 * Specialized configuration for testing analytics components with:
 * - WebSocket mocking
 * - Chart library mocking  
 * - Real-time data simulation
 * - Performance testing utilities
 */

const path = require('path')

module.exports = {
  displayName: 'Analytics Dashboard Tests',
  testMatch: [
    '<rootDir>/tests/unit/components/analytics/**/*.test.{ts,tsx}'
  ],
  
  // Environment setup
  testEnvironment: 'jsdom',
  setupFilesAfterEnv: [
    '<rootDir>/tests/unit/components/analytics/setup.ts'
  ],
  
  // Module mapping for analytics-specific mocks
  moduleNameMapping: {
    '^@/components/(.*)$': '<rootDir>/apps/web-ui/src/components/$1',
    '^@/hooks/(.*)$': '<rootDir>/apps/web-ui/src/hooks/$1',
    '^@/types/(.*)$': '<rootDir>/apps/web-ui/src/types/$1',
    '^@/lib/(.*)$': '<rootDir>/apps/web-ui/src/lib/$1'
  },
  
  // Transform configuration for TypeScript and JSX
  transform: {
    '^.+\\.(ts|tsx)$': ['ts-jest', {
      useESM: false,
      tsconfig: {
        jsx: 'react-jsx'
      }
    }]
  },
  
  // Module file extensions
  moduleFileExtensions: ['ts', 'tsx', 'js', 'jsx', 'json'],
  
  // Coverage configuration
  collectCoverageFrom: [
    'apps/web-ui/src/components/analytics/**/*.{ts,tsx}',
    'apps/web-ui/src/hooks/useAnalytics*.{ts,tsx}',
    '!**/*.d.ts',
    '!**/*.stories.{ts,tsx}',
    '!**/node_modules/**'
  ],
  
  coverageThresholds: {
    './apps/web-ui/src/components/analytics/': {
      branches: 85,
      functions: 85,
      lines: 85,
      statements: 85
    },
    './apps/web-ui/src/hooks/useAnalytics*.ts': {
      branches: 90,
      functions: 90,
      lines: 90,
      statements: 90
    }
  },
  
  // Test timeout for async operations
  testTimeout: 10000,
  
  // Global setup
  globals: {
    'ts-jest': {
      tsconfig: '<rootDir>/tsconfig.json'
    }
  },
  
  // Clear mocks between tests
  clearMocks: true,
  restoreMocks: true,
  
  // Verbose output for detailed test reporting
  verbose: true
}