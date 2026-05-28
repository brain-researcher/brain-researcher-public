/**
 * Legacy compatibility shim.
 *
 * Historical scripts sometimes referenced a "simple" Next config, but the
 * dedicated file drifted away from the real app routing and service ownership.
 * Re-export the canonical config instead of maintaining a second copy.
 */

module.exports = require('./next.config.js')
