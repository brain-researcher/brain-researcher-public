'use client'

import React, { useState, useEffect, useRef } from 'react'
import { CheckCircle, Circle, Clock, AlertCircle, X, ChevronDown, ChevronUp, Loader2 } from 'lucide-react'

interface ProgressStep {
  id: string
  name: string
  status: 'pending' | 'running' | 'completed' | 'error'
  startTime?: number
  endTime?: number
  estimatedDuration?: number
  message?: string
  details?: string[]
}

interface RealTimeProgressProps {
  jobId: string
  onCancel?: () => void
  onComplete?: (result: any) => void
  onError?: (error: any) => void
  sseEndpoint?: string
  pollingEndpoint?: string
  pollingInterval?: number
}

type MilestoneEvent = {
  stage?: string
  status?: string
  percent?: number
  step?: { index?: number; id?: string; name?: string }
}

function formatStage(stage?: string): string {
  const normalized = typeof stage === 'string' ? stage.trim().toLowerCase() : ''
  switch (normalized) {
    case 'data_check':
      return 'Data check'
    case 'preprocess':
      return 'Preprocess'
    case 'model':
      return 'Model'
    case 'stats':
      return 'Stats'
    case 'report':
      return 'Report'
    case 'complete':
      return 'Complete'
    case 'error':
      return 'Error'
    default:
      return '—'
  }
}

function normalizeStepStatus(value: unknown): ProgressStep['status'] {
  const normalized = typeof value === 'string' ? value.trim().toLowerCase() : ''
  if (['completed', 'succeeded', 'success', 'done'].includes(normalized)) return 'completed'
  if (['failed', 'error', 'timeout', 'cancelled', 'canceled'].includes(normalized)) return 'error'
  if (['running', 'retrying', 'claimed', 'in_progress'].includes(normalized)) return 'running'
  return 'pending'
}

function coerceTimestampMs(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) {
    // Heuristic: treat small ints as seconds, large as ms.
    return value < 1e12 ? value * 1000 : value
  }
  if (typeof value === 'string' && value.trim()) {
    const parsed = Date.parse(value)
    if (!Number.isNaN(parsed)) return parsed
  }
  return undefined
}

export function RealTimeProgress({
  jobId,
  onCancel,
  onComplete,
  onError,
  sseEndpoint: sseEndpointInput,
  pollingEndpoint: pollingEndpointInput,
  pollingInterval = 2000
}: RealTimeProgressProps) {
  const [steps, setSteps] = useState<ProgressStep[]>([])
  const [totalProgress, setTotalProgress] = useState(0)
  const [eta, setEta] = useState<string | null>(null)
  const [isConnected, setIsConnected] = useState(false)
  const [usePolling, setUsePolling] = useState(false)
  const [expandedSteps, setExpandedSteps] = useState<Set<string>>(new Set())
  const [isCancelling, setIsCancelling] = useState(false)
  const [milestone, setMilestone] = useState<MilestoneEvent | null>(null)
  // Client-side time for SSR-safe duration calculations (prevents hydration mismatch)
  const [clientNow, setClientNow] = useState<number | null>(null)

  const eventSourceRef = useRef<EventSource | null>(null)
  const gracefulCloseRef = useRef(false)
  const pollingIntervalRef = useRef<NodeJS.Timeout | null>(null)

  const resolvedSseEndpoint =
    sseEndpointInput ?? '/api/analyses/{jobId}/stream'
  const resolvedPollingEndpoint =
    pollingEndpointInput ?? '/api/analyses/{jobId}'

  const buildSseUrl = (endpoint: string, id: string) => {
    if (endpoint.includes('{jobId}')) {
      return endpoint.replace('{jobId}', encodeURIComponent(id))
    }
    // Legacy style: endpoint already ends with /stream and expects ?jobId= param
    if (endpoint.endsWith('/stream')) {
      return `${endpoint}?jobId=${encodeURIComponent(id)}`
    }
    // Assume endpoint is base jobs URL
    const base = endpoint.endsWith('/') ? endpoint.slice(0, -1) : endpoint
    return `${base}/${encodeURIComponent(id)}/stream`
  }

  const buildPollUrl = (endpoint: string, id: string) => {
    if (endpoint.includes('{jobId}')) {
      return endpoint.replace('{jobId}', encodeURIComponent(id))
    }
    // Assume endpoint is base jobs URL
    const base = endpoint.endsWith('/') ? endpoint.slice(0, -1) : endpoint
    return `${base}/${encodeURIComponent(id)}`
  }

  const handleProgressUpdate = React.useCallback(
    (raw: any) => {
      const payload = raw?.data ? raw.data : raw
      const jobData = payload?.job ?? payload
      if (!jobData) {
        return
      }

      const stepPayload = Array.isArray(jobData.step_progress)
        ? jobData.step_progress
        : Array.isArray(jobData.steps)
        ? jobData.steps
        : undefined

      if (Array.isArray(stepPayload)) {
        setSteps(
          stepPayload.map((step: any, index: number) => ({
            id: step.id ?? `step-${index}`,
            name: step.name ?? `Step ${index + 1}`,
            status: normalizeStepStatus(step.status ?? step.state ?? step.status_code ?? 'pending'),
            startTime: coerceTimestampMs(step.start_time ?? step.started_at ?? step.startTime),
            endTime: coerceTimestampMs(step.end_time ?? step.finished_at ?? step.endTime),
            estimatedDuration: step.duration ?? step.estimated_duration,
            message: step.message ?? step.description ?? undefined,
            details: step.details ?? undefined,
          }))
        )
      }

      const progressValue =
        typeof jobData.overall_progress === 'number'
          ? jobData.overall_progress
          : typeof jobData.progress === 'number'
            ? jobData.progress
            : undefined
      if (typeof progressValue === 'number') {
        setTotalProgress(Number(progressValue.toFixed(1)))
      }

      const remainingSeconds =
        jobData.time_estimates?.estimated_remaining ?? jobData.estimated_remaining
      if (typeof remainingSeconds === 'number') {
        if (remainingSeconds <= 0) {
          setEta(null)
        } else {
          const minutes = Math.floor(remainingSeconds / 60)
          const seconds = Math.floor(remainingSeconds % 60)
          setEta(minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`)
        }
      } else if (jobData.eta) {
        const etaDate = new Date(jobData.eta)
        const diff = etaDate.getTime() - Date.now()
        if (diff > 0) {
          const minutes = Math.floor(diff / 60000)
          const seconds = Math.floor((diff % 60000) / 1000)
          setEta(minutes > 0 ? `${minutes}m ${seconds}s` : `${seconds}s`)
        }
      }

      const statusValue = jobData.status ?? jobData.current_status
      if (statusValue) {
        const normalizedStatus = typeof statusValue === 'string' ? statusValue.toLowerCase() : statusValue
        if (['completed', 'succeeded', 'failed', 'cancelled', 'canceled', 'timeout', 'skipped'].includes(String(normalizedStatus))) {
          gracefulCloseRef.current = true
          setIsConnected(false)
          if (eventSourceRef.current) {
            eventSourceRef.current.close()
            eventSourceRef.current = null
          }
          setUsePolling(false)
        }

        if ((normalizedStatus === 'completed' || normalizedStatus === 'succeeded') && onComplete) {
          onComplete(jobData.result)
        } else if ((normalizedStatus === 'failed' || normalizedStatus === 'timeout') && onError) {
          onError(jobData.error ?? new Error('Job failed'))
        } else if ((normalizedStatus === 'cancelled' || normalizedStatus === 'canceled') && onCancel) {
          onCancel()
        }
      }

      if (typeof window !== 'undefined' && (window as any).trackEvent) {
        (window as any).trackEvent('progress_update', {
          job_id: jobId,
          status: statusValue,
          progress: progressValue,
        })
      }
    },
    [jobId, onCancel, onComplete, onError]
  )

  // Reset graceful-close tracker when job changes
  useEffect(() => {
    gracefulCloseRef.current = false
    setMilestone(null)
    setSteps([])
    setTotalProgress(0)
    setEta(null)
    setExpandedSteps(new Set())
    setIsConnected(false)
    setUsePolling(false)
  }, [jobId])

  // Initialize and update client-side time for SSR-safe duration calculations
  useEffect(() => {
    setClientNow(Date.now())
    const interval = setInterval(() => setClientNow(Date.now()), 1000)
    return () => clearInterval(interval)
  }, [])

  // SSE Connection
  useEffect(() => {
    if (!jobId || usePolling) return

    const connectSSE = () => {
      try {
        const url = buildSseUrl(resolvedSseEndpoint, jobId)
        const eventSource = new EventSource(url)
        eventSourceRef.current = eventSource

        const handleEvent = (event: MessageEvent) => {
          try {
            const data = JSON.parse(event.data)
            handleProgressUpdate(data)
          } catch (error) {
            console.error('Error parsing SSE data:', error)
          }
        }

        eventSource.onopen = () => {
          setIsConnected(true)
          console.log('SSE connected for job:', jobId)
        }

        eventSource.onmessage = handleEvent
        eventSource.addEventListener('initial_state', handleEvent as EventListener)
        eventSource.addEventListener('progress_update', handleEvent as EventListener)
        eventSource.addEventListener('milestone', ((event: MessageEvent) => {
          try {
            const data = JSON.parse(event.data) as MilestoneEvent
            setMilestone(data)
          } catch {
            // ignore
          }
        }) as EventListener)
        eventSource.addEventListener('job_complete', (event: MessageEvent) => {
          handleEvent(event)
          gracefulCloseRef.current = true
          eventSource.close()
          eventSourceRef.current = null
        })

        eventSource.onerror = (error) => {
          const readyState = eventSourceRef.current?.readyState
          const closed = readyState === EventSource.CLOSED || readyState === 2
          const connectionReleased = !eventSourceRef.current

          if (gracefulCloseRef.current || closed || connectionReleased) {
            console.debug('RealTimeProgress SSE closed after completion')
            eventSource.close()
            eventSourceRef.current = null
            setIsConnected(false)
            return
          }

          console.error('SSE error:', error)
          setIsConnected(false)
          eventSource.close()
          eventSourceRef.current = null

          // Fallback to polling
          setUsePolling(true)
        }

        return () => {
          eventSource.close()
          eventSourceRef.current = null
        }
      } catch (error) {
        console.error('Failed to establish SSE connection:', error)
        setUsePolling(true)
      }
    }

    const cleanup = connectSSE()
    return cleanup
  }, [handleProgressUpdate, jobId, resolvedSseEndpoint, usePolling])

  // Polling Fallback
  useEffect(() => {
    if (!jobId || !usePolling) return

    const basePollUrl = buildPollUrl(resolvedPollingEndpoint, jobId)
    const progressUrl = basePollUrl.endsWith('/progress')
      ? basePollUrl
      : `${basePollUrl}/progress`

    const pollProgress = async () => {
      try {
        const response = await fetch(progressUrl)
        if (response.ok) {
          const data = await response.json()
          handleProgressUpdate(data)
        }
      } catch (error) {
        console.error('Polling error:', error)
      }
    }

    // Initial poll
    pollProgress()
    
    // Set up interval
    pollingIntervalRef.current = setInterval(pollProgress, pollingInterval)

    return () => {
      if (pollingIntervalRef.current) {
        clearInterval(pollingIntervalRef.current)
      }
    }
  }, [handleProgressUpdate, jobId, usePolling, resolvedPollingEndpoint, pollingInterval])

  const handleCancel = async () => {
    if (isCancelling) return
    
    setIsCancelling(true)
    
    try {
      const basePollUrl = buildPollUrl(resolvedPollingEndpoint, jobId)
      const cancelUrl = basePollUrl.endsWith('/progress')
        ? basePollUrl.replace(/\/progress$/, '')
        : basePollUrl
      const response = await fetch(`${cancelUrl}/cancel`, {
        method: 'POST'
      })
      
      if (response.ok && onCancel) {
        onCancel()
      }
      
      // Track cancellation
      if (typeof window !== 'undefined' && (window as any).trackEvent) {
        (window as any).trackEvent('job_cancelled', {
          job_id: jobId,
          progress: totalProgress
        })
      }
    } catch (error) {
      console.error('Failed to cancel job:', error)
    } finally {
      setIsCancelling(false)
    }
  }

  const toggleStepExpansion = (stepId: string) => {
    setExpandedSteps(prev => {
      const next = new Set(prev)
      if (next.has(stepId)) {
        next.delete(stepId)
      } else {
        next.add(stepId)
      }
      return next
    })
  }

  const getStepIcon = (status: ProgressStep['status']) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="h-5 w-5 text-green-500" />
      case 'running':
        return <Loader2 className="h-5 w-5 text-blue-500 animate-spin" />
      case 'error':
        return <AlertCircle className="h-5 w-5 text-red-500" />
      default:
        return <Circle className="h-5 w-5 text-gray-300" />
    }
  }

  const getStepDuration = (step: ProgressStep) => {
    if (step.startTime && step.endTime) {
      const duration = (step.endTime - step.startTime) / 1000
      return `${duration.toFixed(1)}s`
    } else if (step.startTime && clientNow) {
      // Use clientNow (SSR-safe) instead of Date.now() to prevent hydration mismatch
      const duration = (clientNow - step.startTime) / 1000
      return `${duration.toFixed(1)}s`
    } else if (step.estimatedDuration) {
      return `~${step.estimatedDuration}s`
    }
    return null
  }

  return (
    <div className="bg-white rounded-lg shadow-lg border border-gray-200 overflow-hidden">
      {/* Header */}
      <div className="px-6 py-4 border-b border-gray-200 bg-gradient-to-r from-blue-50 to-purple-50">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h3 className="text-lg font-semibold text-gray-900">Processing</h3>
            {isConnected && !usePolling && (
              <span className="px-2 py-1 bg-green-100 text-green-700 text-xs rounded-full flex items-center gap-1">
                <span className="w-2 h-2 bg-green-500 rounded-full animate-pulse" />
                Live
              </span>
            )}
            {usePolling && (
              <span className="px-2 py-1 bg-yellow-100 text-yellow-700 text-xs rounded-full">
                Polling
              </span>
            )}
          </div>
          
          <button
            onClick={handleCancel}
            disabled={isCancelling}
            className="p-2 text-gray-500 hover:text-gray-700 hover:bg-gray-100 rounded-lg transition-colors disabled:opacity-50"
            title="Cancel"
          >
            {isCancelling ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <X className="h-4 w-4" />
            )}
          </button>
        </div>
      </div>

      {/* Progress Bar */}
      <div className="px-6 py-4 border-b border-gray-200">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-gray-700">Overall Progress</span>
          <div className="flex items-center gap-3">
            {eta && (
              <span className="text-sm text-gray-500 flex items-center gap-1">
                <Clock className="h-3 w-3" />
                ETA: {eta}
              </span>
            )}
            <span className="text-sm font-medium text-gray-900">{totalProgress}%</span>
          </div>
        </div>
        
        <div className="w-full bg-gray-200 rounded-full h-2 overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-blue-500 to-purple-500 transition-all duration-300 ease-out"
            style={{ width: `${totalProgress}%` }}
          />
        </div>
        {milestone?.stage ? (
          <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-xs text-gray-600">
            <span>Stage: {formatStage(milestone.stage)}</span>
            {milestone.step?.name ? <span>• {milestone.step.name}</span> : null}
          </div>
        ) : null}
      </div>

      {/* Steps */}
      <div className="px-6 py-4 space-y-3 max-h-96 overflow-y-auto">
        {steps.length === 0 ? (
          <div className="flex items-center justify-center py-10 text-sm text-muted-foreground">
            <div className="flex items-center gap-2">
              {(isConnected || usePolling) && (
                <Loader2 className="h-4 w-4 animate-spin text-gray-400" />
              )}
              <span>
                {isConnected || usePolling
                  ? 'Waiting for step updates…'
                  : 'No step data yet.'}
              </span>
            </div>
          </div>
        ) : (
          steps.map((step, index) => {
          const isExpanded = expandedSteps.has(step.id)
          const duration = getStepDuration(step)
          
          return (
            <div key={step.id} className="relative">
              {/* Connection Line */}
              {index < steps.length - 1 && (
                <div className="absolute left-2.5 top-8 w-0.5 h-full bg-gray-200" />
              )}
              
              <div
                className={`relative bg-white rounded-lg border transition-all ${
                  step.status === 'running'
                    ? 'border-blue-200 shadow-sm'
                    : step.status === 'error'
                    ? 'border-red-200'
                    : step.status === 'completed'
                    ? 'border-green-200'
                    : 'border-gray-200'
                }`}
              >
                <button
                  onClick={() => step.details && toggleStepExpansion(step.id)}
                  className="w-full px-4 py-3 flex items-center gap-3 text-left hover:bg-gray-50 transition-colors"
                  disabled={!step.details}
                >
                  {getStepIcon(step.status)}
                  
                  <div className="flex-1">
                    <div className="flex items-center justify-between">
                      <p className={`font-medium ${
                        step.status === 'running' ? 'text-blue-700' :
                        step.status === 'error' ? 'text-red-700' :
                        step.status === 'completed' ? 'text-green-700' :
                        'text-gray-500'
                      }`}>
                        {step.name}
                      </p>
                      
                      {duration && (
                        <span className="text-xs text-gray-500">{duration}</span>
                      )}
                    </div>
                    
                    {step.message && (
                      <p className="text-sm text-gray-600 mt-0.5">{step.message}</p>
                    )}
                  </div>
                  
                  {step.details && (
                    <div className="ml-auto">
                      {isExpanded ? (
                        <ChevronUp className="h-4 w-4 text-gray-400" />
                      ) : (
                        <ChevronDown className="h-4 w-4 text-gray-400" />
                      )}
                    </div>
                  )}
                </button>
                
                {/* Expanded Details */}
                {isExpanded && step.details && (
                  <div className="px-4 pb-3 border-t border-gray-100">
                    <ul className="mt-2 space-y-1">
                      {step.details.map((detail, i) => (
                        <li key={i} className="text-sm text-gray-600 flex items-start gap-2">
                          <span className="text-gray-400 mt-0.5">•</span>
                          <span>{detail}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </div>
          )
        })
        )}
      </div>

      {/* Footer */}
      <div className="px-6 py-3 border-t border-gray-200 bg-gray-50">
        <p className="text-xs text-gray-500 text-center">
          Job ID: <span className="font-mono">{jobId}</span>
        </p>
      </div>
    </div>
  )
}
