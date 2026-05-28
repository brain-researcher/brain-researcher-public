'use client'

import React, { useState, useEffect, useRef, useCallback } from 'react'
import { 
  Activity, CheckCircle, XCircle, AlertCircle,
  Clock, Cpu, Loader2, Pause, Play, X
} from 'lucide-react'
import { serviceEndpoints } from '@/lib/service-endpoints'

interface ProgressStep {
  id: string
  name: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'skipped'
  progress: number
  startTime?: Date
  endTime?: Date
  duration?: number
  error?: string
}

interface RealtimeProgressProps {
  jobId: string
  onComplete?: (result: any) => void
  onError?: (error: Error) => void
  onCancel?: () => void
  allowCancel?: boolean
  sseUrl?: string
  fallbackPollInterval?: number
}

export function RealtimeProgress({
  jobId,
  onComplete,
  onError,
  onCancel,
  allowCancel = true,
  sseUrl,
  fallbackPollInterval = 2000
}: RealtimeProgressProps) {
  const [steps, setSteps] = useState<ProgressStep[]>([])
  const [overallProgress, setOverallProgress] = useState(0)
  const [status, setStatus] = useState<'connecting' | 'running' | 'completed' | 'failed' | 'cancelled'>('connecting')
  const [estimatedTime, setEstimatedTime] = useState<number | null>(null)
  const [elapsedTime, setElapsedTime] = useState(0)
  const [connectionType, setConnectionType] = useState<'sse' | 'polling'>('sse')
  const [isPaused, setIsPaused] = useState(false)
  
  const eventSourceRef = useRef<EventSource | null>(null)
  const pollingIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const startTimeRef = useRef<Date>(new Date())
  const elapsedIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const gracefulCloseRef = useRef(false)

  // Initialize SSE connection
  const jobsBaseUrl = (sseUrl ?? serviceEndpoints.orchestratorApi('/jobs')).replace(/\/$/, '')
  const cancelBaseUrl = jobsBaseUrl

  const stopPolling = useCallback(() => {
    if (pollingIntervalRef.current) {
      clearInterval(pollingIntervalRef.current)
      pollingIntervalRef.current = null
    }
  }, [])

  const handleProgressUpdate = useCallback(
    (raw: any) => {
      const data = raw?.data ? raw.data : raw
      const jobData = data?.job ?? data
      if (!jobData) {
        return
      }

      const incomingSteps: ProgressStep[] | undefined = Array.isArray(jobData.step_progress)
        ? jobData.step_progress.map((step: any) => ({
            id: step.id ?? `${step.name ?? 'step'}-${Math.random().toString(36).slice(2, 8)}`,
            name: step.name ?? 'Step',
            status: step.status ?? 'pending',
            progress: Number(step.progress ?? 0),
            startTime: step.start_time ? new Date(step.start_time) : undefined,
            endTime: step.end_time ? new Date(step.end_time) : undefined,
            duration: step.duration ?? undefined,
            error: step.error ?? undefined,
          }))
        : Array.isArray(jobData.steps)
          ? jobData.steps
          : undefined

      if (incomingSteps) {
        setSteps(incomingSteps)
      }

      const progressValue =
        typeof jobData.overall_progress === 'number'
          ? jobData.overall_progress
          : typeof jobData.progress === 'number'
            ? jobData.progress
            : undefined
      if (typeof progressValue === 'number') {
        setOverallProgress(Number(progressValue.toFixed(1)))
      }

      const estimated = jobData.time_estimates?.estimated_remaining ?? jobData.estimatedTime
      if (typeof estimated === 'number') {
        setEstimatedTime(Math.max(0, Math.round(estimated)))
      }

      const statusValue = jobData.status ?? jobData.current_status
      if (statusValue) {
        const normalizedStatus: typeof status =
          statusValue === 'completed'
            ? 'completed'
            : statusValue === 'failed'
              ? 'failed'
              : statusValue === 'cancelled'
                ? 'cancelled'
                : statusValue === 'connecting'
                  ? 'connecting'
                  : 'running'
        setStatus(normalizedStatus)
        if (['completed', 'failed', 'cancelled'].includes(statusValue)) {
          gracefulCloseRef.current = true
          stopPolling()
          if (eventSourceRef.current) {
            eventSourceRef.current.close()
            eventSourceRef.current = null
          }
        }

        if (statusValue === 'completed' && onComplete) {
          onComplete(jobData.result)
        } else if (statusValue === 'failed' && onError) {
          onError(new Error(jobData.error || 'Job failed'))
        }
      }
    },
    [onComplete, onError, stopPolling]
  )

  const startPolling = useCallback(() => {
    gracefulCloseRef.current = false
    if (pollingIntervalRef.current) return

    setConnectionType('polling')
    setStatus('running')

    const poll = async () => {
      try {
        const response = await fetch(`${jobsBaseUrl}/${jobId}/progress`)
        if (response.ok) {
          const data = await response.json()
          handleProgressUpdate(data)
        }
      } catch (err) {
        console.error('Polling error:', err)
      }
    }

    poll() // Initial poll
    pollingIntervalRef.current = setInterval(poll, fallbackPollInterval)
  }, [jobId, jobsBaseUrl, fallbackPollInterval, handleProgressUpdate])

  const connectSSE = useCallback(() => {
    if (eventSourceRef.current) return

    try {
      gracefulCloseRef.current = false
      const eventSource = new EventSource(`${jobsBaseUrl}/${jobId}/stream`)
      eventSourceRef.current = eventSource
      setConnectionType('sse')
      setStatus('running')

      eventSource.onopen = () => {
        console.log('SSE connection opened')
      }

      const handleEvent = (event: MessageEvent) => {
        try {
          const data = JSON.parse(event.data)
          handleProgressUpdate(data)
        } catch (err) {
          console.error('Failed to parse SSE data:', err)
        }
      }

      eventSource.onmessage = handleEvent
      eventSource.addEventListener('initial_state', handleEvent as EventListener)
      eventSource.addEventListener('progress_update', handleEvent as EventListener)
      eventSource.addEventListener('job_complete', (event: MessageEvent) => {
        handleEvent(event)
        gracefulCloseRef.current = true
        eventSource.close()
        eventSourceRef.current = null
      })

      eventSource.onerror = (err) => {
        const readyState = eventSourceRef.current?.readyState
        const closed = readyState === EventSource.CLOSED || readyState === 2
        const connectionReleased = !eventSourceRef.current

        if (gracefulCloseRef.current || closed || connectionReleased) {
          console.debug('Progress SSE closed after completion')
          eventSource.close()
          eventSourceRef.current = null
          return
        }

        console.error('SSE error:', err)
        eventSource.close()
        eventSourceRef.current = null

        // Fallback to polling
        startPolling()
      }
    } catch (err) {
      console.error('Failed to establish SSE connection:', err)
      startPolling()
    }
  }, [jobId, jobsBaseUrl, handleProgressUpdate, startPolling])

  // Track elapsed time
  useEffect(() => {
    elapsedIntervalRef.current = setInterval(() => {
      if (status === 'running' && !isPaused) {
        const elapsed = Math.floor((Date.now() - startTimeRef.current.getTime()) / 1000)
        setElapsedTime(elapsed)
      }
    }, 1000)

    return () => {
      if (elapsedIntervalRef.current) {
        clearInterval(elapsedIntervalRef.current)
      }
    }
  }, [status, isPaused])

  // Initialize connection
  useEffect(() => {
    connectSSE()

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close()
      }
      stopPolling()
    }
  }, [connectSSE, stopPolling])

  // Handle cancel
  const handleCancel = async () => {
    try {
      await fetch(`${cancelBaseUrl}/${jobId}/cancel`, { method: 'POST' })
      setStatus('cancelled')
      onCancel?.()
    } catch (err) {
      console.error('Failed to cancel job:', err)
    }
  }

  // Format time
  const formatTime = (seconds: number) => {
    const mins = Math.floor(seconds / 60)
    const secs = seconds % 60
    return `${mins}:${secs.toString().padStart(2, '0')}`
  }

  // Calculate ETA
  const calculateETA = () => {
    if (!estimatedTime) return null
    const remaining = Math.max(0, estimatedTime - elapsedTime)
    return formatTime(remaining)
  }

  // Get status icon
  const getStatusIcon = (stepStatus: string) => {
    switch (stepStatus) {
      case 'completed':
        return <CheckCircle className="h-5 w-5 text-green-500" />
      case 'failed':
        return <XCircle className="h-5 w-5 text-red-500" />
      case 'running':
        return <Loader2 className="h-5 w-5 text-blue-500 animate-spin" />
      case 'skipped':
        return <AlertCircle className="h-5 w-5 text-gray-400" />
      default:
        return <Clock className="h-5 w-5 text-gray-400" />
    }
  }

  return (
    <div className="bg-white dark:bg-gray-800 rounded-lg shadow-lg p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-3">
          <Activity className="h-6 w-6 text-blue-500" />
          <div>
            <h3 className="text-lg font-semibold text-gray-900 dark:text-white">
              Processing Job
            </h3>
            <p className="text-sm text-gray-500 dark:text-gray-400">
              {connectionType === 'sse' ? 'Real-time updates' : 'Polling for updates'}
            </p>
          </div>
        </div>
        
        <div className="flex items-center gap-2">
          {status === 'running' && (
            <>
              <button
                onClick={() => setIsPaused(!isPaused)}
                className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded-lg"
                title={isPaused ? 'Resume' : 'Pause'}
              >
                {isPaused ? <Play className="h-5 w-5" /> : <Pause className="h-5 w-5" />}
              </button>
              {allowCancel && (
                <button
                  onClick={handleCancel}
                  className="p-2 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg text-red-600"
                  title="Cancel job"
                >
                  <X className="h-5 w-5" />
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {/* Overall Progress */}
      <div className="mb-6">
        <div className="flex items-center justify-between mb-2">
          <span className="text-sm font-medium text-gray-700 dark:text-gray-300">
            Overall Progress
          </span>
          <span className="text-sm text-gray-500 dark:text-gray-400">
            {overallProgress}%
          </span>
        </div>
        <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-2">
          <div
            className="bg-blue-500 h-2 rounded-full transition-all duration-300"
            style={{ width: `${overallProgress}%` }}
          />
        </div>
        
        {/* Time Information */}
        <div className="flex items-center justify-between mt-2 text-sm text-gray-500 dark:text-gray-400">
          <span>Elapsed: {formatTime(elapsedTime)}</span>
          {calculateETA() && (
            <span>ETA: {calculateETA()}</span>
          )}
        </div>
      </div>

      {/* Steps */}
      <div className="space-y-3">
        {steps.map((step, index) => (
          <div
            key={step.id}
            className={`flex items-center gap-3 p-3 rounded-lg border ${
              step.status === 'running'
                ? 'border-blue-200 bg-blue-50 dark:border-blue-800 dark:bg-blue-900/20'
                : 'border-gray-200 dark:border-gray-700'
            }`}
          >
            {getStatusIcon(step.status)}
            
            <div className="flex-1">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium text-gray-900 dark:text-white">
                  {step.name}
                </span>
                {step.duration && (
                  <span className="text-xs text-gray-500 dark:text-gray-400">
                    {formatTime(step.duration)}
                  </span>
                )}
              </div>
              
              {step.status === 'running' && (
                <div className="mt-2">
                  <div className="w-full bg-gray-200 dark:bg-gray-700 rounded-full h-1">
                    <div
                      className="bg-blue-500 h-1 rounded-full transition-all duration-300"
                      style={{ width: `${step.progress}%` }}
                    />
                  </div>
                </div>
              )}
              
              {step.error && (
                <p className="mt-1 text-xs text-red-600 dark:text-red-400">
                  {step.error}
                </p>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Status Message */}
      {status === 'completed' && (
        <div className="mt-6 p-4 bg-green-50 dark:bg-green-900/20 rounded-lg">
          <div className="flex items-center gap-2">
            <CheckCircle className="h-5 w-5 text-green-600 dark:text-green-400" />
            <span className="text-green-800 dark:text-green-200 font-medium">
              Job completed successfully!
            </span>
          </div>
        </div>
      )}
      
      {status === 'failed' && (
        <div className="mt-6 p-4 bg-red-50 dark:bg-red-900/20 rounded-lg">
          <div className="flex items-center gap-2">
            <XCircle className="h-5 w-5 text-red-600 dark:text-red-400" />
            <span className="text-red-800 dark:text-red-200 font-medium">
              Job failed. Please check the error details above.
            </span>
          </div>
        </div>
      )}
    </div>
  )
}
