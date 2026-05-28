import { SERVICE_HOSTS, SERVICE_PORTS, SERVICE_URLS, USE_API_PROXY, WS_URLS } from './config'

const stripTrailingSlash = (value: string) => value.replace(/\/$/, '')
const ensureLeadingSlash = (value: string) =>
  value.startsWith('/') ? value : `/${value}`

// Public browser traffic stays under Next.js `/api/*`.
// Agent-backed public routes include chat/files/datasets/threads plus the
// legacy-only `/api/runs` surface. Canonical browser analysis create/list now
// resolve through Orchestrator `/run` + `/api/analyses`.
// Orchestrator-backed public routes include analyses/jobs/share/credits/dashboard/notifications.
// Do not add an extra prefix here (for example `/api/orchestrator`), otherwise requests will 404.
const ORCHESTRATOR_PROXY_PREFIX = ''
const AGENT_PROXY_PREFIX = '/api/agent'
const KG_PROXY_PREFIX = '/api/kg'

type EndpointOptions = {
  absolute?: boolean
}

const ORCHESTRATOR_BASE = stripTrailingSlash(SERVICE_URLS.ORCHESTRATOR)
const AGENT_BASE = stripTrailingSlash(SERVICE_URLS.AGENT)
const KG_BASE = stripTrailingSlash(SERVICE_URLS.KG)

const USE_PROXY = USE_API_PROXY

const join = (base: string, path: string) => {
  if (!path) {
    return base
  }
  if (path.startsWith('http://') || path.startsWith('https://')) {
    return path
  }
  return `${base}${path.startsWith('/') ? path : `/${path}`}`
}

const appendPath = (base: string, path: string) =>
  `${base.replace(/\/+$/, '')}${path.startsWith('/') ? path : `/${path}`}`

const toWebSocketProtocol = (value: string) =>
  value.replace(/^http:/i, 'ws:').replace(/^https:/i, 'wss:')

const resolveBrowserWebSocketProtocol = () =>
  typeof window !== 'undefined' && window.location.protocol === 'https:' ? 'wss:' : 'ws:'

const resolveDirectOrchestratorWsBase = () =>
  `${resolveBrowserWebSocketProtocol()}//${SERVICE_HOSTS.ORCHESTRATOR}:${SERVICE_PORTS.ORCHESTRATOR}/ws`

const shouldBypassNextDevWsProxy = (wsBase: string) => {
  if (typeof window === 'undefined' || !USE_PROXY) return false
  if (wsBase && wsBase !== '/ws') return false

  const hostname = window.location.hostname.toLowerCase()
  if (!['localhost', '127.0.0.1', '0.0.0.0'].includes(hostname)) return false

  return window.location.port !== String(SERVICE_PORTS.ORCHESTRATOR)
}

const buildEndpoint = (
  base: string,
  proxyPrefix: string,
  path: string,
  options?: EndpointOptions
) => {
  const normalized = ensureLeadingSlash(path)

  if (USE_PROXY && !options?.absolute) {
    return `${proxyPrefix}${normalized}`
  }

  return join(base, normalized)
}

export const serviceEndpoints = {
  useProxy: USE_PROXY,
  orchestratorBase: ORCHESTRATOR_BASE,
  agentBase: AGENT_BASE,
  kgBase: KG_BASE,
  orchestrator(path: string, options?: EndpointOptions) {
    return buildEndpoint(ORCHESTRATOR_BASE, ORCHESTRATOR_PROXY_PREFIX, path, options)
  },
  orchestratorApi(path: string, options?: EndpointOptions) {
    return serviceEndpoints.orchestrator(path, options)
  },
  agent(path: string, options?: EndpointOptions) {
    return buildEndpoint(AGENT_BASE, AGENT_PROXY_PREFIX, path, options)
  },
  kg(path: string, options?: EndpointOptions) {
    return buildEndpoint(KG_BASE, KG_PROXY_PREFIX, path, options)
  },
}

export const resolveKgGraphUrl = (params: URLSearchParams) => {
  if (serviceEndpoints.useProxy && typeof window !== 'undefined') {
    const qs = params.toString()
    const proxyPath = `/api/neurokg/graph${qs ? `?${qs}` : ''}`
    return proxyPath
  }

  const backendUrl = new URL('/api/graph', KG_BASE)
  params.forEach((value, key) => backendUrl.searchParams.set(key, value))
  return backendUrl.toString()
}

export const resolveKgVizUrl = (path: string, params?: URLSearchParams) => {
  const normalized = path.startsWith('/') ? path : `/${path}`

  if (serviceEndpoints.useProxy && typeof window !== 'undefined') {
    const qs = params?.toString()
    return `/api/neurokg/viz/brain${normalized}${qs ? `?${qs}` : ''}`
  }

  const backendUrl = new URL(`/api/viz/brain${normalized}`, KG_BASE)
  if (params) {
    params.forEach((value, key) => backendUrl.searchParams.set(key, value))
  }
  return backendUrl.toString()
}

export const resolveKgHealthUrl = () =>
  typeof window !== 'undefined'
    ? '/api/kg/health'
    : join(KG_BASE, '/health')

const resolveKgUrl = (
  path: string,
  params?: URLSearchParams,
  options?: { rootPath?: boolean },
) => {
  const normalized = path.replace(/^\/+/, '')

  if (serviceEndpoints.useProxy && typeof window !== 'undefined') {
    const qs = params?.toString()
    return `/api/neurokg/${normalized}${qs ? `?${qs}` : ''}`
  }

  const backendPath = options?.rootPath ? `/${normalized}` : `/api/${normalized}`
  const backendUrl = new URL(backendPath, KG_BASE)
  if (params) {
    params.forEach((value, key) => backendUrl.searchParams.set(key, value))
  }
  return backendUrl.toString()
}

export const resolveKgApiUrl = (path: string, params?: URLSearchParams) =>
  resolveKgUrl(path, params)

export const resolveKgRootUrl = (path: string, params?: URLSearchParams) =>
  resolveKgUrl(path, params, { rootPath: true })

export const resolveAgentHealthUrl = () =>
  typeof window !== 'undefined'
    ? '/api/health'
    : join(AGENT_BASE, '/api/health')

export const resolveKgQueryUrl = () =>
  serviceEndpoints.useProxy && typeof window !== 'undefined'
    ? '/api/neurokg/graph/query'
    : join(KG_BASE, '/api/graph/query')

export const resolveKgEvidenceUrl = (params?: URLSearchParams) => {
  if (serviceEndpoints.useProxy && typeof window !== 'undefined') {
    const qs = params?.toString()
    return `/api/kg/evidence${qs ? `?${qs}` : ''}`
  }
  const backendUrl = new URL('/api/kg/evidence', KG_BASE)
  if (params) params.forEach((v, k) => backendUrl.searchParams.set(k, v))
  return backendUrl.toString()
}

export const resolveKgConceptsUrl = (params?: URLSearchParams) => {
  if (serviceEndpoints.useProxy && typeof window !== 'undefined') {
    const qs = params?.toString()
    return `/api/kg/concepts${qs ? `?${qs}` : ''}`
  }
  const backendUrl = new URL('/api/kg/concepts', KG_BASE)
  if (params) params.forEach((v, k) => backendUrl.searchParams.set(k, v))
  return backendUrl.toString()
}

export const resolveKgConceptTreeUrl = (params?: URLSearchParams) => {
  if (serviceEndpoints.useProxy && typeof window !== 'undefined') {
    const qs = params?.toString()
    return `/api/kg/concepts/tree${qs ? `?${qs}` : ''}`
  }
  const backendUrl = new URL('/api/kg/concepts/tree', KG_BASE)
  if (params) params.forEach((v, k) => backendUrl.searchParams.set(k, v))
  return backendUrl.toString()
}

export const resolveKgConceptUrl = (id: string) => {
  const encodedId = encodeURIComponent(id)
  return serviceEndpoints.useProxy && typeof window !== 'undefined'
    ? `/api/kg/concept/${encodedId}`
    : join(KG_BASE, `/api/kg/concept/${encodedId}`)
}

export const resolveKgConceptSummaryUrl = (id: string) => {
  const encodedId = encodeURIComponent(id)
  return serviceEndpoints.useProxy && typeof window !== 'undefined'
    ? `/api/kg/concept/${encodedId}/summary`
    : join(KG_BASE, `/api/kg/concept/${encodedId}/summary`)
}

export const resolveKgConceptEvidenceUrl = (id: string, params?: URLSearchParams) => {
  const encodedId = encodeURIComponent(id)
  if (serviceEndpoints.useProxy && typeof window !== 'undefined') {
    const qs = params?.toString()
    return `/api/kg/concept/${encodedId}/evidence${qs ? `?${qs}` : ''}`
  }
  const backendUrl = new URL(`/api/kg/concept/${encodedId}/evidence`, KG_BASE)
  if (params) params.forEach((v, k) => backendUrl.searchParams.set(k, v))
  return backendUrl.toString()
}

export const resolveKgConceptEvidencePathsUrl = (id: string, params?: URLSearchParams) => {
  const encodedId = encodeURIComponent(id)
  if (serviceEndpoints.useProxy && typeof window !== 'undefined') {
    const qs = params?.toString()
    return `/api/kg/concept/${encodedId}/evidence/paths${qs ? `?${qs}` : ''}`
  }
  const backendUrl = new URL(`/api/kg/concept/${encodedId}/evidence/paths`, KG_BASE)
  if (params) params.forEach((v, k) => backendUrl.searchParams.set(k, v))
  return backendUrl.toString()
}

export const resolveKgConceptChildrenUrl = (id: string, params?: URLSearchParams) => {
  const encodedId = encodeURIComponent(id)
  if (serviceEndpoints.useProxy && typeof window !== 'undefined') {
    const qs = params?.toString()
    return `/api/kg/concept/${encodedId}/children${qs ? `?${qs}` : ''}`
  }
  const backendUrl = new URL(`/api/kg/concept/${encodedId}/children`, KG_BASE)
  if (params) params.forEach((v, k) => backendUrl.searchParams.set(k, v))
  return backendUrl.toString()
}

export const resolveKgLensEntitiesUrl = (lens: string, params?: URLSearchParams) => {
  if (serviceEndpoints.useProxy && typeof window !== 'undefined') {
    const qs = params?.toString()
    return `/api/kg/lens/${lens}/entities${qs ? `?${qs}` : ''}`
  }
  const backendUrl = new URL(`/api/kg/lens/${lens}/entities`, KG_BASE)
  if (params) params.forEach((v, k) => backendUrl.searchParams.set(k, v))
  return backendUrl.toString()
}

export const resolveKgLensTaskTreeUrl = (params?: URLSearchParams) => {
  if (serviceEndpoints.useProxy && typeof window !== 'undefined') {
    const qs = params?.toString()
    return `/api/kg/lens/task/tree${qs ? `?${qs}` : ''}`
  }
  const backendUrl = new URL('/api/kg/lens/task/tree', KG_BASE)
  if (params) params.forEach((v, k) => backendUrl.searchParams.set(k, v))
  return backendUrl.toString()
}

export const resolveKgLensEntitySummaryUrl = (lens: string, entityId: string) => {
  const encodedEntityId = encodeURIComponent(entityId)
  return serviceEndpoints.useProxy && typeof window !== 'undefined'
    ? `/api/kg/lens/${lens}/entity/${encodedEntityId}/summary`
    : join(KG_BASE, `/api/kg/lens/${lens}/entity/${encodedEntityId}/summary`)
}

export const resolveKgLensEntityEvidenceUrl = (
  lens: string,
  entityId: string,
  params?: URLSearchParams,
) => {
  const encodedEntityId = encodeURIComponent(entityId)
  if (serviceEndpoints.useProxy && typeof window !== 'undefined') {
    const qs = params?.toString()
    return `/api/kg/lens/${lens}/entity/${encodedEntityId}/evidence${qs ? `?${qs}` : ''}`
  }
  const backendUrl = new URL(
    `/api/kg/lens/${lens}/entity/${encodedEntityId}/evidence`,
    KG_BASE,
  )
  if (params) params.forEach((v, k) => backendUrl.searchParams.set(k, v))
  return backendUrl.toString()
}

export const resolveKgLensEntityEvidencePathsUrl = (
  lens: string,
  entityId: string,
  params?: URLSearchParams,
) => {
  const encodedEntityId = encodeURIComponent(entityId)
  if (serviceEndpoints.useProxy && typeof window !== 'undefined') {
    const qs = params?.toString()
    return `/api/kg/lens/${lens}/entity/${encodedEntityId}/evidence/paths${qs ? `?${qs}` : ''}`
  }
  const backendUrl = new URL(
    `/api/kg/lens/${lens}/entity/${encodedEntityId}/evidence/paths`,
    KG_BASE,
  )
  if (params) params.forEach((v, k) => backendUrl.searchParams.set(k, v))
  return backendUrl.toString()
}

export const resolveDashboardMetricsUrl = () => {
  if (serviceEndpoints.useProxy && typeof window !== 'undefined') {
    return '/api/dashboard/metrics'
  }
  return join(ORCHESTRATOR_BASE, '/dashboard/metrics')
}

export const resolveDashboardWsUrl = () => {
  const wsBase = stripTrailingSlash(WS_URLS.ORCHESTRATOR || '')
  if (shouldBypassNextDevWsProxy(wsBase)) {
    return `${resolveDirectOrchestratorWsBase()}/dashboard`
  }
  if (wsBase) {
    const dashboardPath = appendPath(wsBase, '/dashboard')
    if (dashboardPath.startsWith('ws://') || dashboardPath.startsWith('wss://')) {
      return dashboardPath
    }
    if (dashboardPath.startsWith('http://') || dashboardPath.startsWith('https://')) {
      return toWebSocketProtocol(dashboardPath)
    }
    if (dashboardPath.startsWith('/')) {
      if (typeof window !== 'undefined') {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
        return `${protocol}//${window.location.host}${dashboardPath}`
      }
      return toWebSocketProtocol(appendPath(ORCHESTRATOR_BASE, dashboardPath))
    }
  }

  if (typeof window !== 'undefined') {
    return `${resolveBrowserWebSocketProtocol()}//${window.location.host}/ws/dashboard`
  }
  return toWebSocketProtocol(appendPath(ORCHESTRATOR_BASE, '/ws/dashboard'))
}

export const resolveRealtimeWsBaseUrl = () => {
  const wsBase = stripTrailingSlash(WS_URLS.ORCHESTRATOR || '')
  if (shouldBypassNextDevWsProxy(wsBase)) {
    return resolveDirectOrchestratorWsBase()
  }
  if (wsBase) {
    if (wsBase.startsWith('ws://') || wsBase.startsWith('wss://')) {
      return wsBase
    }
    if (wsBase.startsWith('http://') || wsBase.startsWith('https://')) {
      return toWebSocketProtocol(wsBase)
    }
    if (wsBase.startsWith('/')) {
      if (typeof window !== 'undefined') {
        const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
        return `${protocol}//${window.location.host}${wsBase}`
      }
      return toWebSocketProtocol(appendPath(ORCHESTRATOR_BASE, wsBase))
    }
  }

  if (typeof window !== 'undefined') {
    return `${resolveBrowserWebSocketProtocol()}//${window.location.host}/ws`
  }
  return toWebSocketProtocol(appendPath(ORCHESTRATOR_BASE, '/ws'))
}
