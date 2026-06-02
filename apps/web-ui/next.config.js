const createNextIntlPlugin = require('next-intl/plugin')

const withNextIntl = createNextIntlPlugin()

// Ensure the web UI shares the same auth secrets as python services when running in a monorepo.
// Next.js only loads .env* files from this app directory by default, but the repo root holds
// shared vars like JWT_SECRET_KEY. Load them here (dev/test) so middleware + NextAuth agree.
const fs = require('node:fs')
const path = require('node:path')

const loadRepoRootEnv = () => {
  if (process.env.NODE_ENV === 'production') return
  if (process.env.JWT_SECRET_KEY) return

  const repoRoot = path.resolve(__dirname, '../../..')
  for (const filename of ['.env.local', '.env']) {
    const filepath = path.join(repoRoot, filename)
    if (!fs.existsSync(filepath)) continue
    try {
      const content = fs.readFileSync(filepath, 'utf8')
      for (const rawLine of content.split(/\r?\n/)) {
        const line = rawLine.trim()
        if (!line || line.startsWith('#')) continue
        const eq = line.indexOf('=')
        if (eq <= 0) continue
        const key = line.slice(0, eq).trim()
        if (!key || process.env[key] != null) continue
        let value = line.slice(eq + 1).trim()
        if (
          (value.startsWith('"') && value.endsWith('"')) ||
          (value.startsWith("'") && value.endsWith("'"))
        ) {
          value = value.slice(1, -1)
        }
        process.env[key] = value
      }
    } catch {
      // Ignore dotenv read/parse errors; env vars can still be provided explicitly.
    }
  }
}

loadRepoRootEnv()

const normalizeBaseUrl = (value) => {
  if (!value || !String(value).trim()) return null
  try {
    const parsed = new URL(String(value).trim())
    return `${parsed.protocol}//${parsed.host}`.replace(/\/$/, '')
  } catch {
    return null
  }
}

const resolveServerBaseUrl = (candidates, fallbackHost, fallbackPort) => {
  for (const candidate of candidates) {
    const normalized = normalizeBaseUrl(candidate)
    if (normalized) return normalized
  }
  return `http://${fallbackHost}:${fallbackPort}`
}

// Service configuration from environment variables
const ORCHESTRATOR_HOST = process.env.ORCHESTRATOR_HOST || 'localhost'
// Legacy fallback retained for backwards compat; prefer dedicated Orchestrator port.
const ORCHESTRATOR_PORT = process.env.ORCHESTRATOR_PORT || process.env.AGENT_PORT || '3001'
const AGENT_HOST = process.env.AGENT_HOST || 'localhost'
const AGENT_PORT = process.env.AGENT_PORT || '8000'
const BR_KG_HOST = process.env.BR_KG_HOST || 'localhost'
const BR_KG_PORT = process.env.BR_KG_PORT || '5000'
const ORCHESTRATOR_BASE_URL = resolveServerBaseUrl(
  [
    process.env.BR_ORCHESTRATOR_URL,
    process.env.ORCHESTRATOR_BASE_URL,
    process.env.ORCHESTRATOR_API,
    process.env.ORCHESTRATOR_URL,
    process.env.ORCHESTRATOR_API_URL,
  ],
  ORCHESTRATOR_HOST,
  ORCHESTRATOR_PORT
)
const AGENT_BASE_URL = resolveServerBaseUrl(
  [
    process.env.BR_AGENT_URL,
    process.env.AGENT_BASE_URL,
    process.env.AGENT_URL,
  ],
  AGENT_HOST,
  AGENT_PORT
)
const BR_KG_BASE_URL = resolveServerBaseUrl(
  [
    process.env.BR_KG_URL,
    process.env.BR_KG_BASE_URL,
    process.env.BR_KG_API_URL,
    process.env.BR_KG_API,
  ],
  BR_KG_HOST,
  BR_KG_PORT
)

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  // Use polling in dev to avoid ENOSPC (system file watcher limit). Set USE_POLLING=0 to use native watchers.
  webpack: (config, { dev }) => {
    if (dev && process.env.USE_POLLING !== '0') {
      config.watchOptions = config.watchOptions || {}
      config.watchOptions.poll = 1000
      config.watchOptions.ignored = ['**/node_modules', '**/.git']
    }
    return config
  },
  async redirects() {
    return [
      { source: '/mcp', destination: '/mcp/setup', permanent: false },
    ]
  },
  async rewrites() {
    const orchestratorUrl = ORCHESTRATOR_BASE_URL
    const agentUrl = AGENT_BASE_URL
    const kgUrl = BR_KG_BASE_URL

    return {
      fallback: [
        // Health endpoints - must come before generic /api/* rule
        { source: '/api/agent/health', destination: `${agentUrl}/health` },
        { source: '/api/kg/health', destination: `${kgUrl}/health` },
        { source: '/api/br-kg/health', destination: `${kgUrl}/health` },
        // Dashboard API - route to Orchestrator (must come before generic /api/* rule)
        // UI widgets expect Orchestrator's aggregated contract (queue + storage + activity),
        // not BR-KG's placeholder metrics.
        { source: '/api/dashboard/:path*', destination: `${orchestratorUrl}/dashboard/:path*` },
        // BR-KG API - preserve /api/* prefixes
        { source: '/api/br-kg/:path*', destination: `${kgUrl}/api/:path*` },
        { source: '/api/kg/:path*', destination: `${kgUrl}/api/kg/:path*` },
        // Agent API
        { source: '/internal/agent/:path*', destination: `${agentUrl}/:path*` },

        // Orchestrator direct paths (browser calls without /api prefix)
        { source: '/threads/:path*', destination: `${orchestratorUrl}/threads/:path*` },
        { source: '/run', destination: `${orchestratorUrl}/run` },
        { source: '/copilot/:path*', destination: `${orchestratorUrl}/copilot/:path*` },
        { source: '/pipeline/:path*', destination: `${orchestratorUrl}/pipeline/:path*` },
        { source: '/upload', destination: `${orchestratorUrl}/upload` },
        { source: '/uploads/:path*', destination: `${orchestratorUrl}/uploads/:path*` },
        { source: '/health', destination: `${orchestratorUrl}/health` },
        // WebSocket proxy path (best-effort when traffic reaches Next.js directly)
        { source: '/ws/:path*', destination: `${orchestratorUrl}/ws/:path*` },

        // Orchestrator API - catch-all (must be last)
        { source: '/api/:path*', destination: `${orchestratorUrl}/api/:path*` },
      ],
    }
  },
}

module.exports = withNextIntl(nextConfig)
