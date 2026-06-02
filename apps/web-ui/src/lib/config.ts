/**
 * Centralized configuration for all service URLs and ports
 * This file provides a single source of truth for backend service endpoints
 */

const RUNTIME_ENV: Record<string, string | undefined> = {
  ORCHESTRATOR_PORT: process.env.ORCHESTRATOR_PORT,
  AGENT_PORT: process.env.AGENT_PORT,
  KG_PORT: process.env.KG_PORT,
  BR_KG_PORT: process.env.BR_KG_PORT,
  NICLIP_PORT: process.env.NICLIP_PORT,
  WEB_UI_PORT: process.env.WEB_UI_PORT,
  ORCHESTRATOR_HOST: process.env.ORCHESTRATOR_HOST,
  AGENT_HOST: process.env.AGENT_HOST,
  KG_HOST: process.env.KG_HOST,
  BR_KG_HOST: process.env.BR_KG_HOST,
  NICLIP_HOST: process.env.NICLIP_HOST,
  WEB_UI_HOST: process.env.WEB_UI_HOST,
  NEXT_PUBLIC_ORCHESTRATOR_URL: process.env.NEXT_PUBLIC_ORCHESTRATOR_URL,
  NEXT_PUBLIC_AGENT_API: process.env.NEXT_PUBLIC_AGENT_API,
  NEXT_PUBLIC_BR_KG_API: process.env.NEXT_PUBLIC_BR_KG_API,
  NEXT_PUBLIC_NICLIP_API: process.env.NEXT_PUBLIC_NICLIP_API,
  NEXT_PUBLIC_WS_URL: process.env.NEXT_PUBLIC_WS_URL,
  NEXT_PUBLIC_USE_API_PROXY: process.env.NEXT_PUBLIC_USE_API_PROXY,
  HTTP_PROTOCOL: process.env.HTTP_PROTOCOL,
  WS_PROTOCOL: process.env.WS_PROTOCOL,
}

// Environment variable helpers
const getEnvVar = (key: keyof typeof RUNTIME_ENV, defaultValue: string): string => {
  if (typeof window !== 'undefined') {
    // Client-side: use NEXT_PUBLIC_ variables
    return (window as any).__ENV?.[key] || RUNTIME_ENV[key] || defaultValue
  }
  // Server-side: use process.env snapshot
  return RUNTIME_ENV[key] || defaultValue
}

// Service ports (configurable via environment variables)
export const SERVICE_PORTS = {
  ORCHESTRATOR: parseInt(getEnvVar('ORCHESTRATOR_PORT', '3001')),
  AGENT: parseInt(getEnvVar('AGENT_PORT', '8000')),
  KG: parseInt(getEnvVar('KG_PORT', getEnvVar('BR_KG_PORT', '5000'))),
  BR_KG: parseInt(getEnvVar('BR_KG_PORT', '5000')),
  NICLIP: parseInt(getEnvVar('NICLIP_PORT', '8001')),
  WEB_UI: parseInt(getEnvVar('WEB_UI_PORT', '3000')),
} as const

// Service hosts (configurable via environment variables)
export const SERVICE_HOSTS = {
  ORCHESTRATOR: getEnvVar('ORCHESTRATOR_HOST', 'localhost'),
  AGENT: getEnvVar('AGENT_HOST', 'localhost'),
  KG: getEnvVar('KG_HOST', getEnvVar('BR_KG_HOST', 'localhost')),
  BR_KG: getEnvVar('BR_KG_HOST', 'localhost'),
  NICLIP: getEnvVar('NICLIP_HOST', 'localhost'),
  WEB_UI: getEnvVar('WEB_UI_HOST', 'localhost'),
} as const

// Protocol configuration
export const PROTOCOLS = {
  HTTP: getEnvVar('HTTP_PROTOCOL', 'http'),
  WS: getEnvVar('WS_PROTOCOL', 'ws'),
} as const

const defaultProxy = 'true'
const proxyEnabled =
  getEnvVar('NEXT_PUBLIC_USE_API_PROXY', defaultProxy).toLowerCase() !== 'false'
const browserProxyMode = typeof window !== 'undefined' && proxyEnabled

const kgServiceUrl = getEnvVar(
  'NEXT_PUBLIC_BR_KG_API',
  getEnvVar(
    'NEXT_PUBLIC_BR_KG_API',
    browserProxyMode
      ? '/api/kg'
      : `${PROTOCOLS.HTTP}://${SERVICE_HOSTS.KG}:${SERVICE_PORTS.KG}`
  )
)

// Construct full service URLs
export const SERVICE_URLS = {
  ORCHESTRATOR: getEnvVar(
    'NEXT_PUBLIC_ORCHESTRATOR_URL',
    browserProxyMode
      ? ''
      : `${PROTOCOLS.HTTP}://${SERVICE_HOSTS.ORCHESTRATOR}:${SERVICE_PORTS.ORCHESTRATOR}`
  ),
  AGENT: getEnvVar(
    'NEXT_PUBLIC_AGENT_API',
    browserProxyMode
      ? '/internal/agent'
      : `${PROTOCOLS.HTTP}://${SERVICE_HOSTS.AGENT}:${SERVICE_PORTS.AGENT}`
  ),
  KG: kgServiceUrl,
  BR_KG: kgServiceUrl,
  NICLIP: getEnvVar('NEXT_PUBLIC_NICLIP_API', `${PROTOCOLS.HTTP}://${SERVICE_HOSTS.NICLIP}:${SERVICE_PORTS.NICLIP}`),
} as const

// WebSocket URLs
const defaultOrchestratorWs = proxyEnabled
  ? '/ws'
  : `${PROTOCOLS.WS}://${SERVICE_HOSTS.ORCHESTRATOR}:${SERVICE_PORTS.ORCHESTRATOR}/ws`

export const WS_URLS = {
  ORCHESTRATOR: getEnvVar('NEXT_PUBLIC_WS_URL', defaultOrchestratorWs),
} as const

export const USE_API_PROXY = proxyEnabled

// API endpoint builders
export const API_ENDPOINTS = {
  // Downstream service endpoints. Public browser traffic should still go through
  // Next.js `/api/*` routes; these URLs describe the underlying service owners.
  orchestrator: {
    base: SERVICE_URLS.ORCHESTRATOR,
    run: `${SERVICE_URLS.ORCHESTRATOR}/run`,
    jobs: `${SERVICE_URLS.ORCHESTRATOR}/api/jobs`,
    analyses: `${SERVICE_URLS.ORCHESTRATOR}/api/analyses`,
    health: `${SERVICE_URLS.ORCHESTRATOR}/health`,
  },
  // Agent endpoints
  agent: {
    base: SERVICE_URLS.AGENT,
    chat: `${SERVICE_URLS.AGENT}/api/chat`,
    runs: `${SERVICE_URLS.AGENT}/api/runs`, // legacy compatibility only; canonical browser analysis create/list use orchestrator run/analyses
    datasets: `${SERVICE_URLS.AGENT}/api/datasets`,
    auth: `${SERVICE_URLS.AGENT}/api/auth`,
    health: `${SERVICE_URLS.AGENT}/api/health`,
  },
  // BR-KG endpoints
  kg: {
    base: SERVICE_URLS.KG,
    search: `${SERVICE_URLS.KG}/api/search_and_expand`,
    openneuro: `${SERVICE_URLS.KG}/api/openneuro`,
    health: `${SERVICE_URLS.KG}/health`,
  },
  brKg: {
    base: SERVICE_URLS.KG,
    search: `${SERVICE_URLS.KG}/api/search_and_expand`,
    openneuro: `${SERVICE_URLS.KG}/api/openneuro`,
    health: `${SERVICE_URLS.KG}/health`,
  },
  // NICLIP endpoints
  niclip: {
    base: SERVICE_URLS.NICLIP,
    embed: `${SERVICE_URLS.NICLIP}/api/embed`,
    health: `${SERVICE_URLS.NICLIP}/health`,
  },
} as const

// WebSocket endpoint builders
export const WS_ENDPOINTS = {
  orchestrator: {
    base: WS_URLS.ORCHESTRATOR,
    jobs: (jobId: string) => `${WS_URLS.ORCHESTRATOR}/jobs/${jobId}`,
    chat: (threadId: string) => `${WS_URLS.ORCHESTRATOR}/chat/${threadId}`,
    notifications: `${WS_URLS.ORCHESTRATOR}/notifications`,
  },
} as const

// NOTE: serviceEndpoints is now in ./service-endpoints.ts
// Import it directly: import { serviceEndpoints } from '@/lib/service-endpoints'

// Export a helper to get config at runtime (for client-side dynamic imports)
export const getConfig = () => ({
  ports: SERVICE_PORTS,
  hosts: SERVICE_HOSTS,
  protocols: PROTOCOLS,
  urls: SERVICE_URLS,
  ws: WS_URLS,
  api: API_ENDPOINTS,
  wsEndpoints: WS_ENDPOINTS,
})

// Type exports
export type ServiceName = keyof typeof SERVICE_URLS
export type WSEndpointName = keyof typeof WS_ENDPOINTS
