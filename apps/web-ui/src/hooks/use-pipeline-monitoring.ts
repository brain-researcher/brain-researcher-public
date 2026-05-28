'use client'

import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import { useWebSocket, WebSocketMessage } from '@/lib/websocket-manager'
import { PipelineNodeData } from '@/components/pipeline/PipelineNode'
import { TimelineEvent } from '@/components/pipeline/PipelineTimeline'
import { useSession } from 'next-auth/react'

import { resolveRealtimeWsBaseUrl, serviceEndpoints } from '@/lib/service-endpoints'

const orchestratorFetch = async (path: string, init?: RequestInit) => {
  const normalized = path.startsWith('/') ? path : `/${path}`
  const needsAbsolute =
    normalized.startsWith('/run') ||
    normalized.startsWith('/pipeline/')

  const preferRelativeApi =
    typeof window !== 'undefined' &&
    normalized.startsWith('/api/') &&
    serviceEndpoints.useProxy

  let url: string
  if (preferRelativeApi) {
    url = normalized
  } else if (needsAbsolute) {
    url = serviceEndpoints.orchestrator(normalized, { absolute: true })
  } else {
    url = serviceEndpoints.orchestrator(normalized)
  }

  const shouldFallback =
    typeof window !== 'undefined' &&
    normalized.startsWith('/api/') &&
    url !== normalized

  try {
    return await fetch(url, init)
  } catch (err) {
    if (shouldFallback) {
      return await fetch(normalized, init)
    }
    throw err
  }
}

export interface PipelineStatus {
  id: string
  name: string
  status: 'idle' | 'running' | 'completed' | 'failed' | 'paused'
  progress: number
  startTime?: Date
  endTime?: Date
  nodes: Record<string, PipelineNodeData>
  edges: Array<{
    id: string
    source: string
    target: string
    animated?: boolean
    type?: string
  }>
  timeline: TimelineEvent[]
  metadata?: {
    totalSteps?: number
    completedSteps?: number
    failedSteps?: number
    estimatedDuration?: number
    resourceRequirements?: {
      cpu: number
      memory: number
      gpu?: number
    }
    tags?: string[]
    version?: string
  }
  performance?: {
    avgExecutionTime?: number
    resourceEfficiency?: number
    successRate?: number
    lastOptimized?: Date
  }
}

export interface PipelineExecution {
  id: string
  pipelineId: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'paused'
  startTime: Date
  endTime?: Date
  nodes: Record<string, PipelineNodeData>
  logs: Array<{
    id: string
    timestamp: Date
    nodeId: string
    level: 'debug' | 'info' | 'warning' | 'error'
    message: string
    metadata?: Record<string, any>
  }>
  results?: Record<string, any>
  metrics?: {
    totalDuration?: number
    resourceUsage?: Record<string, any>
    performance?: Record<string, number>
  }
}

interface UsePipelineMonitoringOptions {
  pipelineId?: string
  autoConnect?: boolean
  pollInterval?: number
  enableResourceMonitoring?: boolean
  enablePerformanceTracking?: boolean
  resourceUpdateInterval?: number
  bufferSize?: number
}

interface UsePipelineMonitoringReturn {
  pipeline: PipelineStatus | null
  execution: PipelineExecution | null
  monitoringEnabled: boolean
  wsTargetReady: boolean
  transportMode: 'disabled' | 'waiting' | 'ws' | 'polling' | 'disconnected'
  isConnected: boolean
  connectionState: 'connecting' | 'open' | 'closing' | 'closed'
  latency: number
  reconnect: () => Promise<void>
  disconnect: () => void
  startPipeline: (pipelineId: string, parameters?: Record<string, any>) => Promise<PipelineExecution | void>
  pausePipeline: (executionId: string) => Promise<void>
  resumePipeline: (executionId: string) => Promise<void>
  cancelPipeline: (executionId: string) => Promise<void>
  retryNode: (executionId: string, nodeId: string) => Promise<void>
  retryPipeline: (pipelineId?: string) => Promise<void>
  exportLogs: (executionId: string, format?: 'txt' | 'json' | 'csv') => void
  exportPipelineImage: (format?: 'png' | 'svg') => Promise<Blob | null>
  exportPipelineData: () => Promise<Blob | null>
  clearTimeline: () => void
  getNodeHistory: (nodeId: string) => TimelineEvent[]
  getSystemMetrics: () => SystemMetrics | null
  error: string | null
  loading: boolean
  reconnectAttempts: number
}

export interface SystemMetrics {
  totalCpuUsage: number
  totalMemoryUsage: number
  totalGpuUsage?: number
  activeNodes: number
  averageLatency: number
  throughput: number
  errorRate: number
  uptime: number
}

export function usePipelineMonitoring(
  options: UsePipelineMonitoringOptions = {}
): UsePipelineMonitoringReturn {
  const {
    pipelineId,
    autoConnect = true,
    pollInterval = 3000,
    enableResourceMonitoring = true,
    enablePerformanceTracking = true,
    resourceUpdateInterval = 1000,
    bufferSize = 1000
  } = options

  const [pipeline, setPipeline] = useState<PipelineStatus | null>(null)
  const [execution, setExecution] = useState<PipelineExecution | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [isPolling, setIsPolling] = useState(false)
  
  const pollTimer = useRef<NodeJS.Timeout | null>(null)
  const resourceTimer = useRef<NodeJS.Timeout | null>(null)
  const eventBuffer = useRef<TimelineEvent[]>([])
  const performanceBuffer = useRef<SystemMetrics[]>([])
  const metricsHistory = useRef<Map<string, number[]>>(new Map())
  const pollingUnsupportedRef = useRef(false)
  const wsDisabledWarnedRef = useRef(false)
  const wsErrorLoggedRef = useRef(false)
  const { data: session } = useSession()
  const fallbackUserIdRef = useRef<string>('anonymous')

  useEffect(() => {
    if (session?.user?.email || session?.user?.name) return
    if (typeof window === 'undefined') return
    const key = 'br:anonymous-user-id'
    const existing = window.localStorage.getItem(key)
    if (existing) {
      fallbackUserIdRef.current = existing
      return
    }
    const generated = `anon_${Math.random().toString(36).slice(2, 10)}`
    window.localStorage.setItem(key, generated)
    fallbackUserIdRef.current = generated
  }, [session?.user?.email, session?.user?.name])

  const resolvedWsBase = resolveRealtimeWsBaseUrl()
  const monitoringEnabled = Boolean(resolvedWsBase)
  const resolvedJobId = useMemo(() => {
    if (execution?.id) return execution.id
    if (pipelineId && pipelineId.startsWith('job_')) return pipelineId
    return undefined
  }, [execution?.id, pipelineId])
  const wsTargetReady = Boolean(resolvedJobId)

  const pipelineTypes = useMemo(
    () => new Set(['glm', 'connectivity', 'decoding', 'preprocessing', 'custom', 'pipeline_builder', 'chat', 'copilot']),
    []
  )

  const mapJobStatus = useCallback((status?: string): PipelineExecution['status'] => {
    const normalized = (status || '').toLowerCase()
    if (['pending', 'queued', 'claimed'].includes(normalized)) return 'queued'
    if (['running', 'retrying'].includes(normalized)) return 'running'
    if (['completed', 'succeeded'].includes(normalized)) return 'completed'
    if (['failed', 'error'].includes(normalized)) return 'failed'
    if (['cancelled', 'canceled'].includes(normalized)) return 'cancelled'
    if (normalized === 'paused') return 'paused'
    return 'running'
  }, [])

  const buildExecutionFromJob = useCallback(
    (job: any, fallbackPipelineId: string): PipelineExecution => {
      const resolvedJob = job?.job ? job.job : job
      const jobId =
        resolvedJob?.id ||
        resolvedJob?.job_id ||
        resolvedJob?.jobId ||
        resolvedJob?.run_id ||
        resolvedJob?.runId ||
        'unknown'
      const startedAt =
        resolvedJob?.started_at ||
        resolvedJob?.startedAt ||
        resolvedJob?.created_at ||
        resolvedJob?.createdAt
      const finishedAt = resolvedJob?.finished_at || resolvedJob?.finishedAt
      return {
        id: String(jobId),
        pipelineId: fallbackPipelineId,
        status: mapJobStatus(resolvedJob?.status || resolvedJob?.state),
        startTime: startedAt ? new Date(startedAt) : new Date(),
        endTime: finishedAt ? new Date(finishedAt) : undefined,
        nodes: {},
        logs: []
      }
    },
    [mapJobStatus]
  )

  useEffect(() => {
    pollingUnsupportedRef.current = false
  }, [pipelineId])

  // WebSocket connection for real-time updates
  // Memoize WebSocket options to prevent infinite re-render loop
  const wsOptions = useMemo(() => ({
    url: resolvedWsBase,
    documentId: resolvedJobId ? `jobs/${resolvedJobId}` : 'jobs/unknown',
    userId: session?.user?.email || session?.user?.name || fallbackUserIdRef.current,
    userName: session?.user?.name || session?.user?.email || 'Anonymous',
    autoConnect: autoConnect && monitoringEnabled && wsTargetReady,
    heartbeatInterval: 20000,
    maxReconnectAttempts: 6
  }), [
    autoConnect,
    monitoringEnabled,
    resolvedWsBase,
    resolvedJobId,
    wsTargetReady,
    session?.user?.email,
    session?.user?.name
  ])

  useEffect(() => {
    if (monitoringEnabled || wsDisabledWarnedRef.current) return
    wsDisabledWarnedRef.current = true
    console.info('Pipeline monitoring WebSocket disabled (no WebSocket endpoint resolved).')
  }, [monitoringEnabled])

  // Memoize WebSocket handlers to prevent infinite re-render loop
  const wsHandlers = useMemo(() => ({
    onConnect: () => {
      console.log('Pipeline monitoring WebSocket connected')
      wsErrorLoggedRef.current = false
      setError(null)
    },
    onDisconnect: () => {
      console.log('Pipeline monitoring WebSocket disconnected')
    },
    onError: (err: Event) => {
      if (!wsErrorLoggedRef.current) {
        wsErrorLoggedRef.current = true
        console.warn('Pipeline monitoring WebSocket error; retrying with backoff.')
      }
      setError('WebSocket connection error')
    },
    onReconnecting: (attempt: number) => {
      console.log(`Reconnecting to pipeline monitoring... Attempt ${attempt}`)
    },
    onReconnectFailed: () => {
      setError('Failed to reconnect to pipeline monitoring service')
    }
  }), []) // Empty deps - setError is stable from useState

  const {
    connectionState,
    isConnected,
    latency,
    reconnectAttempts,
    send: sendMessage,
    lastMessage,
    connect: connectWebSocket,
    disconnect: disconnectWebSocket
  } = useWebSocket(wsOptions, wsHandlers)

  // Subscribe to pipeline updates after connection
  useEffect(() => {
    if (isConnected && resolvedJobId) {
      sendMessage({
        type: 'subscribe',
        request_id: `req_${Date.now()}`,
        streams: [
          {
            stream: 'job',
            job_id: resolvedJobId,
            channels: [
              'graph',
              'timeline',
              ...(enableResourceMonitoring ? ['resources'] : []),
              ...(enablePerformanceTracking ? ['performance'] : [])
            ],
          }
        ]
      })
    }
  }, [isConnected, resolvedJobId, sendMessage, enableResourceMonitoring, enablePerformanceTracking])

  const applyGraphSnapshot = useCallback(
    (snapshot: any) => {
      if (!snapshot || !snapshot.nodes) return

      const nodes: Record<string, PipelineNodeData> = {}
      snapshot.nodes.forEach((node: any) => {
        const timing = node.timing || {}
        nodes[node.id] = {
          label: node.label || node.id,
          type: (node.type as PipelineNodeData['type']) || 'process',
          status: (node.status as PipelineNodeData['status']) || 'pending',
          progress: typeof node.progress === 'number' ? node.progress : undefined,
          startTime: timing.started_at ? new Date(timing.started_at) : undefined,
          endTime: timing.ended_at ? new Date(timing.ended_at) : undefined,
          duration: timing.duration_ms ?? undefined,
          resources: node.resources
            ? {
                cpu: node.resources.cpu_pct,
                memory: node.resources.memory_gb,
                gpu: node.resources.gpu_pct
              }
            : undefined,
          error: node.error?.message || undefined,
          metadata: node.meta ? { tool: node.meta.tool } : undefined
        }
      })

      const edges = (snapshot.edges || []).map((edge: any) => ({
        id: edge.id || `${edge.source}->${edge.target}`,
        source: edge.source,
        target: edge.target,
        type: 'smoothstep'
      }))

      const nodeStates = Object.values(nodes)
      const hasRunning = nodeStates.some(n => n.status === 'running')
      const hasFailed = nodeStates.some(n => n.status === 'failed')
      const allCompleted = nodeStates.length > 0 && nodeStates.every(n => n.status === 'completed')
      const hasPaused = nodeStates.some(n => n.status === 'paused')
      const status: PipelineStatus['status'] = hasRunning
        ? 'running'
        : hasFailed
          ? 'failed'
          : allCompleted
            ? 'completed'
            : hasPaused
              ? 'paused'
              : 'idle'

      const progress = nodeStates.length
        ? Math.round((nodeStates.filter(n => n.status === 'completed').length / nodeStates.length) * 100)
        : 0

      setPipeline(prev => ({
        id: snapshot.job_id || prev?.id || pipelineId || 'unknown',
        name: prev?.name || snapshot.plan?.plan_id || pipelineId || 'Pipeline',
        status,
        progress,
        nodes,
        edges,
        timeline: prev?.timeline || []
      }))

      setExecution(prev => ({
        id: snapshot.job_id || prev?.id || resolvedJobId || pipelineId || 'unknown',
        pipelineId: pipelineId || prev?.pipelineId || 'unknown',
        status:
          status === 'running'
            ? 'running'
            : status === 'failed'
              ? 'failed'
              : status === 'completed'
                ? 'completed'
                : status === 'paused'
                  ? 'paused'
                  : 'queued',
        startTime: prev?.startTime || new Date(),
        endTime: status === 'completed' ? new Date() : prev?.endTime,
        nodes,
        logs: prev?.logs || []
      }))
    },
    [pipelineId, resolvedJobId]
  )

  const applyGraphPatch = useCallback((patch: any) => {
    if (!patch) return
    setPipeline(prev => {
      if (!prev) return prev
      const nextNodes = { ...prev.nodes }
      const nextEdges = [...prev.edges]

      const upsertNode = (node: any) => {
        const existing: PipelineNodeData = nextNodes[node.id] || {
          label: node.label || node.id,
          type: (node.type as PipelineNodeData['type']) || 'process',
          status: (node.status as PipelineNodeData['status']) || 'pending'
        }
        const timing = node.timing || {}
        nextNodes[node.id] = {
          ...existing,
          ...node,
          label: node.label || existing.label,
          type: (node.type as PipelineNodeData['type']) || existing.type,
          status: (node.status as PipelineNodeData['status']) || existing.status,
          progress: node.progress ?? existing.progress,
          startTime: timing.started_at ? new Date(timing.started_at) : existing.startTime,
          endTime: timing.ended_at ? new Date(timing.ended_at) : existing.endTime,
          duration: timing.duration_ms ?? existing.duration,
          resources: node.resources
            ? {
                cpu: node.resources.cpu_pct ?? existing.resources?.cpu,
                memory: node.resources.memory_gb ?? existing.resources?.memory,
                gpu: node.resources.gpu_pct ?? existing.resources?.gpu
              }
            : existing.resources,
          error: node.error?.message ?? existing.error,
          metadata: node.meta ? { tool: node.meta.tool } : existing.metadata
        }
      }

      ;(patch.node_additions || []).forEach(upsertNode)
      ;(patch.node_updates || []).forEach((entry: any) => {
        const existing = nextNodes[entry.id]
        const merged = { ...(existing || {}), ...(entry.patch || {}) }
        upsertNode({ id: entry.id, ...merged })
      })
      ;(patch.node_removals || []).forEach((id: string) => {
        delete nextNodes[id]
      })

      ;(patch.edge_additions || []).forEach((edge: any) => {
        nextEdges.push({
          id: edge.id || `${edge.source}->${edge.target}`,
          source: edge.source,
          target: edge.target,
          type: 'smoothstep'
        })
      })
      ;(patch.edge_removals || []).forEach((id: string) => {
        const idx = nextEdges.findIndex(edge => edge.id === id)
        if (idx >= 0) nextEdges.splice(idx, 1)
      })

      return {
        ...prev,
        nodes: nextNodes,
        edges: nextEdges
      }
    })
  }, [])

  // Enhanced message handling with better error recovery
  useEffect(() => {
    if (!lastMessage) return

    try {
      const message = lastMessage as WebSocketMessage & {
        data?: {
          type?: string
          pipelineId?: string
          nodeId?: string
          execution?: PipelineExecution
          pipeline?: PipelineStatus
          event?: TimelineEvent
          progress?: number
          status?: string
          error?: string
          metrics?: SystemMetrics
          timestamp?: number
        }
      }

      if ((message as any).type === 'pipeline_snapshot') {
        const payload = (message as any).payload || (message as any).data?.payload
        applyGraphSnapshot(payload)
        return
      }

      if ((message as any).type === 'graph_patch') {
        const payload = (message as any).payload || (message as any).data?.payload
        applyGraphPatch(payload)
        return
      }

      const topLevelType = (message as any).type
      if (
        topLevelType === 'connection_info' ||
        topLevelType === 'hello' ||
        topLevelType === 'pong' ||
        topLevelType === 'ping' ||
        topLevelType === 'deprecation_notice'
      ) {
        return
      }

      if (!message.data) return

      switch (message.data.type) {
        case 'pipeline_status':
          if (message.data.pipeline) {
            setPipeline(prev => ({
              ...prev,
              ...message.data.pipeline,
              timeline: [...(prev?.timeline || []), ...(message.data.pipeline.timeline || [])].slice(-bufferSize)
            }))
          }
          break

        case 'execution_update':
          if (message.data.execution) {
            setExecution(message.data.execution)
          }
          break

        case 'node_progress':
          if (message.data.nodeId && message.data.progress !== undefined) {
            setPipeline(prev => {
              if (!prev) return null
              
              const updatedNode = {
                ...prev.nodes[message.data!.nodeId!],
                progress: message.data!.progress,
                status: 'running' as const,
                lastUpdate: new Date()
              }

              return {
                ...prev,
                nodes: {
                  ...prev.nodes,
                  [message.data!.nodeId!]: updatedNode
                }
              }
            })
          }
          break

        case 'node_status_change':
          if (message.data.nodeId && message.data.status) {
            setPipeline(prev => {
              if (!prev) return null
              
              const updatedNode = {
                ...prev.nodes[message.data!.nodeId!],
                status: message.data!.status as PipelineNodeData['status'],
                ...(message.data!.status === 'completed' && { progress: 100, endTime: new Date() }),
                ...(message.data!.status === 'failed' && { error: message.data!.error }),
                lastUpdate: new Date()
              }

              return {
                ...prev,
                nodes: {
                  ...prev.nodes,
                  [message.data!.nodeId!]: updatedNode
                }
              }
            })
          }
          break

        case 'resource_metrics':
          if (message.data.nodeId && enableResourceMonitoring) {
            const nodeId = message.data.nodeId
            const metrics = message.data.metrics || {}
            
            setPipeline(prev => {
              if (!prev || !prev.nodes[nodeId]) return prev
              
              return {
                ...prev,
                nodes: {
                  ...prev.nodes,
                  [nodeId]: {
                    ...prev.nodes[nodeId],
                    resources: {
                      ...prev.nodes[nodeId].resources,
                      ...metrics,
                      timestamp: new Date()
                    }
                  }
                }
              }
            })

            // Update metrics history
            Object.entries(metrics).forEach(([metric, value]) => {
              const key = `${nodeId}-${metric}`
              const history = metricsHistory.current.get(key) || []
              history.push(value as number)
              if (history.length > 100) history.shift() // Keep last 100 points
              metricsHistory.current.set(key, history)
            })
          }
          break

        case 'timeline_event':
          if (message.data.event) {
            const event = {
              ...message.data.event,
              timestamp: new Date(message.data.event.timestamp)
            }
            
            eventBuffer.current.push(event)
            if (eventBuffer.current.length > bufferSize) {
              eventBuffer.current.shift()
            }
            
            setPipeline(prev => {
              if (!prev) return null
              return {
                ...prev,
                timeline: [...prev.timeline, event].slice(-bufferSize)
              }
            })
          }
          break

        case 'system_metrics':
          if (message.data.metrics && enablePerformanceTracking) {
            performanceBuffer.current.push(message.data.metrics)
            if (performanceBuffer.current.length > 60) { // Keep 1 hour of data at 1-minute intervals
              performanceBuffer.current.shift()
            }
          }
          break

        case 'pipeline_error':
          setError(message.data.error || 'Unknown pipeline error')
          break

        default:
          if (message.data?.type) {
            console.log('Unhandled pipeline message:', message.data.type)
          }
      }
    } catch (err) {
      console.error('Error processing pipeline message:', err)
      setError('Failed to process pipeline update')
    }
  }, [
    lastMessage,
    bufferSize,
    enableResourceMonitoring,
    enablePerformanceTracking,
    applyGraphSnapshot,
    applyGraphPatch
  ])

  // Polling fallback with exponential backoff
  useEffect(() => {
    if (!monitoringEnabled || !pipelineId || isConnected || pollingUnsupportedRef.current) {
      setIsPolling(false)
      return
    }

    let attempts = 0
    const maxAttempts = 5
    setIsPolling(true)

    const poll = async () => {
      try {
        if (execution?.id) {
          const jobResponse = await orchestratorFetch(`/api/analyses/${execution.id}`, {
            headers: { 'Cache-Control': 'no-cache' }
          })
          if (jobResponse.ok) {
            const jobData = await jobResponse.json()
            setExecution(prev => ({
              ...buildExecutionFromJob(jobData, pipelineId),
              logs: prev?.logs ?? []
            }))
            attempts = 0
            setError(null)
            return
          }
        }

        const response = await orchestratorFetch(`/api/pipeline/${pipelineId}/status`, {
          headers: {
            'Cache-Control': 'no-cache'
          }
        })

        if (response.status === 404 || response.status === 405 || response.status === 501) {
          pollingUnsupportedRef.current = true
          if (pollTimer.current) {
            clearInterval(pollTimer.current)
          }
          setError(null)
          console.info('Pipeline status polling unsupported; disabling fallback polling.')
          return
        }

        if (response.ok) {
          const data = await response.json()
          if (data.pipeline) {
            setPipeline(data.pipeline)
          }

          if (data.execution) {
            setExecution(buildExecutionFromJob(data.execution, pipelineId))
          } else if (data.job_id) {
            setExecution(
              buildExecutionFromJob(
                { job_id: data.job_id, status: data.status || 'queued', created_at: data.created_at },
                pipelineId
              )
            )
          }

          attempts = 0 // Reset on success
          setError(null)
        } else {
          throw new Error(`HTTP ${response.status}: ${response.statusText}`)
        }
      } catch (err) {
        attempts++
        if (attempts >= maxAttempts && !pollingUnsupportedRef.current) {
          setError(`Polling failed after ${maxAttempts} attempts`)
        }
        console.error('Polling error:', err)
      }
    }

    poll() // Initial poll
    const interval = Math.min(pollInterval * Math.pow(1.5, attempts), 30000) // Max 30s
    pollTimer.current = setInterval(poll, interval)

    return () => {
      if (pollTimer.current) {
        clearInterval(pollTimer.current)
      }
      setIsPolling(false)
    }
  }, [
    pipelineId,
    isConnected,
    pollInterval,
    execution?.id,
    buildExecutionFromJob,
    monitoringEnabled
  ])

  // Resource monitoring timer
  useEffect(() => {
    if (!enableResourceMonitoring || !isConnected || !pipelineId) return

    const updateResources = () => {
      sendMessage({
        type: 'request_resource_update',
        data: { pipelineId }
      })
    }

    updateResources() // Initial request
    resourceTimer.current = setInterval(updateResources, resourceUpdateInterval)

    return () => {
      if (resourceTimer.current) {
        clearInterval(resourceTimer.current)
      }
    }
  }, [enableResourceMonitoring, isConnected, pipelineId, resourceUpdateInterval, sendMessage])

  const startPipeline = useCallback(async (pipelineId: string, parameters?: Record<string, any>) => {
    setLoading(true)
    setError(null)

    try {
      const trimmedPipelineId = pipelineId.trim()
      const normalizedPipeline = trimmedPipelineId.toLowerCase()
      const pipelineType = pipelineTypes.has(normalizedPipeline) ? normalizedPipeline : undefined

      let response: Response

      if (parameters && (parameters.nodes || parameters.edges)) {
        response = await orchestratorFetch('/pipeline/execute', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(parameters)
        })
      } else {
        const payload = {
          prompt: parameters?.prompt || `Execute pipeline ${trimmedPipelineId}`,
          pipeline: pipelineType || 'custom',
          parameters: {
            pipeline_id: trimmedPipelineId,
            ...parameters
          }
        }
        response = await orchestratorFetch('/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        })
      }

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({ message: response.statusText }))
        throw new Error(errorData.message || `Failed to start pipeline: ${response.statusText}`)
      }

      const data = await response.json()
      const nextExecution = data.job_id
        ? buildExecutionFromJob({ job_id: data.job_id, status: data.status || 'queued' }, trimmedPipelineId)
        : buildExecutionFromJob(data, trimmedPipelineId)

      setExecution(nextExecution)

      return nextExecution
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to start pipeline'
      setError(message)
      throw err
    } finally {
      setLoading(false)
    }
  }, [buildExecutionFromJob, pipelineTypes])

  const pausePipeline = useCallback(async (executionId: string) => {
    const response = await orchestratorFetch(
      `/api/analyses/${executionId}/cancel?reason=${encodeURIComponent('Paused by user')}`,
      { method: 'POST' }
    )
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ message: response.statusText }))
      throw new Error(errorData.message || `Failed to pause pipeline: ${response.statusText}`)
    }
  }, [])

  const resumePipeline = useCallback(async (executionId: string) => {
    const response = await orchestratorFetch(`/api/analyses/${executionId}/retry`, {
      method: 'POST'
    })
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ message: response.statusText }))
      throw new Error(errorData.message || `Failed to resume pipeline: ${response.statusText}`)
    }
  }, [])

  const cancelPipeline = useCallback(async (executionId: string) => {
    const response = await orchestratorFetch(
      `/api/analyses/${executionId}/cancel?reason=${encodeURIComponent('Cancelled by user')}`,
      { method: 'POST' }
    )
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ message: response.statusText }))
      throw new Error(errorData.message || `Failed to cancel pipeline: ${response.statusText}`)
    }
  }, [])

  const retryNode = useCallback(async (executionId: string, nodeId: string) => {
    const response = await orchestratorFetch(`/api/analyses/${executionId}/retry`, {
      method: 'POST'
    })
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ message: response.statusText }))
      throw new Error(errorData.message || `Failed to retry node ${nodeId}: ${response.statusText}`)
    }
  }, [])

  const retryPipeline = useCallback(async (overridePipelineId?: string) => {
    if (!execution) throw new Error('No execution to retry')

    const response = await orchestratorFetch(`/api/analyses/${execution.id}/retry`, {
      method: 'POST'
    })

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ message: response.statusText }))
      throw new Error(errorData.message || `Failed to retry pipeline: ${response.statusText}`)
    }

    const data = await response.json().catch(() => ({}))
    setExecution(
      buildExecutionFromJob(
        { ...data, job_id: execution.id },
        overridePipelineId || pipelineId || execution.pipelineId
      )
    )
    return data
  }, [execution, pipelineId, buildExecutionFromJob])

  const exportLogs = useCallback((executionId: string, format: 'txt' | 'json' | 'csv' = 'txt') => {
    if (!execution?.logs) return

    let content: string
    let mimeType: string
    let extension: string

    switch (format) {
      case 'json':
        content = JSON.stringify(execution.logs, null, 2)
        mimeType = 'application/json'
        extension = 'json'
        break
      case 'csv':
        const headers = 'Timestamp,Node ID,Level,Message\n'
        const rows = execution.logs
          .map(log => `"${log.timestamp?.toISOString?.() || new Date().toISOString()}","${log.nodeId || 'unknown'}","${log.level || 'info'}","${(log.message || '').replace(/"/g, '""')}"`)
          .join('\n')
        content = headers + rows
        mimeType = 'text/csv'
        extension = 'csv'
        break
      default: // txt
        content = execution.logs
          .map(log => `[${log.timestamp?.toISOString?.() || new Date().toISOString()}] ${(log.level || 'INFO').toUpperCase()} [${log.nodeId || 'unknown'}]: ${log.message || ''}`)
          .join('\n')
        mimeType = 'text/plain'
        extension = 'txt'
    }

    const blob = new Blob([content], { type: mimeType })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.download = `pipeline-${executionId}-logs.${extension}`
    link.href = url
    document.body.appendChild(link)
    link.click()
    document.body.removeChild(link)
    URL.revokeObjectURL(url)
  }, [execution])

  const exportPipelineImage = useCallback(async (format: 'png' | 'svg' = 'png'): Promise<Blob | null> => {
    try {
      const element = document.querySelector('.react-flow') as HTMLElement
      if (!element) return null

      if (format === 'svg') {
        const { toSvg } = await import('html-to-image')
        const dataUrl = await toSvg(element, {
          backgroundColor: 'white',
          width: 1400,
          height: 900,
          style: {
            transform: 'scale(1)',
            transformOrigin: 'top left'
          }
        })
        const response = await fetch(dataUrl)
        return await response.blob()
      } else {
        const { toPng } = await import('html-to-image')
        const dataUrl = await toPng(element, {
          backgroundColor: 'white',
          width: 1400,
          height: 900,
          pixelRatio: 2
        })
        const response = await fetch(dataUrl)
        return await response.blob()
      }
    } catch (err) {
      console.error('Failed to export pipeline image:', err)
      setError('Failed to export pipeline image')
      return null
    }
  }, [])

  const exportPipelineData = useCallback(async (): Promise<Blob | null> => {
    try {
      const exportData = {
        pipeline,
        execution,
        timeline: eventBuffer.current,
        performance: performanceBuffer.current,
        metricsHistory: Object.fromEntries(metricsHistory.current),
        exportedAt: new Date().toISOString(),
        version: '1.0.0'
      }

      const blob = new Blob([JSON.stringify(exportData, null, 2)], { 
        type: 'application/json' 
      })
      return blob
    } catch (err) {
      console.error('Failed to export pipeline data:', err)
      setError('Failed to export pipeline data')
      return null
    }
  }, [pipeline, execution])

  const clearTimeline = useCallback(() => {
    eventBuffer.current = []
    setPipeline(prev => prev ? { ...prev, timeline: [] } : null)
  }, [])

  const getNodeHistory = useCallback((nodeId: string): TimelineEvent[] => {
    return eventBuffer.current.filter(event => event.nodeId === nodeId)
  }, [])

  const getSystemMetrics = useCallback((): SystemMetrics | null => {
    if (!pipeline || !enablePerformanceTracking) return null

    const nodes = Object.values(pipeline.nodes)
    const runningNodes = nodes.filter(n => n.status === 'running' || n.status === 'completed')
    
    if (runningNodes.length === 0) return null

    const totalCpuUsage = runningNodes.reduce((sum, n) => sum + (n.resources?.cpu || 0), 0) / runningNodes.length
    const totalMemoryUsage = runningNodes.reduce((sum, n) => sum + (n.resources?.memory || 0), 0) / runningNodes.length
    const totalGpuUsage = runningNodes
      .filter(n => n.resources?.gpu !== undefined)
      .reduce((sum, n) => sum + (n.resources?.gpu || 0), 0) / 
      Math.max(1, runningNodes.filter(n => n.resources?.gpu !== undefined).length)

    const errorEvents = pipeline.timeline.filter(e => e.type === 'error').length
    const totalEvents = pipeline.timeline.length
    const errorRate = totalEvents > 0 ? (errorEvents / totalEvents) * 100 : 0

    const uptime = pipeline.startTime ? Date.now() - pipeline.startTime.getTime() : 0

    return {
      totalCpuUsage,
      totalMemoryUsage,
      totalGpuUsage: totalGpuUsage > 0 ? totalGpuUsage : undefined,
      activeNodes: runningNodes.length,
      averageLatency: latency,
      throughput: pipeline.timeline.length / Math.max(1, uptime / 60000), // events per minute
      errorRate,
      uptime
    }
  }, [pipeline, latency, enablePerformanceTracking])

  const transportMode: UsePipelineMonitoringReturn['transportMode'] = !monitoringEnabled
    ? 'disabled'
    : isConnected
      ? 'ws'
      : isPolling
        ? 'polling'
        : wsTargetReady
          ? 'disconnected'
          : 'waiting'

  // Cleanup on unmount
  useEffect(() => {
    const pollInterval = pollTimer.current
    const resourceInterval = resourceTimer.current
    const metricsHistoryMap = metricsHistory.current

    return () => {
      if (pollInterval) clearInterval(pollInterval)
      if (resourceInterval) clearInterval(resourceInterval)

      eventBuffer.current = []
      performanceBuffer.current = []
      metricsHistoryMap.clear()
    }
  }, [])

  return {
    pipeline,
    execution,
    monitoringEnabled,
    wsTargetReady,
    transportMode,
    isConnected,
    connectionState,
    latency,
    // Expose reconnect controls
    reconnect: async () => {
      if (!monitoringEnabled || !wsTargetReady) return
      try {
        await connectWebSocket()
      } catch (e) {
        console.error('Reconnect failed:', e)
      }
    },
    disconnect: () => disconnectWebSocket(),
    startPipeline,
    pausePipeline,
    resumePipeline,
    cancelPipeline,
    retryNode,
    retryPipeline,
    exportLogs,
    exportPipelineImage,
    exportPipelineData,
    clearTimeline,
    getNodeHistory,
    getSystemMetrics,
    error,
    loading,
    reconnectAttempts
  }
}
