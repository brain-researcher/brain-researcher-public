/**
 * Legacy compatibility shim.
 *
 * Keep this file as a thin alias to the canonical Next config so older local
 * workflows do not accidentally pick up a second, stale development routing
 * model.
 */

module.exports = require('./next.config.js')
