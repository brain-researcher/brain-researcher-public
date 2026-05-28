import { useEffect, useMemo, useState } from 'react'

import { getJSON, openSSE } from '@/lib/api'
import type { JobStepsResponse, StepState } from '@/lib/job-steps'

import type { DagNodeStatus } from './plan-dag-view'

function mapStepStateToDagStatus(state?: StepState | string | null): DagNodeStatus {
  const normalized = typeof state === 'string' ? state.toLowerCase() : ''

  if (normalized === 'running' || normalized === 'claimed' || normalized === 'retrying') {
    return 'running'
  }

  if (normalized === 'succeeded' || normalized === 'completed') {
    return 'succeeded'
  }

  if (normalized === 'failed' || normalized === 'timeout') {
    return 'failed'
  }

  if (normalized === 'cancelled') {
    return 'cancelled'
  }

  if (normalized === 'skipped') {
    return 'skipped'
  }

  return 'pending'
}

function buildStatusMap(args: {
  jobSteps: JobStepsResponse | null
  orderedStepNumbers: number[]
}): Partial<Record<number, DagNodeStatus>> {
  const { jobSteps, orderedStepNumbers } = args
  if (!jobSteps?.steps?.length) {
    return {}
  }

  const mapping: Partial<Record<number, DagNodeStatus>> = {}

  orderedStepNumbers.forEach((order, idx) => {
    const step = jobSteps.steps[idx]
    if (!step) return
    mapping[order] = mapStepStateToDagStatus(step.state)
  })

  return mapping
}

export function useDagStepStatusByOrder(args: {
  jobId?: string
  stepOrders: number[]
  enabled?: boolean
}): Partial<Record<number, DagNodeStatus>> {
  const { jobId, stepOrders, enabled = true } = args
  const orderedStepNumbers = useMemo(
    () => stepOrders.map((value) => value || 0).filter(Boolean),
    [stepOrders],
  )

  const [jobSteps, setJobSteps] = useState<JobStepsResponse | null>(null)

  useEffect(() => {
    if (!enabled) return
    if (!jobId) return
    if (!orderedStepNumbers.length) return

    let isMounted = true
    let sse: EventSource | null = null
    let pollInterval: NodeJS.Timeout | null = null

    const cleanup = () => {
      isMounted = false
      if (sse) {
        sse.close()
        sse = null
      }
      if (pollInterval) {
        clearInterval(pollInterval)
        pollInterval = null
      }
    }

    const fetchSteps = async () => {
      try {
        const json = await getJSON<JobStepsResponse>(
          `/api/analyses/${encodeURIComponent(jobId)}/steps`,
        )
        if (!isMounted) return
        setJobSteps(json)
      } catch (error) {
        // Keep last known state.
        console.warn('Failed to fetch step statuses:', error)
      }
    }

    const startPolling = () => {
      if (!pollInterval) {
        pollInterval = setInterval(fetchSteps, 3000)
      }
    }

    fetchSteps()

    try {
      sse = openSSE(`/api/analyses/${encodeURIComponent(jobId)}/steps/stream`)
    } catch (error) {
      console.warn('Failed to open steps SSE; falling back to polling:', error)
      startPolling()
      return () => cleanup()
    }

    sse.addEventListener('steps_update', (evt) => {
      const message = evt as MessageEvent
      try {
        const update: JobStepsResponse = JSON.parse(message.data)
        if (!isMounted) return
        setJobSteps(update)
      } catch (parseError) {
        console.warn('Failed to parse steps_update event:', parseError)
      }
    })

    const handleSseError = () => {
      if (!isMounted) return
      if (sse) {
        sse.close()
        sse = null
      }
      startPolling()
    }

    sse.addEventListener('error', handleSseError)
    sse.onerror = handleSseError

    return () => cleanup()
  }, [enabled, jobId, orderedStepNumbers])

  return useMemo(
    () =>
      buildStatusMap({
        jobSteps,
        orderedStepNumbers,
      }),
    [jobSteps, orderedStepNumbers],
  )
}

