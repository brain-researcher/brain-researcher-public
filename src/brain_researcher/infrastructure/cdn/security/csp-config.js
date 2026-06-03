/**
 * Content Security Policy Configuration for Brain Researcher
 * Implements defense-in-depth security with progressive enhancement
 */

class CSPConfig {
    constructor(environment = 'production') {
        this.environment = environment;
        this.nonce = this.generateNonce();
        this.reportUri = process.env.CSP_REPORT_URI || '/api/csp-report';

        // Base domains for different environments
        this.domains = {
            development: {
                app: ['localhost:3000', '127.0.0.1:3000'],
                api: ['localhost:3001', '127.0.0.1:3001', 'localhost:5000'],
                cdn: ['localhost:3000'],
                websocket: ['ws://localhost:3001', 'wss://localhost:3001']
            },
            staging: {
                app: ['staging.${PUBLIC_HOSTNAME}'],
                api: ['api-staging.${PUBLIC_HOSTNAME}'],
                cdn: ['cdn-staging.${PUBLIC_HOSTNAME}'],
                websocket: ['wss://api-staging.${PUBLIC_HOSTNAME}']
            },
            production: {
                app: ['${PUBLIC_HOSTNAME}', 'www.${PUBLIC_HOSTNAME}'],
                api: ['api.${PUBLIC_HOSTNAME}'],
                cdn: ['cdn.${PUBLIC_HOSTNAME}', '*.cloudfront.net'],
                websocket: ['wss://api.${PUBLIC_HOSTNAME}']
            }
        };
    }

    /**
     * Generate cryptographically secure nonce
     */
    generateNonce() {
        const crypto = require('crypto');
        return crypto.randomBytes(16).toString('base64');
    }

    /**
     * Get domains for current environment
     */
    getCurrentDomains() {
        return this.domains[this.environment] || this.domains.production;
    }

    /**
     * Build Content Security Policy header
     */
    buildCSP(options = {}) {
        const {
            enableUnsafeInline = false,
            enableUnsafeEval = false,
            reportOnly = false,
            customDirectives = {}
        } = options;

        const domains = this.getCurrentDomains();

        // Base CSP directives
        const directives = {
            'default-src': ["'self'", ...domains.app],

            'script-src': [
                "'self'",
                `'nonce-${this.nonce}'`,
                ...domains.app,
                ...domains.cdn,
                'https://cdn.jsdelivr.net',
                'https://unpkg.com',
                ...(enableUnsafeEval ? ["'unsafe-eval'"] : []),
                ...(enableUnsafeInline && this.environment === 'development' ? ["'unsafe-inline'"] : [])
            ],

            'style-src': [
                "'self'",
                "'unsafe-inline'", // Required for CSS-in-JS and dynamic styles
                ...domains.app,
                ...domains.cdn,
                'https://fonts.googleapis.com'
            ],

            'img-src': [
                "'self'",
                'data:',
                'blob:',
                'https:',
                ...domains.app,
                ...domains.api,
                ...domains.cdn,
                'https://images.unsplash.com',
                'https://via.placeholder.com'
            ],

            'font-src': [
                "'self'",
                'data:',
                ...domains.cdn,
                'https://fonts.gstatic.com'
            ],

            'connect-src': [
                "'self'",
                ...domains.app,
                ...domains.api,
                ...domains.websocket,
                'https://api.openai.com',
                'https://api.anthropic.com',
                ...(this.environment === 'development' ? ['ws:', 'wss:'] : [])
            ],

            'media-src': [
                "'self'",
                'data:',
                'blob:',
                ...domains.cdn
            ],

            'object-src': ["'none'"],

            'frame-src': [
                "'self'",
                'https://www.youtube.com',
                'https://player.vimeo.com'
            ],

            'frame-ancestors': ["'none'"],

            'base-uri': ["'self'"],

            'form-action': [
                "'self'",
                ...domains.api
            ],

            'manifest-src': ["'self'"],

            'worker-src': [
                "'self'",
                'blob:'
            ],

            'upgrade-insecure-requests': [],

            ...(this.reportUri ? { 'report-uri': [this.reportUri] } : {}),

            // Custom directives override defaults
            ...customDirectives
        };

        // Development environment relaxations
        if (this.environment === 'development') {
            directives['script-src'].push("'unsafe-eval'"); // For hot reload
            directives['connect-src'].push('ws://localhost:*', 'http://localhost:*');
        }

        // Build CSP string
        const cspString = Object.entries(directives)
            .map(([directive, sources]) => {
                if (sources.length === 0) {
                    return directive;
                }
                return `${directive} ${sources.join(' ')}`;
            })
            .join('; ');

        return {
            headerName: reportOnly ? 'Content-Security-Policy-Report-Only' : 'Content-Security-Policy',
            headerValue: cspString,
            nonce: this.nonce
        };
    }

    /**
     * Get security headers for HTTP responses
     */
    getSecurityHeaders(options = {}) {
        const csp = this.buildCSP(options);

        const headers = {
            // Content Security Policy
            [csp.headerName]: csp.headerValue,

            // Strict Transport Security
            'Strict-Transport-Security': 'max-age=31536000; includeSubDomains; preload',

            // Frame Options
            'X-Frame-Options': 'DENY',

            // Content Type Options
            'X-Content-Type-Options': 'nosniff',

            // XSS Protection (legacy browsers)
            'X-XSS-Protection': '1; mode=block',

            // Referrer Policy
            'Referrer-Policy': 'strict-origin-when-cross-origin',

            // Permissions Policy
            'Permissions-Policy': [
                'camera=()',
                'microphone=()',
                'geolocation=()',
                'interest-cohort=()',
                'payment=()',
                'usb=()',
                'magnetometer=()',
                'gyroscope=()'
            ].join(', '),

            // Cross-Origin Policies
            'Cross-Origin-Embedder-Policy': 'credentialless',
            'Cross-Origin-Opener-Policy': 'same-origin',
            'Cross-Origin-Resource-Policy': 'same-origin'
        };

        return headers;
    }

    /**
     * Express middleware for security headers
     */
    expressMiddleware(options = {}) {
        const headers = this.getSecurityHeaders(options);

        return (req, res, next) => {
            // Set security headers
            Object.entries(headers).forEach(([name, value]) => {
                res.setHeader(name, value);
            });

            // Add nonce to response locals for template access
            res.locals.nonce = this.nonce;

            next();
        };
    }

    /**
     * Next.js headers configuration
     */
    nextHeaders() {
        const headers = this.getSecurityHeaders();

        return Object.entries(headers).map(([key, value]) => ({
            key,
            value
        }));
    }

    /**
     * Nginx configuration for security headers
     */
    nginxConfig() {
        const headers = this.getSecurityHeaders();

        const nginxDirectives = Object.entries(headers)
            .map(([name, value]) => `add_header ${name} "${value}" always;`)
            .join('\n    ');

        return `
# Security Headers Configuration
location / {
    ${nginxDirectives}
}

# Additional security for API endpoints
location /api/ {
    ${nginxDirectives}
    add_header X-API-Version "1.0" always;
    add_header X-Rate-Limit-Remaining "$rate_limit_remaining" always;
}

# Security for static assets
location ~* \.(js|css|png|jpg|jpeg|gif|svg|ico|woff|woff2|ttf|eot)$ {
    add_header Cache-Control "public, max-age=31536000, immutable" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Access-Control-Allow-Origin "*" always;
}`;
    }

    /**
     * CloudFront response headers policy JSON
     */
    cloudFrontPolicy() {
        const headers = this.getSecurityHeaders();

        return {
            ResponseHeadersPolicyConfig: {
                Name: "BrainResearcher-SecurityHeaders",
                Comment: "Security headers for Brain Researcher application",
                SecurityHeadersConfig: {
                    StrictTransportSecurity: {
                        AccessControlMaxAgeSec: 31536000,
                        IncludeSubdomains: true,
                        Preload: true
                    },
                    ContentTypeOptions: {
                        Override: true
                    },
                    FrameOptions: {
                        FrameOption: "DENY",
                        Override: true
                    },
                    ReferrerPolicy: {
                        ReferrerPolicy: "strict-origin-when-cross-origin",
                        Override: true
                    }
                },
                CustomHeadersConfig: {
                    Items: Object.entries(headers)
                        .filter(([name]) => !name.startsWith('Strict-Transport') &&
                                           !name.startsWith('X-Frame') &&
                                           !name.startsWith('X-Content-Type') &&
                                           !name.startsWith('Referrer-Policy'))
                        .map(([name, value]) => ({
                            Header: name,
                            Value: value,
                            Override: false
                        }))
                }
            }
        };
    }

    /**
     * Validate CSP implementation
     */
    async validateCSP(url) {
        try {
            const response = await fetch(url);
            const cspHeader = response.headers.get('Content-Security-Policy');

            if (!cspHeader) {
                return {
                    valid: false,
                    error: 'No CSP header found'
                };
            }

            // Basic validation
            const requiredDirectives = ['default-src', 'script-src', 'style-src', 'img-src'];
            const presentDirectives = cspHeader.split(';').map(d => d.trim().split(' ')[0]);

            const missingDirectives = requiredDirectives.filter(
                directive => !presentDirectives.includes(directive)
            );

            return {
                valid: missingDirectives.length === 0,
                header: cspHeader,
                missingDirectives,
                presentDirectives
            };

        } catch (error) {
            return {
                valid: false,
                error: error.message
            };
        }
    }

    /**
     * Generate CSP report handler
     */
    cspReportHandler() {
        return (req, res) => {
            const report = req.body;

            // Log CSP violation
            console.warn('CSP Violation:', {
                documentURI: report['document-uri'],
                violatedDirective: report['violated-directive'],
                blockedURI: report['blocked-uri'],
                lineNumber: report['line-number'],
                sourceFile: report['source-file'],
                timestamp: new Date().toISOString()
            });

            // Store violation for analysis (implement based on your logging system)
            // await storeCSPViolation(report);

            res.status(204).end();
        };
    }
}

module.exports = { CSPConfig };

// Example usage
if (require.main === module) {
    const environment = process.argv[2] || 'production';
    const cspConfig = new CSPConfig(environment);

    console.log('CSP Configuration for', environment);
    console.log('='.repeat(50));

    const csp = cspConfig.buildCSP();
    console.log('\nCSP Header:');
    console.log(csp.headerValue);

    console.log('\nAll Security Headers:');
    const headers = cspConfig.getSecurityHeaders();
    Object.entries(headers).forEach(([name, value]) => {
        console.log(`${name}: ${value}`);
    });

    console.log('\nNginx Configuration:');
    console.log(cspConfig.nginxConfig());
}