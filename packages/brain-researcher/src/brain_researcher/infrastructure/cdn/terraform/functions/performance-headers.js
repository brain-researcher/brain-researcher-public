/**
 * CloudFront Function: Performance Headers
 * Adds performance optimization headers to Brain Researcher responses
 */

function handler(event) {
    var response = event.response;
    var headers = response.headers;
    var request = event.request;
    var uri = request.uri;
    
    // Get file extension for cache optimization
    var extension = uri.split('.').pop().toLowerCase();
    
    // Set cache headers based on file type
    var staticAssets = ['js', 'css', 'png', 'jpg', 'jpeg', 'gif', 'svg', 'ico', 'woff', 'woff2', 'ttf', 'eot'];
    var longCacheAssets = ['woff', 'woff2', 'ttf', 'eot', 'png', 'jpg', 'jpeg', 'gif', 'svg', 'ico'];
    
    if (staticAssets.includes(extension)) {
        if (longCacheAssets.includes(extension)) {
            // Long cache for fonts and images (1 year)
            headers['cache-control'] = { value: 'public, max-age=31536000, immutable' };
        } else {
            // Medium cache for JS/CSS (1 week)
            headers['cache-control'] = { value: 'public, max-age=604800, stale-while-revalidate=86400' };
        }
        
        // Add compression hint
        if (['js', 'css', 'svg'].includes(extension)) {
            headers['vary'] = { value: 'Accept-Encoding' };
        }
    } else if (uri.startsWith('/api/')) {
        // API responses - short cache with revalidation
        headers['cache-control'] = { value: 'public, max-age=300, stale-while-revalidate=60' };
        headers['vary'] = { value: 'Accept-Encoding, Authorization' };
    } else if (uri === '/' || uri.endsWith('.html')) {
        // HTML pages - minimal cache with revalidation
        headers['cache-control'] = { value: 'public, max-age=0, must-revalidate' };
    }
    
    // Add performance headers
    headers['x-content-type-options'] = { value: 'nosniff' };
    headers['x-frame-options'] = { value: 'DENY' };
    headers['x-xss-protection'] = { value: '1; mode=block' };
    headers['referrer-policy'] = { value: 'strict-origin-when-cross-origin' };
    
    // Add resource hints for critical resources
    if (uri === '/' || uri === '/index.html') {
        headers['link'] = { 
            value: [
                '</static/css/main.css>; rel=preload; as=style',
                '</static/js/main.js>; rel=preload; as=script',
                '//fonts.googleapis.com; rel=preconnect; crossorigin',
                '//api.brain-researcher.com; rel=preconnect'
            ].join(', ')
        };
    }
    
    // Add timing headers for monitoring
    headers['server-timing'] = { 
        value: 'cf-cache;desc="' + (headers['x-cache'] ? headers['x-cache'].value : 'MISS') + '"'
    };
    
    // Enable CORS for API endpoints
    if (uri.startsWith('/api/')) {
        headers['access-control-allow-origin'] = { value: '*' };
        headers['access-control-allow-methods'] = { value: 'GET, POST, PUT, DELETE, OPTIONS' };
        headers['access-control-allow-headers'] = { value: 'Content-Type, Authorization, X-Requested-With' };
        headers['access-control-max-age'] = { value: '3600' };
    }
    
    // Add Progressive Web App headers
    if (uri === '/manifest.json') {
        headers['content-type'] = { value: 'application/manifest+json' };
        headers['cache-control'] = { value: 'public, max-age=3600' };
    }
    
    if (uri === '/sw.js' || uri === '/service-worker.js') {
        headers['content-type'] = { value: 'application/javascript' };
        headers['cache-control'] = { value: 'no-cache, no-store, must-revalidate' };
        headers['service-worker-allowed'] = { value: '/' };
    }
    
    return response;
}