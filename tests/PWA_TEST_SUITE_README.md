# Brain Researcher PWA Test Suite

## Overview

This comprehensive test suite validates the Progressive Web App (PWA) implementation for Brain Researcher, ensuring robust offline capabilities, efficient caching strategies, push notification functionality, and seamless mobile experiences for neuroimaging research workflows.

## Test Coverage

### 1. Service Worker Tests (`/tests/unit/pwa/test_service_worker.js`)

**Coverage Areas:**
- Service worker installation and activation lifecycle
- Brain-specific caching strategies for neuroimaging data
- IndexedDB integration for large brain imaging files
- Background sync operations for analysis results
- Push notification handling with brain research templates
- Cache management and cleanup operations
- Performance metrics tracking

**Key Features Tested:**
- ✅ Static resource caching during installation
- ✅ Specialized brain data cache strategies (24-hour cache for atlas data)
- ✅ Analysis results caching (1-hour cache for dynamic results)
- ✅ Large file handling with progress tracking (.nii.gz files)
- ✅ Offline fallback strategies for navigation requests
- ✅ Background sync for critical brain data synchronization
- ✅ Push notification delivery and action handling
- ✅ Cache statistics and health monitoring

### 2. Push Notification Tests (`/tests/unit/pwa/test_push_notifications.py`)

**Coverage Areas:**
- Push notification subscription and management
- Brain research specific notification templates
- Permission handling and user experience flows
- Backend integration and subscription synchronization
- Notification scheduling and optimal delivery timing
- Engagement analytics and delivery metrics

**Key Features Tested:**
- ✅ Service worker registration and push manager setup
- ✅ VAPID key configuration and subscription creation
- ✅ Brain-specific notification templates (analysis complete, data updates, system alerts)
- ✅ Notification action handling (view results, sync data, dismiss)
- ✅ Optimal timing for research notifications (respect quiet hours)
- ✅ Mobile device detection and platform-specific handling
- ✅ Engagement metrics and click-through tracking

### 3. Mobile Component Tests (`/tests/unit/components/test_mobile_components.tsx`)

**Coverage Areas:**
- Mobile app shell architecture and navigation
- PWA install prompt and user onboarding
- Offline indicator and capability display
- Touch interactions for brain visualization
- Responsive design and orientation handling
- Accessibility features for mobile interfaces

**Key Features Tested:**
- ✅ Mobile app shell with header, main content, and bottom navigation
- ✅ PWA install prompt with brain research benefits messaging
- ✅ Offline indicator showing available neuroimaging capabilities
- ✅ Touch gesture support for 3D brain visualization (pinch, pan, rotate)
- ✅ Mobile navigation with brain research specific sections
- ✅ Responsive layouts for different screen sizes and orientations
- ✅ Accessibility compliance with ARIA labels and keyboard navigation
- ✅ Performance optimizations for mobile rendering

### 4. PWA Lifecycle Integration Tests (`/tests/integration/test_pwa_lifecycle.spec.ts`)

**Coverage Areas:**
- Complete PWA installation and update workflows
- Service worker lifecycle management
- Cache population and invalidation strategies
- Online/offline transition handling
- Background sync operations
- Performance metrics collection

**Key Features Tested:**
- ✅ Service worker registration and static resource caching
- ✅ PWA installation flow with user prompts
- ✅ Service worker updates and cache cleanup
- ✅ Brain data caching with appropriate expiration policies
- ✅ Large brain imaging file handling with IndexedDB storage
- ✅ Download progress tracking for neuroimaging datasets
- ✅ Offline state detection and indicator display
- ✅ Background synchronization for analysis results and brain data
- ✅ Push notification delivery and interaction handling
- ✅ Performance telemetry and offline capability reporting

### 5. End-to-End Offline Functionality Tests (`/tests/e2e/test_offline_functionality.spec.ts`)

**Coverage Areas:**
- Complete offline workflows for brain research
- Data accessibility during network outages
- Research workflow continuity in offline mode
- Collaboration features with offline support
- Data synchronization when connectivity is restored

**Key Features Tested:**
- ✅ Brain atlas access with cached regional and network data
- ✅ Analysis result display and interaction while offline
- ✅ Research note creation and editing in offline mode
- ✅ Brain visualization rendering from cached surface data
- ✅ Statistical overlay display and interactive features offline
- ✅ Collaboration annotations and comment queuing
- ✅ Version control and conflict resolution for offline edits
- ✅ Comprehensive data synchronization on reconnection
- ✅ Sync conflict resolution and priority handling
- ✅ Performance maintenance under poor network conditions

## Brain Research Specific Features

### Neuroimaging Data Optimization
- **Atlas Data Caching**: Long-term caching (24 hours) for brain region and network data
- **Analysis Results**: Shorter caching (1 hour) for dynamic analysis results
- **Large File Handling**: Streaming download with progress for .nii.gz files
- **IndexedDB Storage**: Efficient storage for large brain imaging datasets

### Research Workflow Support
- **Offline Analysis**: Queue analysis jobs for execution when connectivity returns
- **Research Documentation**: Create and edit research notes with markdown support
- **Visualization State**: Maintain 3D brain visualization state across offline periods
- **Collaboration Features**: Queue comments, annotations, and sharing requests

### Mobile Brain Research Interface
- **Touch Interactions**: Pinch-to-zoom, pan, and rotate for 3D brain models
- **Responsive Layouts**: Optimized layouts for different screen orientations
- **Brain-Specific Navigation**: Quick access to atlas, analysis, and visualization tools
- **Offline Capabilities Display**: Show users what brain research features work offline

## Running the Tests

### Prerequisites
```bash
npm install
npm install -D @playwright/test @testing-library/react @testing-library/jest-dom
```

### Unit Tests
```bash
# Service Worker Tests (JavaScript)
npm test tests/unit/pwa/test_service_worker.js

# Push Notification Tests (Python)
cd tests/unit/pwa && python -m pytest test_push_notifications.py -v

# Mobile Component Tests (TypeScript/React)
npm test tests/unit/components/test_mobile_components.tsx
```

### Integration Tests
```bash
# PWA Lifecycle Tests (Playwright)
npx playwright test tests/integration/test_pwa_lifecycle.spec.ts
```

### End-to-End Tests
```bash
# Offline Functionality Tests (Playwright)
npx playwright test tests/e2e/test_offline_functionality.spec.ts

# Run with specific browser
npx playwright test tests/e2e/test_offline_functionality.spec.ts --project=chromium

# Run with UI mode for debugging
npx playwright test tests/e2e/test_offline_functionality.spec.ts --ui
```

### Test Environment Setup

#### Local Development
```bash
# Start Brain Researcher services
npm run dev

# Start test database and services
docker-compose -f docker-compose.test.yml up -d

# Run tests
npm run test:pwa
```

#### CI/CD Pipeline
```yaml
# Example GitHub Actions workflow
- name: PWA Tests
  run: |
    npm run build
    npm run start:test &
    npx playwright test tests/integration/test_pwa_lifecycle.spec.ts
    npx playwright test tests/e2e/test_offline_functionality.spec.ts
```

## Test Data and Mocks

### Mock Brain Research Data
The tests use comprehensive mock data representing real neuroimaging research scenarios:

```javascript
// Brain Atlas Data
{
  regions: [
    { id: 'frontal_cortex', name: 'Frontal Cortex', function: 'Executive control' },
    { id: 'temporal_cortex', name: 'Temporal Cortex', function: 'Auditory processing' }
  ],
  networks: [
    { id: 'default_mode', name: 'Default Mode Network', connectivity: 0.85 }
  ]
}

// Analysis Results
{
  analysisId: 'glm_123',
  results: {
    significantActivation: [
      { region: 'frontal_cortex', tScore: 4.2, pValue: 0.0001 }
    ]
  }
}
```

### Service Worker Mocking
Comprehensive mocking of browser APIs:
- Cache API for testing caching strategies
- IndexedDB for large file storage testing
- Push Manager for notification testing
- Network conditions simulation

## Performance Benchmarks

### Target Metrics
- **Installation Time**: < 5 seconds for initial PWA installation
- **Offline Load Time**: < 2 seconds for cached brain atlas data
- **Large File Download**: Progress tracking for files > 10MB
- **Sync Time**: < 30 seconds for typical offline changes
- **Cache Hit Rate**: > 80% for frequently accessed brain data

### Memory Usage
- **Service Worker Memory**: < 50MB for typical caching operations
- **IndexedDB Storage**: Efficient compression for brain imaging files
- **Cache Size Limits**: Automatic cleanup when approaching 50MB limit

## Accessibility Testing

### Mobile Accessibility Features
- **Screen Reader Support**: ARIA labels for all navigation elements
- **Keyboard Navigation**: Full keyboard support for mobile interfaces
- **High Contrast Mode**: Support for users with visual impairments
- **Touch Target Size**: Minimum 44px touch targets for brain interface controls

### Testing Tools Integration
```bash
# Accessibility testing with axe-core
npm install -D @axe-core/playwright
npx playwright test --grep "accessibility"
```

## Troubleshooting

### Common Issues

#### Service Worker Not Registering
```javascript
// Debug service worker registration
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/service-worker.js')
    .then(reg => console.log('SW registered', reg))
    .catch(err => console.log('SW registration failed', err));
}
```

#### Cache Not Populating
- Check network requests in DevTools
- Verify cache strategy implementation
- Ensure HTTPS for service worker functionality

#### Offline Tests Failing
- Confirm service worker is activated before going offline
- Wait for cache population before testing offline access
- Check IndexedDB storage for large files

#### Push Notifications Not Working
- Verify VAPID keys are configured correctly
- Check notification permission status
- Ensure service worker can receive push events

## Contributing

### Adding New PWA Tests
1. Follow the established patterns in existing test files
2. Include brain research specific scenarios
3. Test both online and offline conditions
4. Add performance benchmarks where appropriate
5. Update this documentation with new test coverage

### Test Naming Conventions
- Use descriptive test names that explain the scenario
- Group related tests in describe blocks
- Include "offline", "mobile", or "pwa" in test descriptions where relevant
- Focus on brain research workflow scenarios

## Related Documentation

- [PWA Implementation Guide](../docs/guides/pwa-implementation.md)
- [Service Worker Architecture](../docs/architecture/service-worker.md)
- [Brain Data Caching Strategy](../docs/architecture/brain-data-caching.md)
- [Mobile UI Guidelines](../docs/design/mobile-ui-guidelines.md)
- [Offline Research Workflows](../docs/workflows/offline-research.md)