import { useState, useEffect, useCallback, useRef } from 'react'
import {
  resolveDashboardMetricsUrl,
  resolveDashboardWsUrl,
} from '@/lib/service-endpoints'

export type ActivityType = 'start' | 'complete' | 'upload' | 'error' | 'submit'

export interface QueueSnapshot {
  running: number
  queued: number
  completed: number
  failed: number
}

export interface JobMetrics {
  queue: QueueSnapshot
  queueSource: string
  oldestPendingSeconds: number | null
  throughputPerMinute?: number | null
  activeWorkers?: number | null
  lastUpdated: string
}

export interface GpuSample {
  timestamp: string
  gpu1: number
  gpu2: number
  gpu3: number
  gpu4: number
}

export interface ResourceMetrics {
  gpuSamples: GpuSample[]
  cluster?: Record<string, unknown> | null
}

export interface StorageTier {
  used: number
  total: number
}

export interface StorageMetrics {
  primary: StorageTier
  archive: StorageTier
  scratch: StorageTier
  [tier: string]: StorageTier
}

export interface ActivityEntry {
  id: string
  timestamp: string
  user: string
  action: string
  type: ActivityType
}

export interface OutputItem {
  id: string
  name: string
  type: string
  size: string
  created: string
  url?: string
}

export interface DashboardMetadata {
  status: string
  source?: string
  fetched_at?: string
  errors?: string[]
}

export type McpStatus = 'used' | 'token_never_used' | 'no_token'

export interface McpAdoptionSummary {
  totalUsers: number
  usedUsers: number
  unusedUsers: number
  tokenNeverUsedUsers: number
  noTokenUsers: number
  adoptionRatePct: number
}

export interface McpAdoptionUser {
  userId: string
  username: string
  email: string
  fullName?: string | null
  role?: string | null
  createdAt: string
  hasAnyToken: boolean
  hasActiveToken: boolean
  tokenCount: number
  usedMcp: boolean
  lastUsedAt?: string | null
  mcpStatus: McpStatus
}

export interface McpAdoptionMetrics {
  generatedAt: string
  summary: McpAdoptionSummary
  users: McpAdoptionUser[]
}

export interface DashboardProject {
  id: string
  name: string
  progress: number
  subjects: number
  timeRemaining: string
  status: 'active' | 'paused' | 'completed'
}

export interface DashboardData {
  timestamp: string
  jobMetrics: JobMetrics
  resourceMetrics: ResourceMetrics
  projects: DashboardProject[]
  activity: ActivityEntry[]
  storageMetrics: StorageMetrics
  outputs: OutputItem[]
  mcpAdoption?: McpAdoptionMetrics | null
  metadata: DashboardMetadata
}

const DEFAULT_QUEUE: QueueSnapshot = { running: 0, queued: 0, completed: 0, failed: 0 }
const STORAGE_TIERS = ['primary', 'archive', 'scratch'] as const
const ACTIVITY_TYPES = new Set<ActivityType>(['start', 'complete', 'upload', 'error', 'submit'])
const MAX_GPU_SAMPLES = 24
const MAX_ACTIVITY_ITEMS = 20
const MAX_OUTPUT_ITEMS = 20

export function useDashboardData() {
  const [data, setData] = useState<DashboardData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [ws, setWs] = useState<WebSocket | null>(null)
  const [connected, setConnected] = useState(false)
  const connectedRef = useRef(connected)
  const wsRetryAttemptsRef = useRef(0)
  const wsReconnectTimerRef = useRef<NodeJS.Timeout | null>(null)
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const wsErrorLoggedRef = useRef(false)
  const shouldReconnectRef = useRef(true)
  const MAX_WS_RETRY_ATTEMPTS = 5

  useEffect(() => {
    connectedRef.current = connected
  }, [connected])

  const fetchData = useCallback(async () => {
    try {
      const endpoint = resolveDashboardMetricsUrl()
      const response = await fetch(endpoint)
      if (!response.ok) {
        throw new Error('Failed to fetch dashboard data')
      }
      const jsonData = await response.json()
      setData(normalizeDashboardPayload(jsonData))
      setError(null)
      setLoading(false)
    } catch (err) {
      console.error('Dashboard data fetch failed:', err)
      setError(err instanceof Error ? err.message : 'Failed to fetch dashboard data')
      setLoading(false)
    }
  }, [])

  const handleRealtimeUpdate = useCallback((update: any) => {
    const payload = update?.data?.type ? update.data : update
    setData(prevData => {
      if (!prevData) {
        return prevData
      }

      switch (payload?.type) {
        case 'snapshot': {
          if (!payload?.data) {
            return prevData
          }
          try {
            const nextData = normalizeDashboardPayload(payload.data)
            if (!nextData.mcpAdoption && prevData?.mcpAdoption) {
              nextData.mcpAdoption = prevData.mcpAdoption
            }
            return nextData
          } catch (snapshotErr) {
            console.error('Failed to process dashboard snapshot:', snapshotErr)
            return prevData
          }
        }

        case 'gpu_update': {
          const sample = normalizeGpuSample(payload.data)
          if (!sample) {
            return prevData
          }
          return {
            ...prevData,
            resourceMetrics: {
              ...prevData.resourceMetrics,
              gpuSamples: [...prevData.resourceMetrics.gpuSamples.slice(-MAX_GPU_SAMPLES + 1), sample]
            }
          }
        }

        case 'queue_update':
          return {
            ...prevData,
            jobMetrics: {
              ...prevData.jobMetrics,
              queue: normalizeQueueSnapshot(payload.data),
              lastUpdated: new Date().toISOString()
            }
          }

        case 'project_update': {
          const [updatedProject] = normalizeProjects([payload.data])
          if (!updatedProject) {
            return prevData
          }
          return {
            ...prevData,
            projects: prevData.projects.map(project =>
              project.id === updatedProject.id ? { ...project, ...updatedProject } : project
            )
          }
        }

        case 'activity_update':
          return {
            ...prevData,
            activity: [
              normalizeActivityItem(payload.data, 0),
              ...prevData.activity.slice(0, MAX_ACTIVITY_ITEMS - 1)
            ]
          }

        case 'storage_update':
          return {
            ...prevData,
            storageMetrics: normalizeStorageMetrics(payload.data)
          }

        case 'metadata_update':
          return {
            ...prevData,
            metadata: normalizeMetadata(payload.data)
          }

        case 'output_added': {
          const outputPayload = Array.isArray(payload.data) ? payload.data : [payload.data]
          const [output] = normalizeOutputs(outputPayload)
          if (!output) {
            return prevData
          }
          return {
            ...prevData,
            outputs: [output, ...prevData.outputs.slice(0, MAX_OUTPUT_ITEMS - 1)]
          }
        }

        default:
          return prevData
      }
    })
  }, [])

  const startPolling = useCallback(() => {
    if (pollIntervalRef.current) return
    pollIntervalRef.current = setInterval(async () => {
      if (!connectedRef.current) {
        await fetchData()
      }
    }, 5000)
  }, [fetchData])

  const stopPolling = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current)
      pollIntervalRef.current = null
    }
  }, [])

  const connectWebSocket = useCallback(() => {
    stopPolling()
    try {
      const wsUrl = resolveDashboardWsUrl()
      shouldReconnectRef.current = true

      const websocket = new WebSocket(wsUrl)

      websocket.onopen = () => {
        wsRetryAttemptsRef.current = 0
        wsErrorLoggedRef.current = false
        setConnected(true)
        setError(null)
      }

      websocket.onmessage = event => {
        try {
          const update = JSON.parse(event.data)
          handleRealtimeUpdate(update)
        } catch (parseErr) {
          console.error('Failed to parse WebSocket message:', parseErr)
        }
      }

      websocket.onerror = event => {
        if (!wsErrorLoggedRef.current) {
          wsErrorLoggedRef.current = true
          console.warn('Dashboard WebSocket error; switching to backoff/polling fallback.')
        }
        setConnected(false)
      }

      websocket.onclose = event => {
        setConnected(false)
        if (!shouldReconnectRef.current) return
        if (event.code === 1008 || event.code === 1003) {
          setError('Real-time dashboard updates unavailable; using periodic refresh.')
          startPolling()
          return
        }

        if (wsReconnectTimerRef.current) return

        if (wsRetryAttemptsRef.current >= MAX_WS_RETRY_ATTEMPTS) {
          setError('Real-time dashboard updates unavailable; using periodic refresh.')
          startPolling()
          return
        }

        const delayMs = Math.min(1000 * Math.pow(2, wsRetryAttemptsRef.current), 15000)
        wsRetryAttemptsRef.current += 1
        wsReconnectTimerRef.current = setTimeout(() => {
          wsReconnectTimerRef.current = null
          connectWebSocket()
        }, delayMs)
      }

      setWs(websocket)
    } catch (wsErr) {
      console.error('Failed to create WebSocket connection:', wsErr)
      setConnected(false)
      startPolling()
    }
  }, [handleRealtimeUpdate, startPolling, stopPolling])

  useEffect(() => {
    fetchData()
    connectWebSocket()
  }, [fetchData, connectWebSocket])

  useEffect(
    () => () => {
      if (wsReconnectTimerRef.current) {
        clearTimeout(wsReconnectTimerRef.current)
        wsReconnectTimerRef.current = null
      }
      stopPolling()
      if (ws) {
        shouldReconnectRef.current = false
        ws.close()
      }
    },
    [ws, stopPolling]
  )

  const refresh = useCallback(() => {
    fetchData()
  }, [fetchData])

  return {
    data,
    loading,
    error,
    connected,
    refresh
  }
}

function ensureISODate(value: unknown): string {
  if (value instanceof Date && !Number.isNaN(value.getTime())) {
    return value.toISOString()
  }
  if (typeof value === 'string' && value.length > 0) {
    const parsed = new Date(value)
    if (!Number.isNaN(parsed.getTime())) {
      return parsed.toISOString()
    }
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    const parsed = new Date(value)
    if (!Number.isNaN(parsed.getTime())) {
      return parsed.toISOString()
    }
  }
  return new Date().toISOString()
}

function ensureNumber(value: unknown, fallback = 0): number {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value
  }
  if (typeof value === 'string' && value.trim().length > 0) {
    const parsed = Number(value)
    if (Number.isFinite(parsed)) {
      return parsed
    }
  }
  return fallback
}

function ensureString(value: unknown, fallback = ''): string {
  if (typeof value === 'string') {
    return value
  }
  if (value === null || value === undefined) {
    return fallback
  }
  return String(value)
}

function normalizeQueueSnapshot(raw: any): QueueSnapshot {
  const base =
    raw && typeof raw === 'object'
      ? typeof raw.queue === 'object'
        ? raw.queue
        : raw
      : DEFAULT_QUEUE
  return {
    running: ensureNumber(base.running),
    queued: ensureNumber(base.queued),
    completed: ensureNumber(base.completed),
    failed: ensureNumber(base.failed)
  }
}

function normalizeJobMetrics(raw: any, legacyQueue?: any): JobMetrics {
  const source = raw && typeof raw === 'object' ? raw : {}
  const queue = normalizeQueueSnapshot(source.queue ?? legacyQueue)
  const queueSource = ensureString(source.queueSource ?? source.source ?? 'unknown', 'unknown')
  const oldest =
    typeof source.oldestPendingSeconds === 'number' && Number.isFinite(source.oldestPendingSeconds)
      ? source.oldestPendingSeconds
      : null
  const throughput =
    typeof source.throughputPerMinute === 'number' && Number.isFinite(source.throughputPerMinute)
      ? source.throughputPerMinute
      : null
  const activeWorkers =
    typeof source.activeWorkers === 'number' && Number.isFinite(source.activeWorkers)
      ? source.activeWorkers
      : typeof source.active_workers === 'number' && Number.isFinite(source.active_workers)
        ? source.active_workers
        : null
  const lastUpdated = ensureISODate(source.lastUpdated ?? source.timestamp ?? Date.now())
  return {
    queue,
    queueSource,
    oldestPendingSeconds: oldest,
    throughputPerMinute: throughput,
    activeWorkers,
    lastUpdated
  }
}

function normalizeGpuSample(raw: any): GpuSample | null {
  if (!raw || typeof raw !== 'object') {
    return null
  }
  return {
    timestamp: ensureISODate(raw.timestamp),
    gpu1: ensureNumber(raw.gpu1),
    gpu2: ensureNumber(raw.gpu2),
    gpu3: ensureNumber(raw.gpu3),
    gpu4: ensureNumber(raw.gpu4)
  }
}

function normalizeGpuSeries(raw: any): GpuSample[] {
  if (!Array.isArray(raw)) {
    return []
  }
  const samples = raw
    .map(sample => normalizeGpuSample(sample))
    .filter((sample): sample is GpuSample => Boolean(sample))
  return samples.slice(-MAX_GPU_SAMPLES)
}

function normalizeResourceMetrics(raw: any, legacy?: any): ResourceMetrics {
  const source = raw && typeof raw === 'object' ? raw : {}
  return {
    gpuSamples: normalizeGpuSeries(source.gpuSamples ?? legacy?.gpuUtilization ?? []),
    cluster: source.cluster ?? legacy?.clusterStatus ?? null
  }
}

function normalizeStorageTier(raw: any): StorageTier {
  const used = Math.max(0, ensureNumber(raw?.used))
  const totalCandidate = ensureNumber(raw?.total, used || 1)
  const total = Math.max(totalCandidate, used || 1)
  return { used, total }
}

function normalizeStorageMetrics(raw: any): StorageMetrics {
  const source = raw && typeof raw === 'object' ? raw : {}
  const tierNames = new Set<string>([...STORAGE_TIERS, ...Object.keys(source ?? {})])
  const metrics: Record<string, StorageTier> = {}

  tierNames.forEach(tier => {
    metrics[tier] = normalizeStorageTier((source as Record<string, any>)[tier])
  })

  STORAGE_TIERS.forEach(tier => {
    metrics[tier] = metrics[tier] ?? normalizeStorageTier(undefined)
  })

  return metrics as StorageMetrics
}

function normalizeProjects(raw: any): DashboardProject[] {
  if (!Array.isArray(raw)) {
    return []
  }
  return raw.map((project, index) => {
    const subjects = ensureNumber(project?.subjects)
    const progress = Math.min(Math.max(ensureNumber(project?.progress), 0), 100)
    const statusRaw = ensureString(project?.status, 'active') as DashboardProject['status']
    const status: DashboardProject['status'] =
      statusRaw === 'paused' || statusRaw === 'completed' ? statusRaw : 'active'
    const timeRemaining =
      typeof project?.timeRemaining === 'string' && project.timeRemaining.length > 0
        ? project.timeRemaining
        : '—'
    return {
      id: ensureString(project?.id, 'project-' + index),
      name: ensureString(project?.name, 'Untitled Project'),
      progress,
      subjects,
      timeRemaining,
      status
    }
  })
}

function normalizeActivityItem(entry: any, index = 0): ActivityEntry {
  const typeRaw = ensureString(entry?.type, 'start') as ActivityType
  const type = ACTIVITY_TYPES.has(typeRaw) ? typeRaw : 'start'
  return {
    id: ensureString(entry?.id, 'activity-' + index),
    timestamp: ensureISODate(entry?.timestamp),
    user: ensureString(entry?.user, 'System'),
    action: ensureString(entry?.action, 'Analysis update'),
    type
  }
}

function normalizeActivityFeed(raw: any): ActivityEntry[] {
  if (!Array.isArray(raw)) {
    return []
  }
  return raw
    .map((event, index) => normalizeActivityItem(event, index))
    .slice(0, MAX_ACTIVITY_ITEMS)
}

function normalizeOutputs(raw: any): OutputItem[] {
  if (!Array.isArray(raw)) {
    return []
  }
  return raw
    .map((item, index) => ({
      id: ensureString(item?.id, 'output-' + index),
      name: ensureString(item?.name, 'Analysis output'),
      type: ensureString(item?.type, 'report'),
      size: ensureString(item?.size, 'N/A'),
      created: ensureISODate(item?.created),
      url: typeof item?.url === 'string' ? item.url : undefined
    }))
    .slice(0, MAX_OUTPUT_ITEMS)
}

function normalizeMetadata(raw: any): DashboardMetadata {
  const source = raw && typeof raw === 'object' ? raw : {}
  const errors = Array.isArray(source.errors)
    ? source.errors.map((err: unknown) => ensureString(err, 'unknown'))
    : undefined
  return {
    status: ensureString(source.status ?? 'unknown', 'unknown'),
    source: typeof source.source === 'string' ? source.source : undefined,
    fetched_at: typeof source.fetched_at === 'string' ? source.fetched_at : undefined,
    errors
  }
}

function normalizeMcpStatus(value: unknown): McpStatus {
  const raw = ensureString(value, 'no_token')
  if (raw === 'used' || raw === 'token_never_used' || raw === 'no_token') {
    return raw
  }
  return 'no_token'
}

function normalizeMcpAdoptionSummary(raw: any): McpAdoptionSummary {
  const source = raw && typeof raw === 'object' ? raw : {}
  return {
    totalUsers: ensureNumber(source.totalUsers),
    usedUsers: ensureNumber(source.usedUsers),
    unusedUsers: ensureNumber(source.unusedUsers),
    tokenNeverUsedUsers: ensureNumber(source.tokenNeverUsedUsers),
    noTokenUsers: ensureNumber(source.noTokenUsers),
    adoptionRatePct: ensureNumber(source.adoptionRatePct),
  }
}

function normalizeMcpAdoptionUsers(raw: any): McpAdoptionUser[] {
  if (!Array.isArray(raw)) {
    return []
  }
  return raw.map((entry, index) => ({
    userId: ensureString(entry?.userId, `user-${index}`),
    username: ensureString(entry?.username, 'unknown'),
    email: ensureString(entry?.email),
    fullName:
      typeof entry?.fullName === 'string' && entry.fullName.length > 0 ? entry.fullName : undefined,
    role: typeof entry?.role === 'string' && entry.role.length > 0 ? entry.role : undefined,
    createdAt: ensureISODate(entry?.createdAt),
    hasAnyToken: Boolean(entry?.hasAnyToken),
    hasActiveToken: Boolean(entry?.hasActiveToken),
    tokenCount: ensureNumber(entry?.tokenCount),
    usedMcp: Boolean(entry?.usedMcp),
    lastUsedAt:
      entry?.lastUsedAt == null || entry?.lastUsedAt === ''
        ? undefined
        : ensureISODate(entry?.lastUsedAt),
    mcpStatus: normalizeMcpStatus(entry?.mcpStatus),
  }))
}

function normalizeMcpAdoption(raw: any): McpAdoptionMetrics | null {
  if (!raw || typeof raw !== 'object') {
    return null
  }
  return {
    generatedAt: ensureISODate(raw.generatedAt),
    summary: normalizeMcpAdoptionSummary(raw.summary),
    users: normalizeMcpAdoptionUsers(raw.users),
  }
}

function normalizeDashboardPayload(raw: any): DashboardData {
  const safe = raw ?? {}
  return {
    timestamp: ensureISODate(safe.timestamp ?? safe.fetched_at),
    jobMetrics: normalizeJobMetrics(safe.jobMetrics, safe.queueStatus),
    resourceMetrics: normalizeResourceMetrics(safe.resourceMetrics, safe),
    projects: normalizeProjects(safe.projects),
    activity: normalizeActivityFeed(safe.activity ?? safe.teamActivity),
    storageMetrics: normalizeStorageMetrics(safe.storageMetrics ?? safe.storage ?? {}),
    outputs: normalizeOutputs(safe.outputs),
    mcpAdoption: normalizeMcpAdoption(safe.mcpAdoption),
    metadata: normalizeMetadata(safe.metadata ?? safe)
  }
}
