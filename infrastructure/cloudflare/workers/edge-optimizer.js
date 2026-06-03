/**
 * Cloudflare Worker for Brain Researcher Edge Optimization
 * Handles caching, image optimization, and API acceleration
 */

// Cache configuration
const CACHE_CONFIG = {
  static: {
    ttl: 31536000, // 1 year for static assets
    patterns: [/\/_next\/static\//, /\.(?:js|css|woff2?|ttf|otf)$/]
  },
  images: {
    ttl: 2592000, // 30 days for images
    patterns: [/\.(?:jpg|jpeg|png|gif|webp|svg|ico)$/]
  },
  api: {
    ttl: 300, // 5 minutes for API responses
    patterns: [/\/api\/datasets\//, /\/api\/search\//]
  },
  nifti: {
    ttl: 86400, // 1 day for brain imaging data
    patterns: [/\.(?:nii|nii\.gz)$/]
  }
};

// Security headers
const SECURITY_HEADERS = {
  'X-Frame-Options': 'SAMEORIGIN',
  'X-Content-Type-Options': 'nosniff',
  'X-XSS-Protection': '1; mode=block',
  'Referrer-Policy': 'strict-origin-when-cross-origin',
  'Permissions-Policy': 'camera=(), microphone=(), geolocation=()',
  'Content-Security-Policy': "default-src 'self'; script-src 'self' 'unsafe-eval' 'unsafe-inline' https://cdn.jsdelivr.net; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob: https:; connect-src 'self' wss: https:; worker-src 'self' blob:;"
};

// Main request handler
addEventListener('fetch', event => {
  event.respondWith(handleRequest(event.request, event));
});

async function handleRequest(request, event) {
  const url = new URL(request.url);
  
  // Handle CORS preflight
  if (request.method === 'OPTIONS') {
    return handleCORS(request);
  }
  
  // Check cache first
  const cacheKey = new Request(url.toString(), request);
  const cache = caches.default;
  
  let response = await cache.match(cacheKey);
  
  if (!response) {
    // Apply optimizations based on content type
    if (isImageRequest(url.pathname)) {
      response = await handleImageRequest(request, url);
    } else if (isAPIRequest(url.pathname)) {
      response = await handleAPIRequest(request, url, event);
    } else if (isStaticAsset(url.pathname)) {
      response = await handleStaticRequest(request, url);
    } else {
      response = await fetch(request);
    }
    
    // Cache the response if applicable
    response = await cacheResponse(request, response, cache, cacheKey);
  }
  
  // Add security headers
  response = addSecurityHeaders(response);
  
  return response;
}

// Image optimization handler
async function handleImageRequest(request, url) {
  const accept = request.headers.get('Accept') || '';
  const cf = request.cf || {};
  
  // Cloudflare image resizing options
  const options = {
    cf: {
      image: {
        fit: 'scale-down',
        quality: 85,
        format: 'auto', // Auto WebP/AVIF conversion
        dpr: cf.deviceType === 'mobile' ? 2 : 1
      },
      cacheEverything: true,
      cacheTtl: CACHE_CONFIG.images.ttl
    }
  };
  
  // Add responsive image sizing based on viewport hints
  const viewport = request.headers.get('Viewport-Width');
  if (viewport) {
    options.cf.image.width = Math.min(parseInt(viewport), 2048);
  }
  
  return fetch(request, options);
}

// API request handler with caching
async function handleAPIRequest(request, url, event) {
  const cacheKey = `api:${url.pathname}${url.search}`;
  
  // Check KV store for cached API responses
  if (typeof CACHE !== 'undefined') {
    const cached = await CACHE.get(cacheKey);
    if (cached) {
      return new Response(cached, {
        headers: {
          'Content-Type': 'application/json',
          'X-Cache': 'HIT',
          'Cache-Control': `public, max-age=${CACHE_CONFIG.api.ttl}`
        }
      });
    }
  }
  
  // Fetch from origin
  const response = await fetch(request);
  
  // Cache successful responses
  if (response.ok && typeof CACHE !== 'undefined') {
    const body = await response.text();
    event.waitUntil(
      CACHE.put(cacheKey, body, { expirationTtl: CACHE_CONFIG.api.ttl })
    );
    
    return new Response(body, {
      headers: {
        ...response.headers,
        'X-Cache': 'MISS',
        'Cache-Control': `public, max-age=${CACHE_CONFIG.api.ttl}`
      }
    });
  }
  
  return response;
}

// Static asset handler
async function handleStaticRequest(request, url) {
  const response = await fetch(request, {
    cf: {
      cacheEverything: true,
      cacheTtl: CACHE_CONFIG.static.ttl
    }
  });
  
  // Add immutable cache header for versioned assets
  if (url.pathname.includes('/_next/static/')) {
    const headers = new Headers(response.headers);
    headers.set('Cache-Control', `public, max-age=${CACHE_CONFIG.static.ttl}, immutable`);
    return new Response(response.body, {
      status: response.status,
      headers
    });
  }
  
  return response;
}

// Cache response helper
async function cacheResponse(request, response, cache, cacheKey) {
  if (!response.ok) return response;
  
  const url = new URL(request.url);
  let cacheTtl = 0;
  
  // Determine cache TTL based on content type
  for (const [type, config] of Object.entries(CACHE_CONFIG)) {
    if (config.patterns.some(pattern => pattern.test(url.pathname))) {
      cacheTtl = config.ttl;
      break;
    }
  }
  
  if (cacheTtl > 0) {
    const headers = new Headers(response.headers);
    headers.set('Cache-Control', `public, max-age=${cacheTtl}`);
    
    const cachedResponse = new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers
    });
    
    // Store in cache
    cache.put(cacheKey, cachedResponse.clone());
    
    return cachedResponse;
  }
  
  return response;
}

// Add security headers
function addSecurityHeaders(response) {
  const headers = new Headers(response.headers);
  
  Object.entries(SECURITY_HEADERS).forEach(([key, value]) => {
    headers.set(key, value);
  });
  
  return new Response(response.body, {
    status: response.status,
    statusText: response.statusText,
    headers
  });
}

// CORS handler
function handleCORS(request) {
  const headers = {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, PUT, DELETE, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type, Authorization',
    'Access-Control-Max-Age': '86400'
  };
  
  return new Response(null, {
    status: 204,
    headers
  });
}

// Helper functions
function isImageRequest(pathname) {
  return CACHE_CONFIG.images.patterns.some(pattern => pattern.test(pathname));
}

function isAPIRequest(pathname) {
  return CACHE_CONFIG.api.patterns.some(pattern => pattern.test(pathname));
}

function isStaticAsset(pathname) {
  return CACHE_CONFIG.static.patterns.some(pattern => pattern.test(pathname));
}

// Cache warming (scheduled)
addEventListener('scheduled', event => {
  event.waitUntil(warmCache());
});

async function warmCache() {
  const urlsToWarm = [
    '/',
    '/datasets',
    '/analysis',
    '/api/datasets',
    '/_next/static/chunks/main.js',
    '/_next/static/chunks/framework.js'
  ];
  
  const promises = urlsToWarm.map(url => 
    fetch(`https://${PUBLIC_HOSTNAME}${url}`)
  );
  
  await Promise.all(promises);
}