/**
 * CloudFront Function: Security Headers
 * Adds security headers to Brain Researcher responses
 */

function handler(event) {
    var request = event.request;
    var headers = request.headers;

    // Add origin verification token check
    if (!headers['x-origin-verify'] ||
        headers['x-origin-verify'].value !== 'brain-researcher-verify-token-2024') {

        // Allow requests from known origins during development
        var allowedOrigins = [
            'localhost:3000',
            'localhost:3001',
            'brain-researcher.com',
            'www.brain-researcher.com',
            'app.brain-researcher.com'
        ];

        var host = headers.host ? headers.host.value : '';
        var isAllowedOrigin = allowedOrigins.some(function(origin) {
            return host.includes(origin);
        });

        if (!isAllowedOrigin) {
            return {
                statusCode: 403,
                statusDescription: 'Forbidden',
                headers: {
                    'content-type': { value: 'text/plain' }
                },
                body: 'Access denied'
            };
        }
    }

    // Add security headers to the request before forwarding to origin
    headers['x-forwarded-proto'] = { value: 'https' };
    headers['x-forwarded-port'] = { value: '443' };

    // Add rate limiting headers (basic implementation)
    var clientIP = event.viewer.ip;
    var timestamp = Math.floor(Date.now() / 1000);

    // Simple rate limiting based on IP (would need external storage in real implementation)
    headers['x-rate-limit-key'] = {
        value: clientIP + ':' + Math.floor(timestamp / 60) // Per minute window
    };

    return request;
}