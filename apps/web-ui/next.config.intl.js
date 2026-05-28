// Minimal config - only next-intl, no PWA/Analyzer/optimizePackageImports
const createNextIntlPlugin = require('next-intl/plugin');
const withNextIntl = createNextIntlPlugin('./src/i18n/request.ts');

module.exports = withNextIntl({
  reactStrictMode: true,
  experimental: {}, // Disable all experimental features
});