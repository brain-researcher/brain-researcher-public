/**
 * CDN Performance Monitoring System for Brain Researcher
 * Real-time monitoring of CDN performance, cache hit rates, and user experience metrics
 */

const EventEmitter = require('events');
const fetch = require('node-fetch');
const fs = require('fs').promises;

class PerformanceMonitor extends EventEmitter {
    constructor(options = {}) {
        super();
        
        this.config = {
            // Monitoring endpoints
            distributionId: options.distributionId || process.env.CLOUDFRONT_DISTRIBUTION_ID,
            region: options.region || process.env.AWS_REGION || 'us-east-1',
            
            // Monitoring intervals
            metricsInterval: options.metricsInterval || 60000, // 1 minute
            healthCheckInterval: options.healthCheckInterval || 300000, // 5 minutes
            reportInterval: options.reportInterval || 3600000, // 1 hour
            
            // Thresholds
            thresholds: {
                responseTime: options.responseTimeThreshold || 2000, // 2 seconds
                errorRate: options.errorRateThreshold || 5, // 5%
                cacheHitRate: options.cacheHitRateThreshold || 80, // 80%
                throughput: options.throughputThreshold || 100 // requests/minute
            },
            
            // Storage
            metricsRetention: options.metricsRetention || 86400000, // 24 hours
            reportPath: options.reportPath || './reports/performance',
            
            // Endpoints to monitor
            endpoints: options.endpoints || [
                { url: '/', name: 'homepage', critical: true },
                { url: '/knowledge-graph', name: 'knowledge-graph', critical: true },
                { url: '/api/health', name: 'api-health', critical: true },
                { url: '/api/datasets', name: 'api-datasets', critical: false },
                { url: '/static/css/main.css', name: 'main-css', critical: false },
                { url: '/static/js/main.js', name: 'main-js', critical: false }
            ]
        };
        
        this.metrics = new Map();
        this.alerts = [];
        this.intervals = new Map();
        this.isMonitoring = false;
        
        // Initialize AWS SDK if available
        this.initializeAWS();
        
        // Create reports directory
        this.ensureReportsDirectory();
    }
    
    /**
     * Initialize AWS SDK for CloudWatch metrics
     */
    async initializeAWS() {
        try {
            this.cloudWatch = require('@aws-sdk/client-cloudwatch');
            this.client = new this.cloudWatch.CloudWatchClient({ 
                region: this.config.region 
            });
            
            console.log('✅ AWS CloudWatch client initialized');
        } catch (error) {
            console.warn('⚠️  AWS SDK not available, using local metrics only');
            this.client = null;
        }
    }
    
    /**
     * Ensure reports directory exists
     */
    async ensureReportsDirectory() {
        try {
            await fs.mkdir(this.config.reportPath, { recursive: true });
        } catch (error) {
            console.warn('Failed to create reports directory:', error);
        }
    }
    
    /**
     * Start monitoring
     */
    start() {
        if (this.isMonitoring) {
            console.log('⚠️  Monitoring already started');
            return;
        }
        
        console.log('🚀 Starting CDN performance monitoring...');
        
        this.isMonitoring = true;
        
        // Start metric collection
        const metricsInterval = setInterval(() => {
            this.collectMetrics().catch(error => {
                console.error('Metrics collection error:', error);
            });
        }, this.config.metricsInterval);
        
        // Start health checks
        const healthInterval = setInterval(() => {
            this.performHealthChecks().catch(error => {
                console.error('Health check error:', error);
            });
        }, this.config.healthCheckInterval);
        
        // Start periodic reporting
        const reportInterval = setInterval(() => {
            this.generateReport().catch(error => {
                console.error('Report generation error:', error);
            });
        }, this.config.reportInterval);
        
        this.intervals.set('metrics', metricsInterval);
        this.intervals.set('health', healthInterval);
        this.intervals.set('report', reportInterval);
        
        // Initial collection
        this.collectMetrics();
        this.performHealthChecks();
        
        this.emit('started');
    }
    
    /**
     * Stop monitoring
     */
    stop() {
        if (!this.isMonitoring) {
            console.log('⚠️  Monitoring not started');
            return;
        }
        
        console.log('🛑 Stopping CDN performance monitoring...');
        
        this.intervals.forEach(interval => clearInterval(interval));
        this.intervals.clear();
        
        this.isMonitoring = false;
        this.emit('stopped');
    }
    
    /**
     * Collect performance metrics
     */
    async collectMetrics() {
        const timestamp = Date.now();
        const metrics = {
            timestamp,
            cloudfront: await this.getCloudFrontMetrics(),
            endpoints: await this.getEndpointMetrics(),
            webVitals: await this.getWebVitalMetrics(),
            cache: await this.getCacheMetrics()
        };
        
        // Store metrics
        this.storeMetrics(metrics);
        
        // Check thresholds and emit alerts
        this.checkThresholds(metrics);
        
        this.emit('metricsCollected', metrics);
        
        return metrics;
    }
    
    /**
     * Get CloudFront metrics from AWS
     */
    async getCloudFrontMetrics() {
        if (!this.client || !this.config.distributionId) {
            return null;
        }
        
        try {
            const endTime = new Date();
            const startTime = new Date(endTime - 300000); // 5 minutes ago
            
            const params = {
                MetricDataQueries: [
                    {
                        Id: 'requests',
                        MetricStat: {
                            Metric: {
                                Namespace: 'AWS/CloudFront',
                                MetricName: 'Requests',
                                Dimensions: [
                                    {
                                        Name: 'DistributionId',
                                        Value: this.config.distributionId
                                    }
                                ]
                            },
                            Period: 300,
                            Stat: 'Sum'
                        }
                    },
                    {
                        Id: 'bytes_downloaded',
                        MetricStat: {
                            Metric: {
                                Namespace: 'AWS/CloudFront',
                                MetricName: 'BytesDownloaded',
                                Dimensions: [
                                    {
                                        Name: 'DistributionId',
                                        Value: this.config.distributionId
                                    }
                                ]
                            },
                            Period: 300,
                            Stat: 'Sum'
                        }
                    },
                    {
                        Id: 'error_rate',
                        MetricStat: {
                            Metric: {
                                Namespace: 'AWS/CloudFront',
                                MetricName: '4xxErrorRate',
                                Dimensions: [
                                    {
                                        Name: 'DistributionId',
                                        Value: this.config.distributionId
                                    }
                                ]
                            },
                            Period: 300,
                            Stat: 'Average'
                        }
                    },
                    {
                        Id: 'origin_latency',
                        MetricStat: {
                            Metric: {
                                Namespace: 'AWS/CloudFront',
                                MetricName: 'OriginLatency',
                                Dimensions: [
                                    {
                                        Name: 'DistributionId',
                                        Value: this.config.distributionId
                                    }
                                ]
                            },
                            Period: 300,
                            Stat: 'Average'
                        }
                    },
                    {
                        Id: 'cache_hit_rate',
                        MetricStat: {
                            Metric: {
                                Namespace: 'AWS/CloudFront',
                                MetricName: 'CacheHitRate',
                                Dimensions: [
                                    {
                                        Name: 'DistributionId',
                                        Value: this.config.distributionId
                                    }
                                ]
                            },
                            Period: 300,
                            Stat: 'Average'
                        }
                    }
                ],
                StartTime: startTime,
                EndTime: endTime
            };
            
            const command = new this.cloudWatch.GetMetricDataCommand(params);
            const response = await this.client.send(command);
            
            const result = {};
            response.MetricDataResults.forEach(metric => {
                result[metric.Id] = metric.Values.length > 0 ? metric.Values[0] : 0;
            });
            
            return result;
            
        } catch (error) {
            console.error('Failed to get CloudFront metrics:', error);
            return null;
        }
    }
    
    /**
     * Get endpoint-specific metrics
     */
    async getEndpointMetrics() {
        const results = [];
        
        for (const endpoint of this.config.endpoints) {
            try {
                const start = Date.now();
                
                const response = await fetch(endpoint.url, {
                    method: 'GET',
                    headers: {
                        'User-Agent': 'BrainResearcher-Monitor/1.0',
                        'Accept': '*/*'
                    },
                    timeout: 10000
                });
                
                const duration = Date.now() - start;
                
                results.push({
                    name: endpoint.name,
                    url: endpoint.url,
                    critical: endpoint.critical,
                    status: response.status,
                    ok: response.ok,
                    duration,
                    size: parseInt(response.headers.get('content-length') || '0'),
                    cacheStatus: response.headers.get('x-cache') || 
                               response.headers.get('cf-cache-status') || 
                               'unknown',
                    server: response.headers.get('server'),
                    contentType: response.headers.get('content-type')
                });
                
            } catch (error) {
                results.push({
                    name: endpoint.name,
                    url: endpoint.url,
                    critical: endpoint.critical,
                    status: 0,
                    ok: false,
                    duration: null,
                    error: error.message
                });
            }
        }
        
        return results;
    }
    
    /**
     * Get Web Vitals metrics (simulated - would normally come from browser)
     */
    async getWebVitalMetrics() {
        // In a real implementation, these would come from browser APIs
        // For now, we'll simulate based on endpoint metrics
        const homepage = this.config.endpoints.find(e => e.name === 'homepage');
        if (!homepage) return null;
        
        try {
            const start = Date.now();
            const response = await fetch(homepage.url, {
                headers: { 'User-Agent': 'BrainResearcher-Monitor/1.0' }
            });
            const html = await response.text();
            const duration = Date.now() - start;
            
            // Simulate Core Web Vitals
            return {
                // Largest Contentful Paint (LCP) - should be < 2.5s
                lcp: duration + Math.random() * 500,
                
                // First Input Delay (FID) - should be < 100ms  
                fid: Math.random() * 50,
                
                // Cumulative Layout Shift (CLS) - should be < 0.1
                cls: Math.random() * 0.05,
                
                // First Contentful Paint (FCP) - should be < 1.8s
                fcp: duration * 0.6,
                
                // Time to Interactive (TTI)
                tti: duration + Math.random() * 1000,
                
                // Total Blocking Time (TBT)
                tbt: Math.random() * 200
            };
            
        } catch (error) {
            return null;
        }
    }
    
    /**
     * Get cache performance metrics
     */
    async getCacheMetrics() {
        const endpointMetrics = await this.getEndpointMetrics();
        
        const totalRequests = endpointMetrics.length;
        const cacheHits = endpointMetrics.filter(m => 
            m.cacheStatus && (m.cacheStatus.toLowerCase().includes('hit') || 
                             m.cacheStatus.toLowerCase().includes('cached'))
        ).length;
        
        const cacheMisses = endpointMetrics.filter(m => 
            m.cacheStatus && m.cacheStatus.toLowerCase().includes('miss')
        ).length;
        
        const averageResponseTime = endpointMetrics
            .filter(m => m.duration)
            .reduce((sum, m) => sum + m.duration, 0) / 
            Math.max(1, endpointMetrics.filter(m => m.duration).length);
        
        return {
            hitRate: totalRequests > 0 ? (cacheHits / totalRequests) * 100 : 0,
            missRate: totalRequests > 0 ? (cacheMisses / totalRequests) * 100 : 0,
            totalRequests,
            cacheHits,
            cacheMisses,
            averageResponseTime: Math.round(averageResponseTime)
        };
    }
    
    /**
     * Store metrics in memory with retention
     */
    storeMetrics(metrics) {
        const key = metrics.timestamp;
        this.metrics.set(key, metrics);
        
        // Clean up old metrics
        const cutoff = Date.now() - this.config.metricsRetention;
        for (const [timestamp] of this.metrics) {
            if (timestamp < cutoff) {
                this.metrics.delete(timestamp);
            }
        }
    }
    
    /**
     * Check performance thresholds and emit alerts
     */
    checkThresholds(metrics) {
        const alerts = [];
        
        // Check response time
        if (metrics.endpoints) {
            const criticalEndpoints = metrics.endpoints.filter(e => e.critical);
            const slowEndpoints = criticalEndpoints.filter(e => 
                e.duration && e.duration > this.config.thresholds.responseTime
            );
            
            if (slowEndpoints.length > 0) {
                alerts.push({
                    type: 'slow_response',
                    severity: 'warning',
                    message: `${slowEndpoints.length} critical endpoints have slow response times`,
                    endpoints: slowEndpoints.map(e => ({ name: e.name, duration: e.duration }))
                });
            }
        }
        
        // Check error rate
        if (metrics.cloudfront && metrics.cloudfront.error_rate > this.config.thresholds.errorRate) {
            alerts.push({
                type: 'high_error_rate',
                severity: 'critical',
                message: `Error rate is ${metrics.cloudfront.error_rate.toFixed(2)}%`,
                value: metrics.cloudfront.error_rate
            });
        }
        
        // Check cache hit rate
        if (metrics.cache && metrics.cache.hitRate < this.config.thresholds.cacheHitRate) {
            alerts.push({
                type: 'low_cache_hit_rate',
                severity: 'warning',
                message: `Cache hit rate is ${metrics.cache.hitRate.toFixed(2)}%`,
                value: metrics.cache.hitRate
            });
        }
        
        // Check Web Vitals
        if (metrics.webVitals) {
            if (metrics.webVitals.lcp > 2500) {
                alerts.push({
                    type: 'poor_lcp',
                    severity: 'warning',
                    message: `LCP is ${metrics.webVitals.lcp}ms (should be < 2500ms)`,
                    value: metrics.webVitals.lcp
                });
            }
            
            if (metrics.webVitals.fid > 100) {
                alerts.push({
                    type: 'poor_fid',
                    severity: 'warning',
                    message: `FID is ${metrics.webVitals.fid}ms (should be < 100ms)`,
                    value: metrics.webVitals.fid
                });
            }
            
            if (metrics.webVitals.cls > 0.1) {
                alerts.push({
                    type: 'poor_cls',
                    severity: 'warning',
                    message: `CLS is ${metrics.webVitals.cls} (should be < 0.1)`,
                    value: metrics.webVitals.cls
                });
            }
        }
        
        // Emit alerts
        alerts.forEach(alert => {
            this.alerts.push({ ...alert, timestamp: metrics.timestamp });
            this.emit('alert', alert);
        });
        
        return alerts;
    }
    
    /**
     * Perform comprehensive health checks
     */
    async performHealthChecks() {
        console.log('🏥 Performing health checks...');
        
        const results = {
            timestamp: Date.now(),
            overall: 'healthy',
            checks: {}
        };
        
        // Check endpoint availability
        const endpointMetrics = await this.getEndpointMetrics();
        const failedEndpoints = endpointMetrics.filter(e => !e.ok);
        
        results.checks.endpoints = {
            status: failedEndpoints.length === 0 ? 'healthy' : 'unhealthy',
            total: endpointMetrics.length,
            failed: failedEndpoints.length,
            failures: failedEndpoints.map(e => ({ name: e.name, error: e.error || `HTTP ${e.status}` }))
        };
        
        // Check cache performance
        const cacheMetrics = await this.getCacheMetrics();
        results.checks.cache = {
            status: cacheMetrics.hitRate >= this.config.thresholds.cacheHitRate ? 'healthy' : 'degraded',
            hitRate: cacheMetrics.hitRate,
            threshold: this.config.thresholds.cacheHitRate
        };
        
        // Check response times
        const slowEndpoints = endpointMetrics.filter(e => 
            e.duration && e.duration > this.config.thresholds.responseTime
        );
        
        results.checks.performance = {
            status: slowEndpoints.length === 0 ? 'healthy' : 'degraded',
            slowEndpoints: slowEndpoints.length,
            threshold: this.config.thresholds.responseTime
        };
        
        // Determine overall health
        const unhealthyChecks = Object.values(results.checks).filter(c => c.status === 'unhealthy');
        const degradedChecks = Object.values(results.checks).filter(c => c.status === 'degraded');
        
        if (unhealthyChecks.length > 0) {
            results.overall = 'unhealthy';
        } else if (degradedChecks.length > 0) {
            results.overall = 'degraded';
        }
        
        this.emit('healthCheck', results);
        
        console.log(`🏥 Health check completed: ${results.overall}`);
        
        return results;
    }
    
    /**
     * Generate comprehensive performance report
     */
    async generateReport() {
        const now = Date.now();
        const hourAgo = now - 3600000; // 1 hour ago
        
        // Get metrics from last hour
        const recentMetrics = Array.from(this.metrics.entries())
            .filter(([timestamp]) => timestamp >= hourAgo)
            .map(([, metrics]) => metrics);
        
        if (recentMetrics.length === 0) {
            console.log('📊 No metrics available for report');
            return null;
        }
        
        const report = {
            timestamp: now,
            period: {
                start: new Date(hourAgo).toISOString(),
                end: new Date(now).toISOString(),
                duration: '1 hour'
            },
            summary: this.generateSummary(recentMetrics),
            performance: this.generatePerformanceAnalysis(recentMetrics),
            cache: this.generateCacheAnalysis(recentMetrics),
            webVitals: this.generateWebVitalsAnalysis(recentMetrics),
            alerts: this.getRecentAlerts(hourAgo),
            recommendations: this.generateRecommendations(recentMetrics)
        };
        
        // Save report
        const reportPath = `${this.config.reportPath}/performance-report-${new Date().toISOString().split('T')[0]}.json`;
        try {
            await fs.writeFile(reportPath, JSON.stringify(report, null, 2));
            console.log(`📊 Performance report saved: ${reportPath}`);
        } catch (error) {
            console.error('Failed to save report:', error);
        }
        
        this.emit('reportGenerated', report);
        
        return report;
    }
    
    /**
     * Generate summary statistics
     */
    generateSummary(metrics) {
        const endpointData = metrics.map(m => m.endpoints).filter(Boolean).flat();
        const cacheData = metrics.map(m => m.cache).filter(Boolean);
        
        return {
            totalRequests: endpointData.length,
            successRate: endpointData.length > 0 ? 
                (endpointData.filter(e => e.ok).length / endpointData.length) * 100 : 0,
            averageResponseTime: endpointData.length > 0 ?
                endpointData.filter(e => e.duration).reduce((sum, e) => sum + e.duration, 0) / 
                endpointData.filter(e => e.duration).length : 0,
            averageCacheHitRate: cacheData.length > 0 ?
                cacheData.reduce((sum, c) => sum + c.hitRate, 0) / cacheData.length : 0
        };
    }
    
    /**
     * Generate performance analysis
     */
    generatePerformanceAnalysis(metrics) {
        const endpointData = metrics.map(m => m.endpoints).filter(Boolean).flat();
        
        // Group by endpoint
        const byEndpoint = {};
        endpointData.forEach(e => {
            if (!byEndpoint[e.name]) {
                byEndpoint[e.name] = [];
            }
            byEndpoint[e.name].push(e);
        });
        
        const analysis = {};
        Object.entries(byEndpoint).forEach(([name, data]) => {
            const durations = data.filter(d => d.duration).map(d => d.duration);
            analysis[name] = {
                requests: data.length,
                successRate: (data.filter(d => d.ok).length / data.length) * 100,
                averageResponseTime: durations.length > 0 ? 
                    durations.reduce((sum, d) => sum + d, 0) / durations.length : 0,
                minResponseTime: durations.length > 0 ? Math.min(...durations) : 0,
                maxResponseTime: durations.length > 0 ? Math.max(...durations) : 0
            };
        });
        
        return analysis;
    }
    
    /**
     * Generate cache analysis
     */
    generateCacheAnalysis(metrics) {
        const cacheData = metrics.map(m => m.cache).filter(Boolean);
        
        if (cacheData.length === 0) return null;
        
        return {
            averageHitRate: cacheData.reduce((sum, c) => sum + c.hitRate, 0) / cacheData.length,
            totalRequests: cacheData.reduce((sum, c) => sum + c.totalRequests, 0),
            totalHits: cacheData.reduce((sum, c) => sum + c.cacheHits, 0),
            totalMisses: cacheData.reduce((sum, c) => sum + c.cacheMisses, 0),
            trend: this.calculateTrend(cacheData.map(c => c.hitRate))
        };
    }
    
    /**
     * Generate Web Vitals analysis
     */
    generateWebVitalsAnalysis(metrics) {
        const webVitalsData = metrics.map(m => m.webVitals).filter(Boolean);
        
        if (webVitalsData.length === 0) return null;
        
        const avgMetrics = {};
        ['lcp', 'fid', 'cls', 'fcp', 'tti', 'tbt'].forEach(metric => {
            avgMetrics[metric] = webVitalsData.reduce((sum, w) => sum + (w[metric] || 0), 0) / webVitalsData.length;
        });
        
        return {
            averages: avgMetrics,
            scores: {
                lcp: avgMetrics.lcp <= 2500 ? 'good' : avgMetrics.lcp <= 4000 ? 'needs-improvement' : 'poor',
                fid: avgMetrics.fid <= 100 ? 'good' : avgMetrics.fid <= 300 ? 'needs-improvement' : 'poor',
                cls: avgMetrics.cls <= 0.1 ? 'good' : avgMetrics.cls <= 0.25 ? 'needs-improvement' : 'poor'
            }
        };
    }
    
    /**
     * Get recent alerts
     */
    getRecentAlerts(since) {
        return this.alerts.filter(alert => alert.timestamp >= since);
    }
    
    /**
     * Generate performance recommendations
     */
    generateRecommendations(metrics) {
        const recommendations = [];
        const summary = this.generateSummary(metrics);
        const cache = this.generateCacheAnalysis(metrics);
        
        if (summary.averageResponseTime > this.config.thresholds.responseTime) {
            recommendations.push({
                type: 'performance',
                priority: 'high',
                message: 'Average response time is above threshold',
                suggestion: 'Consider optimizing server response times or implementing additional caching'
            });
        }
        
        if (cache && cache.averageHitRate < this.config.thresholds.cacheHitRate) {
            recommendations.push({
                type: 'caching',
                priority: 'medium',
                message: 'Cache hit rate is below optimal level',
                suggestion: 'Review cache headers and consider implementing cache warming for critical resources'
            });
        }
        
        if (summary.successRate < 99) {
            recommendations.push({
                type: 'reliability',
                priority: 'high',
                message: 'Success rate is below 99%',
                suggestion: 'Investigate failing endpoints and implement better error handling'
            });
        }
        
        return recommendations;
    }
    
    /**
     * Calculate trend (positive = improving, negative = degrading)
     */
    calculateTrend(values) {
        if (values.length < 2) return 0;
        
        const firstHalf = values.slice(0, Math.floor(values.length / 2));
        const secondHalf = values.slice(Math.floor(values.length / 2));
        
        const firstAvg = firstHalf.reduce((sum, v) => sum + v, 0) / firstHalf.length;
        const secondAvg = secondHalf.reduce((sum, v) => sum + v, 0) / secondHalf.length;
        
        return secondAvg - firstAvg;
    }
    
    /**
     * Get current status
     */
    getStatus() {
        return {
            isMonitoring: this.isMonitoring,
            metricsCount: this.metrics.size,
            alertsCount: this.alerts.length,
            lastCollection: this.metrics.size > 0 ? 
                Math.max(...this.metrics.keys()) : null
        };
    }
}

module.exports = { PerformanceMonitor };

// CLI usage
if (require.main === module) {
    const monitor = new PerformanceMonitor({
        distributionId: process.env.CLOUDFRONT_DISTRIBUTION_ID,
        metricsInterval: 30000, // 30 seconds for testing
        reportInterval: 300000   // 5 minutes for testing
    });
    
    // Set up event listeners
    monitor.on('started', () => {
        console.log('✅ Monitoring started');
    });
    
    monitor.on('metricsCollected', (metrics) => {
        console.log(`📊 Metrics collected at ${new Date(metrics.timestamp).toLocaleTimeString()}`);
        
        if (metrics.cache) {
            console.log(`   Cache hit rate: ${metrics.cache.hitRate.toFixed(1)}%`);
        }
        
        if (metrics.endpoints) {
            const failed = metrics.endpoints.filter(e => !e.ok).length;
            console.log(`   Endpoints: ${metrics.endpoints.length - failed}/${metrics.endpoints.length} healthy`);
        }
    });
    
    monitor.on('alert', (alert) => {
        const emoji = alert.severity === 'critical' ? '🚨' : '⚠️';
        console.log(`${emoji} ALERT: ${alert.message}`);
    });
    
    monitor.on('healthCheck', (results) => {
        const emoji = results.overall === 'healthy' ? '✅' : 
                     results.overall === 'degraded' ? '⚠️' : '❌';
        console.log(`${emoji} Health check: ${results.overall}`);
    });
    
    monitor.on('reportGenerated', (report) => {
        console.log(`📈 Performance report generated`);
        console.log(`   Success rate: ${report.summary.successRate.toFixed(1)}%`);
        console.log(`   Avg response time: ${report.summary.averageResponseTime.toFixed(0)}ms`);
        console.log(`   Cache hit rate: ${report.summary.averageCacheHitRate.toFixed(1)}%`);
    });
    
    // Handle graceful shutdown
    process.on('SIGINT', () => {
        console.log('\n🛑 Shutting down monitor...');
        monitor.stop();
        process.exit(0);
    });
    
    process.on('SIGTERM', () => {
        console.log('\n🛑 Shutting down monitor...');
        monitor.stop();
        process.exit(0);
    });
    
    // Start monitoring
    monitor.start();
    
    console.log('Press Ctrl+C to stop monitoring');
}