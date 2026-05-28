/**
 * Web Vitals tracking script for Brain Researcher UI
 * Measures Core Web Vitals and sends data to performance monitoring
 */

(function() {
  'use strict';

  // Only run in browsers that support the necessary APIs
  if (typeof window === 'undefined' || !window.performance) {
    return;
  }

  // Configuration
  const config = {
    enableLogging: window.location.hostname === 'localhost',
    enableReporting: true,
    reportUrl: '/api/performance/vitals',
    sampleRate: 1.0 // Report 100% in development, adjust for production
  };

  // Web Vitals data storage
  const vitalsData = {
    url: window.location.href,
    timestamp: Date.now(),
    userAgent: navigator.userAgent,
    connection: getConnectionInfo(),
    viewport: getViewportInfo(),
    vitals: {}
  };

  // Utility functions
  function getConnectionInfo() {
    const connection = navigator.connection || navigator.mozConnection || navigator.webkitConnection;
    if (connection) {
      return {
        effectiveType: connection.effectiveType,
        downlink: connection.downlink,
        rtt: connection.rtt,
        saveData: connection.saveData
      };
    }
    return null;
  }

  function getViewportInfo() {
    return {
      width: window.innerWidth,
      height: window.innerHeight,
      devicePixelRatio: window.devicePixelRatio || 1
    };
  }

  function log(metric, value, rating) {
    if (config.enableLogging) {
      console.log(`[Web Vitals] ${metric}: ${value.toFixed(2)}ms (${rating})`);
    }
  }

  function getRating(metric, value) {
    const thresholds = {
      LCP: { good: 2500, poor: 4000 },
      FID: { good: 100, poor: 300 },
      CLS: { good: 0.1, poor: 0.25 },
      FCP: { good: 1800, poor: 3000 },
      TTI: { good: 3000, poor: 5000 }, // Our key target
      TTFB: { good: 800, poor: 1800 }
    };

    const threshold = thresholds[metric];
    if (!threshold) return 'unknown';
    
    if (value <= threshold.good) return 'good';
    if (value <= threshold.poor) return 'needs-improvement';
    return 'poor';
  }

  function recordVital(name, value, delta) {
    const rating = getRating(name, value);
    
    vitalsData.vitals[name] = {
      value: value,
      rating: rating,
      delta: delta,
      timestamp: Date.now()
    };

    log(name, value, rating);

    // Special handling for TTI (our key metric)
    if (name === 'TTI') {
      vitalsData.ttiTargetMet = value < 3000;
      
      if (rating === 'poor') {
        console.warn(`[Performance] TTI target not met: ${value}ms > 3000ms`);
      }
    }

    // Report individual metrics immediately for real-time monitoring
    if (config.enableReporting && Math.random() < config.sampleRate) {
      reportVital(name, vitalsData.vitals[name]);
    }
  }

  function reportVital(name, vitalData) {
    const reportData = {
      ...vitalsData,
      vitals: { [name]: vitalData }
    };

    // Send to performance monitoring endpoint
    if (navigator.sendBeacon) {
      navigator.sendBeacon(config.reportUrl, JSON.stringify(reportData));
    } else {
      fetch(config.reportUrl, {
        method: 'POST',
        body: JSON.stringify(reportData),
        headers: {
          'Content-Type': 'application/json'
        },
        keepalive: true
      }).catch(error => {
        if (config.enableLogging) {
          console.error('[Web Vitals] Report failed:', error);
        }
      });
    }
  }

  function reportAllVitals() {
    if (config.enableReporting && Object.keys(vitalsData.vitals).length > 0) {
      reportVital('batch', vitalsData.vitals);
    }
  }

  // Core Web Vitals measurement

  // Largest Contentful Paint (LCP)
  function measureLCP() {
    if (!window.PerformanceObserver) return;

    try {
      const observer = new PerformanceObserver((list) => {
        const entries = list.getEntries();
        const lastEntry = entries[entries.length - 1];
        if (lastEntry) {
          recordVital('LCP', lastEntry.startTime);
        }
      });
      
      observer.observe({ entryTypes: ['largest-contentful-paint'] });
    } catch (e) {
      console.warn('[Web Vitals] LCP measurement not supported');
    }
  }

  // First Input Delay (FID)
  function measureFID() {
    if (!window.PerformanceObserver) return;

    try {
      const observer = new PerformanceObserver((list) => {
        const entries = list.getEntries();
        entries.forEach((entry) => {
          if (entry.processingStart && entry.startTime) {
            const fid = entry.processingStart - entry.startTime;
            recordVital('FID', fid);
          }
        });
      });
      
      observer.observe({ entryTypes: ['first-input'] });
    } catch (e) {
      console.warn('[Web Vitals] FID measurement not supported');
    }
  }

  // Cumulative Layout Shift (CLS)
  function measureCLS() {
    if (!window.PerformanceObserver) return;

    let clsValue = 0;
    let sessionValue = 0;
    let sessionEntries = [];

    try {
      const observer = new PerformanceObserver((list) => {
        const entries = list.getEntries();
        
        entries.forEach((entry) => {
          if (!entry.hadRecentInput) {
            const firstSessionEntry = sessionEntries[0];
            const lastSessionEntry = sessionEntries[sessionEntries.length - 1];

            // If the entry occurred less than 1 second after the previous entry and
            // less than 5 seconds after the first entry in the session, include it
            if (sessionValue &&
                entry.startTime - lastSessionEntry.startTime < 1000 &&
                entry.startTime - firstSessionEntry.startTime < 5000) {
              sessionValue += entry.value;
              sessionEntries.push(entry);
            } else {
              sessionValue = entry.value;
              sessionEntries = [entry];
            }

            if (sessionValue > clsValue) {
              clsValue = sessionValue;
              recordVital('CLS', clsValue);
            }
          }
        });
      });
      
      observer.observe({ entryTypes: ['layout-shift'] });
    } catch (e) {
      console.warn('[Web Vitals] CLS measurement not supported');
    }
  }

  // First Contentful Paint (FCP)
  function measureFCP() {
    if (!window.PerformanceObserver) return;

    try {
      const observer = new PerformanceObserver((list) => {
        const entries = list.getEntries();
        entries.forEach((entry) => {
          if (entry.name === 'first-contentful-paint') {
            recordVital('FCP', entry.startTime);
          }
        });
      });
      
      observer.observe({ entryTypes: ['paint'] });
    } catch (e) {
      console.warn('[Web Vitals] FCP measurement not supported');
    }
  }

  // Time to Interactive (TTI) - approximated
  function measureTTI() {
    // Wait for page to be mostly loaded
    if (document.readyState === 'complete') {
      calculateTTI();
    } else {
      window.addEventListener('load', calculateTTI);
    }
  }

  function calculateTTI() {
    // Simple TTI approximation based on navigation timing
    const navigation = performance.getEntriesByType('navigation')[0];
    if (navigation) {
      // TTI approximated as the latest of DOM complete and load event
      const domComplete = navigation.domComplete - navigation.navigationStart;
      const loadComplete = navigation.loadEventEnd - navigation.navigationStart;
      const tti = Math.max(domComplete, loadComplete);
      
      recordVital('TTI', tti);
    }
  }

  // Time to First Byte (TTFB)
  function measureTTFB() {
    const navigation = performance.getEntriesByType('navigation')[0];
    if (navigation) {
      const ttfb = navigation.responseStart - navigation.requestStart;
      recordVital('TTFB', ttfb);
    }
  }

  // Custom Brain Researcher specific metrics
  function measureCustomMetrics() {
    // Measure when main app components are ready
    const observer = new MutationObserver(() => {
      // Check if main content is loaded
      const mainContent = document.querySelector('#main-content, [data-testid="main-content"]');
      if (mainContent) {
        const navigationStart = performance.getEntriesByType('navigation')[0].navigationStart;
        const contentReady = performance.now();
        recordVital('ContentReady', contentReady);
        observer.disconnect();
      }
    });

    observer.observe(document.body, {
      childList: true,
      subtree: true
    });

    // Timeout after 10 seconds
    setTimeout(() => observer.disconnect(), 10000);
  }

  // Initialize Web Vitals measurement
  function init() {
    // Core Web Vitals
    measureLCP();
    measureFID();
    measureCLS();
    measureFCP();
    measureTTI();
    measureTTFB();

    // Custom metrics
    measureCustomMetrics();

    // Report all vitals when page is about to unload
    window.addEventListener('beforeunload', reportAllVitals);
    window.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') {
        reportAllVitals();
      }
    });

    // Report vitals after a delay for final measurement
    setTimeout(reportAllVitals, 5000);
  }

  // Start measuring when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // Expose vitals data for debugging
  window.brainResearcherVitals = vitalsData;

  if (config.enableLogging) {
    console.log('[Web Vitals] Monitoring initialized');
  }

})();