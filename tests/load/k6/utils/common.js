/**
 * Common utilities and helpers for K6 load testing
 *
 * This module provides reusable functions for:
 * - HTTP client configuration
 * - Response validation
 * - Error handling
 * - Data generation
 * - Test coordination
 */

import { check, fail } from 'k6';
import { Rate, Counter, Trend, Gauge } from 'k6/metrics';

// Custom metrics for Brain Researcher specific monitoring
export const analysisRequestDuration = new Trend('analysis_request_duration', true);
export const websocketConnectionTime = new Trend('websocket_connection_time', true);
export const fileUploadDuration = new Trend('file_upload_duration', true);
export const autoScalingResponseTime = new Trend('auto_scaling_response_time', true);
export const errorRate = new Rate('custom_error_rate');
export const activeConnections = new Gauge('active_connections');
export const successfulRequests = new Counter('successful_requests');

/**
 * Get base configuration from environment variables
 */
export function getConfig() {
    return {
        baseUrl: __ENV.BASE_URL || 'http://localhost',
        authToken: __ENV.AUTH_TOKEN || '',
        environment: __ENV.K6_ENVIRONMENT || 'development',
        debug: __ENV.DEBUG === 'true',
        // Service-specific endpoints
        endpoints: {
            orchestrator: `${__ENV.BASE_URL || 'http://localhost'}/orchestrator`,
            brKg: `${__ENV.BASE_URL || 'http://localhost'}/br-kg`,
            agent: `${__ENV.BASE_URL || 'http://localhost'}/agent`,
            webui: `${__ENV.BASE_URL || 'http://localhost'}`,
            apiGateway: `${__ENV.BASE_URL || 'http://localhost'}/api`
        }
    };
}

/**
 * Standard HTTP client configuration
 */
export function getHttpConfig() {
    return {
        headers: {
            'Content-Type': 'application/json',
            'User-Agent': 'K6-LoadTest/1.0',
            'Authorization': `Bearer ${getConfig().authToken}`
        },
        timeout: '30s',
        responseType: 'json'
    };
}

/**
 * Validate HTTP response with comprehensive checks
 * @param {Object} response - HTTP response object
 * @param {Object} expectations - Expected response characteristics
 */
export function validateResponse(response, expectations = {}) {
    const {
        status = 200,
        maxDuration = 5000,
        contentType = 'application/json',
        minBodySize = 0,
        requiredFields = [],
        customValidations = []
    } = expectations;

    const checks = {
        [`status is ${status}`]: response.status === status,
        [`response time < ${maxDuration}ms`]: response.timings.duration < maxDuration,
        'response body exists': response.body && response.body.length > minBodySize
    };

    // Content type validation
    if (contentType) {
        checks[`content-type is ${contentType}`] =
            response.headers['Content-Type'] &&
            response.headers['Content-Type'].includes(contentType);
    }

    // Required fields validation for JSON responses
    if (requiredFields.length > 0 && response.json) {
        const json = response.json();
        requiredFields.forEach(field => {
            checks[`has required field: ${field}`] = json.hasOwnProperty(field);
        });
    }

    // Custom validations
    customValidations.forEach((validation, index) => {
        checks[`custom validation ${index + 1}`] = validation(response);
    });

    const success = check(response, checks);

    // Update custom metrics
    if (success) {
        successfulRequests.add(1);
    } else {
        errorRate.add(1);
        if (getConfig().debug) {
            console.error(`Response validation failed:`, {
                url: response.url,
                status: response.status,
                duration: response.timings.duration,
                body: response.body.substring(0, 500)
            });
        }
    }

    return success;
}

/**
 * Generate realistic test data for Brain Researcher
 */
export class DataGenerator {
    /**
     * Generate random user profile
     */
    static generateUser() {
        const firstNames = ['Alice', 'Bob', 'Carol', 'David', 'Eve', 'Frank', 'Grace', 'Henry'];
        const lastNames = ['Smith', 'Johnson', 'Williams', 'Brown', 'Jones', 'Garcia', 'Miller', 'Davis'];
        const institutions = ['MIT', 'Stanford', 'Harvard', 'Oxford', 'Cambridge', 'ETH Zurich'];

        const firstName = firstNames[Math.floor(Math.random() * firstNames.length)];
        const lastName = lastNames[Math.floor(Math.random() * lastNames.length)];

        return {
            id: `user_${Date.now()}_${Math.floor(Math.random() * 10000)}`,
            email: `${firstName.toLowerCase()}.${lastName.toLowerCase()}@example.com`,
            name: `${firstName} ${lastName}`,
            institution: institutions[Math.floor(Math.random() * institutions.length)],
            role: Math.random() > 0.7 ? 'admin' : 'researcher'
        };
    }

    /**
     * Generate neuroimaging analysis request
     */
    static generateAnalysisRequest() {
        const analysisTypes = [
            'GLM', 'ICA', 'SVM', 'connectivity_analysis',
            'meta_analysis', 'decoding', 'encoding'
        ];

        const datasets = [
            'ds000001', 'ds000002', 'ds000114', 'ds000228',
            'HCP_1200', 'ABCD_Year1', 'OASIS3'
        ];

        return {
            analysis_type: analysisTypes[Math.floor(Math.random() * analysisTypes.length)],
            dataset: datasets[Math.floor(Math.random() * datasets.length)],
            parameters: {
                smoothing_fwhm: Math.floor(Math.random() * 8) + 4, // 4-12mm
                high_pass_filter: Math.random() * 0.01, // 0-0.01 Hz
                tr: Math.random() * 2 + 1, // 1-3 seconds
                n_subjects: Math.floor(Math.random() * 100) + 10 // 10-110 subjects
            },
            priority: Math.random() > 0.8 ? 'high' : 'normal',
            estimated_duration: Math.floor(Math.random() * 3600) + 300 // 5-65 minutes
        };
    }

    /**
     * Generate knowledge graph query
     */
    static generateKnowledgeGraphQuery() {
        const queryTypes = ['spatial', 'semantic', 'hybrid', 'text_search'];
        const terms = [
            'working memory', 'attention', 'emotion', 'language',
            'motor control', 'visual cortex', 'prefrontal cortex',
            'amygdala', 'hippocampus', 'default mode network'
        ];

        const queryType = queryTypes[Math.floor(Math.random() * queryTypes.length)];
        const term = terms[Math.floor(Math.random() * terms.length)];

        return {
            query_type: queryType,
            search_term: term,
            filters: {
                min_subjects: Math.floor(Math.random() * 20) + 5,
                modality: Math.random() > 0.5 ? 'fMRI' : 'any',
                year_range: {
                    start: 2010 + Math.floor(Math.random() * 10),
                    end: 2023
                }
            },
            limit: Math.floor(Math.random() * 100) + 10 // 10-110 results
        };
    }

    /**
     * Generate file upload data
     */
    static generateFileUpload() {
        const fileTypes = ['nifti', 'json', 'csv', 'tsv', 'mat'];
        const fileSizes = {
            'nifti': Math.floor(Math.random() * 100) + 10, // 10-110 MB
            'json': Math.floor(Math.random() * 10) + 1,   // 1-11 MB
            'csv': Math.floor(Math.random() * 50) + 5,    // 5-55 MB
            'tsv': Math.floor(Math.random() * 30) + 2,    // 2-32 MB
            'mat': Math.floor(Math.random() * 200) + 20   // 20-220 MB
        };

        const fileType = fileTypes[Math.floor(Math.random() * fileTypes.length)];

        return {
            filename: `test_data_${Date.now()}.${fileType}`,
            file_type: fileType,
            size_mb: fileSizes[fileType],
            description: `Generated test file for load testing`,
            metadata: {
                created: new Date().toISOString(),
                source: 'k6_load_test',
                version: '1.0'
            }
        };
    }
}

/**
 * Sleep with random jitter to simulate realistic user behavior
 * @param {number} baseSeconds - Base sleep time in seconds
 * @param {number} jitterPercent - Jitter percentage (0-100)
 */
export function sleepWithJitter(baseSeconds, jitterPercent = 20) {
    const jitter = (Math.random() - 0.5) * 2 * (jitterPercent / 100);
    const sleepTime = baseSeconds * (1 + jitter);

    // Import sleep here to avoid circular dependencies
    const { sleep } = require('k6');
    sleep(Math.max(0.1, sleepTime)); // Minimum 0.1 seconds
}

/**
 * Retry mechanism for flaky operations
 * @param {Function} operation - Operation to retry
 * @param {number} maxRetries - Maximum number of retries
 * @param {number} delaySeconds - Delay between retries
 */
export async function retry(operation, maxRetries = 3, delaySeconds = 1) {
    let lastError;

    for (let attempt = 1; attempt <= maxRetries; attempt++) {
        try {
            return await operation();
        } catch (error) {
            lastError = error;

            if (attempt === maxRetries) {
                throw error;
            }

            if (getConfig().debug) {
                console.warn(`Attempt ${attempt} failed, retrying in ${delaySeconds}s:`, error.message);
            }

            sleepWithJitter(delaySeconds);
        }
    }

    throw lastError;
}

/**
 * Load balancer health check
 * @param {string} baseUrl - Base URL to check
 */
export function healthCheck(baseUrl) {
    const { http } = require('k6/http');

    const endpoints = [
        `${baseUrl}/health`,
        `${baseUrl}/api/health`,
        `${baseUrl}/orchestrator/health`,
        `${baseUrl}/br-kg/health`
    ];

    const healthResults = {};

    endpoints.forEach(endpoint => {
        try {
            const response = http.get(endpoint, {
                timeout: '10s',
                headers: { 'User-Agent': 'K6-HealthCheck/1.0' }
            });

            healthResults[endpoint] = {
                status: response.status,
                responseTime: response.timings.duration,
                healthy: response.status === 200
            };

        } catch (error) {
            healthResults[endpoint] = {
                status: 0,
                responseTime: 0,
                healthy: false,
                error: error.message
            };
        }
    });

    return healthResults;
}

/**
 * Monitor auto-scaling behavior
 * @param {string} baseUrl - Base URL for monitoring
 * @param {number} durationSeconds - How long to monitor
 */
export function monitorAutoScaling(baseUrl, durationSeconds = 60) {
    const { http } = require('k6/http');
    const startTime = Date.now();
    const measurements = [];

    while ((Date.now() - startTime) / 1000 < durationSeconds) {
        try {
            const response = http.get(`${baseUrl}/api/metrics/scaling`, {
                headers: getHttpConfig().headers,
                timeout: '5s'
            });

            if (response.status === 200 && response.json) {
                const metrics = response.json();
                measurements.push({
                    timestamp: Date.now(),
                    replicas: metrics.replicas || {},
                    cpu_usage: metrics.cpu_usage || {},
                    memory_usage: metrics.memory_usage || {},
                    response_time: response.timings.duration
                });
            }
        } catch (error) {
            if (getConfig().debug) {
                console.warn('Auto-scaling monitoring error:', error.message);
            }
        }

        sleepWithJitter(5); // Check every ~5 seconds
    }

    return measurements;
}

/**
 * Simulate realistic user session patterns
 */
export class UserSession {
    constructor() {
        this.user = DataGenerator.generateUser();
        this.sessionId = `session_${Date.now()}_${Math.floor(Math.random() * 10000)}`;
        this.startTime = Date.now();
        this.authenticated = false;
    }

    /**
     * Authenticate user session
     */
    authenticate() {
        const { http } = require('k6/http');
        const config = getConfig();

        const loginData = {
            email: this.user.email,
            password: 'test_password_123'
        };

        const response = http.post(
            `${config.endpoints.apiGateway}/auth/login`,
            JSON.stringify(loginData),
            getHttpConfig()
        );

        const success = validateResponse(response, {
            status: 200,
            requiredFields: ['token', 'user']
        });

        if (success && response.json) {
            this.authToken = response.json().token;
            this.authenticated = true;
        }

        return success;
    }

    /**
     * Perform typical research workflow
     */
    researchWorkflow() {
        if (!this.authenticated) {
            throw new Error('User must be authenticated before workflow');
        }

        const { http } = require('k6/http');
        const config = getConfig();
        const httpConfig = {
            ...getHttpConfig(),
            headers: {
                ...getHttpConfig().headers,
                'Authorization': `Bearer ${this.authToken}`
            }
        };

        const workflow = [];

        // Step 1: Browse available datasets
        let response = http.get(`${config.endpoints.brKg}/datasets`, httpConfig);
        workflow.push({
            step: 'browse_datasets',
            success: validateResponse(response, { maxDuration: 2000 })
        });
        sleepWithJitter(3);

        // Step 2: Search for specific studies
        const query = DataGenerator.generateKnowledgeGraphQuery();
        response = http.post(
            `${config.endpoints.brKg}/search`,
            JSON.stringify(query),
            httpConfig
        );
        workflow.push({
            step: 'search_studies',
            success: validateResponse(response, { maxDuration: 5000 })
        });
        sleepWithJitter(5);

        // Step 3: Submit analysis request
        const analysisRequest = DataGenerator.generateAnalysisRequest();
        const analysisStart = Date.now();

        response = http.post(
            `${config.endpoints.orchestrator}/analysis`,
            JSON.stringify(analysisRequest),
            httpConfig
        );

        const analysisSubmitSuccess = validateResponse(response, {
            status: 202, // Accepted
            requiredFields: ['job_id', 'status']
        });

        workflow.push({
            step: 'submit_analysis',
            success: analysisSubmitSuccess
        });

        if (analysisSubmitSuccess && response.json) {
            const jobId = response.json().job_id;

            // Step 4: Monitor analysis progress
            let analysisComplete = false;
            let attempts = 0;
            const maxAttempts = 10;

            while (!analysisComplete && attempts < maxAttempts) {
                sleepWithJitter(10); // Wait between checks
                attempts++;

                response = http.get(
                    `${config.endpoints.orchestrator}/analysis/${jobId}/status`,
                    httpConfig
                );

                if (validateResponse(response) && response.json) {
                    const status = response.json().status;
                    analysisComplete = ['completed', 'failed', 'cancelled'].includes(status);

                    if (status === 'completed') {
                        const analysisDuration = Date.now() - analysisStart;
                        analysisRequestDuration.add(analysisDuration);
                    }
                }
            }

            workflow.push({
                step: 'monitor_analysis',
                success: analysisComplete,
                attempts: attempts
            });
        }

        sleepWithJitter(2);
        return workflow;
    }

    /**
     * Get session duration
     */
    getSessionDuration() {
        return Date.now() - this.startTime;
    }
}

/**
 * Performance threshold validator
 */
export class PerformanceValidator {
    constructor() {
        this.measurements = [];
    }

    /**
     * Add measurement
     */
    addMeasurement(metric, value, timestamp = Date.now()) {
        this.measurements.push({
            metric,
            value,
            timestamp
        });
    }

    /**
     * Validate SLA thresholds
     */
    validateSLA(thresholds) {
        const results = {};

        Object.keys(thresholds).forEach(metric => {
            const measurements = this.measurements
                .filter(m => m.metric === metric)
                .map(m => m.value);

            if (measurements.length === 0) {
                results[metric] = { passed: false, reason: 'No measurements available' };
                return;
            }

            const threshold = thresholds[metric];
            let passed = false;
            let actualValue;

            // Parse threshold (e.g., 'p(95)<500', 'rate<0.01')
            if (threshold.includes('p(')) {
                const percentileMatch = threshold.match(/p\((\d+)\)<(.+)/);
                if (percentileMatch) {
                    const percentile = parseInt(percentileMatch[1]);
                    const limit = parseFloat(percentileMatch[2]);

                    measurements.sort((a, b) => a - b);
                    const index = Math.floor((percentile / 100) * measurements.length);
                    actualValue = measurements[Math.min(index, measurements.length - 1)];

                    passed = actualValue < limit;
                }
            } else if (threshold.includes('rate<')) {
                const limit = parseFloat(threshold.split('rate<')[1]);
                actualValue = measurements.reduce((sum, val) => sum + val, 0) / measurements.length;
                passed = actualValue < limit;
            } else if (threshold.includes('avg<')) {
                const limit = parseFloat(threshold.split('avg<')[1]);
                actualValue = measurements.reduce((sum, val) => sum + val, 0) / measurements.length;
                passed = actualValue < limit;
            }

            results[metric] = {
                passed,
                actualValue,
                threshold,
                measurementCount: measurements.length
            };
        });

        return results;
    }
}