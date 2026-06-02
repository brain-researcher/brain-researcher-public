const createNextIntlPlugin = require('next-intl/plugin');
const { BundleAnalyzerPlugin } = require('webpack-bundle-analyzer');

const withNextIntl = createNextIntlPlugin('./src/i18n/config.ts');

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Production optimizations
  poweredByHeader: false,
  generateEtags: false,
  compress: true,

  // Image optimization
  images: {
    domains: [
      'api.brain-researcher.com',
      'cdn.brain-researcher.com',
      'images.unsplash.com',
      'via.placeholder.com'
    ],
    formats: ['image/webp', 'image/avif'],
    deviceSizes: [640, 750, 828, 1080, 1200, 1920, 2048, 3840],
    imageSizes: [16, 32, 48, 64, 96, 128, 256, 384],
    minimumCacheTTL: 31536000, // 1 year
    dangerouslyAllowSVG: true,
    contentSecurityPolicy: "default-src 'self'; script-src 'none'; sandbox;",
  },

  // Experimental features for better performance
  experimental: {
    optimizeCss: true,
    scrollRestoration: true,
    legacyBrowsers: false,
    browsersListForSwc: true,
    newNextLinkBehavior: true,
    runtime: 'nodejs',
    serverComponentsExternalPackages: ['sharp'],
    turbo: {
      loaders: {
        '.svg': ['@svgr/webpack'],
      },
    },
  },

  // Compiler optimizations
  compiler: {
    removeConsole: process.env.NODE_ENV === 'production',
    reactRemoveProperties: process.env.NODE_ENV === 'production',
    styledComponents: true,
  },

  // SWC minification
  swcMinify: true,

  // Output configuration
  output: 'standalone',

  // Headers for security and performance
  async headers() {
    const securityHeaders = [
      {
        key: 'X-DNS-Prefetch-Control',
        value: 'on'
      },
      {
        key: 'Strict-Transport-Security',
        value: 'max-age=31536000; includeSubDomains; preload'
      },
      {
        key: 'X-Frame-Options',
        value: 'DENY'
      },
      {
        key: 'X-Content-Type-Options',
        value: 'nosniff'
      },
      {
        key: 'Referrer-Policy',
        value: 'strict-origin-when-cross-origin'
      },
      {
        key: 'Permissions-Policy',
        value: 'camera=(), microphone=(), geolocation=(), interest-cohort=()'
      },
      {
        key: 'Content-Security-Policy',
        value: [
          "default-src 'self'",
          "script-src 'self' 'unsafe-eval' 'unsafe-inline' https://cdn.jsdelivr.net",
          "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
          "font-src 'self' https://fonts.gstatic.com",
          "img-src 'self' data: blob: https:",
          "connect-src 'self' https://api.brain-researcher.com wss:",
          "frame-ancestors 'none'",
          "base-uri 'self'",
          "form-action 'self'",
          "upgrade-insecure-requests"
        ].join('; ')
      }
    ];

    return [
      // Security headers for all routes
      {
        source: '/(.*)',
        headers: securityHeaders
      },
      // Caching headers for static assets
      {
        source: '/static/(.*)',
        headers: [
          {
            key: 'Cache-Control',
            value: 'public, max-age=31536000, immutable'
          }
        ]
      },
      // Caching headers for Next.js assets
      {
        source: '/_next/static/(.*)',
        headers: [
          {
            key: 'Cache-Control',
            value: 'public, max-age=31536000, immutable'
          }
        ]
      },
      // API response headers
      {
        source: '/api/(.*)',
        headers: [
          {
            key: 'Cache-Control',
            value: 'public, max-age=300, stale-while-revalidate=60'
          },
          {
            key: 'Access-Control-Allow-Origin',
            value: '*'
          },
          {
            key: 'Access-Control-Allow-Methods',
            value: 'GET, POST, PUT, DELETE, OPTIONS'
          },
          {
            key: 'Access-Control-Allow-Headers',
            value: 'Content-Type, Authorization, X-Requested-With'
          }
        ]
      }
    ];
  },

  // Rewrites for API proxy
  async rewrites() {
    const baseUrl = (
      process.env.BR_ORCHESTRATOR_URL ||
      process.env.ORCHESTRATOR_BASE_URL ||
      process.env.ORCHESTRATOR_API ||
      process.env.ORCHESTRATOR_URL ||
      process.env.ORCHESTRATOR_API_URL ||
      'http://localhost:3001'
    ).replace(/\/$/, '');

    return [
      {
        source: '/api/dashboard/:path*',
        destination: `${baseUrl}/dashboard/:path*`,
      },
      {
        source: '/api/kg/:path*',
        destination: `${baseUrl}/kg/:path*`,
      },
      {
        source: '/api/viz/:path*',
        destination: `${baseUrl}/viz/:path*`,
      },
      {
        source: '/api/:path*',
        destination: `${baseUrl}/api/:path*`,
      },
      {
        source: '/run',
        destination: `${baseUrl}/run`,
      },
      {
        source: '/jobs/:path*',
        destination: `${baseUrl}/jobs/:path*`,
      },
    ];
  },

  // Redirects for SEO and UX
  async redirects() {
    return [
      {
        source: '/home',
        destination: '/',
        permanent: true
      },
      {
        source: '/dashboard',
        destination: '/knowledge-graph',
        permanent: false
      }
    ];
  },

  // Webpack configuration for advanced optimizations
  webpack: (config, { buildId, dev, isServer, defaultLoaders, webpack }) => {
    // Bundle analyzer in development
    if (process.env.ANALYZE === 'true') {
      config.plugins.push(
        new BundleAnalyzerPlugin({
          analyzerMode: 'static',
          openAnalyzer: false,
          reportFilename: isServer
            ? '../analyze/server.html'
            : './analyze/client.html'
        })
      );
    }

    // Optimize chunks
    if (!dev && !isServer) {
      config.optimization = {
        ...config.optimization,
        splitChunks: {
          chunks: 'all',
          cacheGroups: {
            // Vendor chunk for stable libraries
            vendor: {
              test: /[\\/]node_modules[\\/]/,
              name: 'vendors',
              chunks: 'all',
              enforce: true,
              priority: 20
            },
            // Common chunk for shared code
            common: {
              name: 'common',
              minChunks: 2,
              chunks: 'all',
              enforce: true,
              priority: 10
            },
            // UI components chunk
            ui: {
              test: /[\\/]src[\\/]components[\\/]ui[\\/]/,
              name: 'ui',
              chunks: 'all',
              enforce: true,
              priority: 15
            },
            // Utilities chunk
            utils: {
              test: /[\\/]src[\\/]lib[\\/]/,
              name: 'utils',
              chunks: 'all',
              enforce: true,
              priority: 12
            }
          }
        }
      };
    }

    // SVG handling
    config.module.rules.push({
      test: /\.svg$/,
      use: ['@svgr/webpack']
    });

    // WebAssembly support
    config.experiments = {
      ...config.experiments,
      asyncWebAssembly: true,
      layers: true
    };

    // Resolve fallbacks for browser compatibility
    config.resolve.fallback = {
      ...config.resolve.fallback,
      fs: false,
      path: false,
      crypto: false,
      stream: false,
      buffer: false
    };

    // Performance optimizations
    if (!dev) {
      // Tree shaking optimization
      config.optimization.usedExports = true;
      config.optimization.sideEffects = false;

      // Module concatenation
      config.optimization.concatenateModules = true;

      // Minimize CSS
      config.optimization.minimizer = [
        ...config.optimization.minimizer,
        new (require('css-minimizer-webpack-plugin'))()
      ];
    }

    // Load balancing for worker threads
    if (!isServer) {
      config.plugins.push(
        new webpack.IgnorePlugin({
          resourceRegExp: /^pg-native$/,
        })
      );
    }

    return config;
  },

  // Environment variables available to browser
  env: {
    NEXT_PUBLIC_BUILD_ID: process.env.BUILD_ID || 'development',
    NEXT_PUBLIC_VERSION: process.env.npm_package_version || '1.0.0'
  },

  // Development configuration
  ...(process.env.NODE_ENV === 'development' && {
    eslint: {
      dirs: ['src', 'pages', 'components']
    },
    typescript: {
      ignoreBuildErrors: false
    }
  })
};

module.exports = withNextIntl(nextConfig);
