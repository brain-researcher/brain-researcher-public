// @vitest-environment jsdom
import { act, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const { listenersByName, openSSE } = vi.hoisted(() => {
  const listenersByName = new Map<string, Array<(event: any) => void>>()
  const openSSE = vi.fn(() => {
    listenersByName.clear()
    return {
      addEventListener: vi.fn((name: string, listener: (event: any) => void) => {
        const listeners = listenersByName.get(name) ?? []
        listeners.push(listener)
        listenersByName.set(name, listeners)
      }),
      close: vi.fn(),
      onopen: null,
      onmessage: null,
      onerror: null,
    }
  })
  return { listenersByName, openSSE }
})

vi.mock('@/lib/api', () => ({ openSSE }))

import { AnalysisStreamEventsPanel } from '../analysis-stream-events-panel'

describe('AnalysisStreamEventsPanel', () => {
  it('ignores EventSource connection errors without JSON payloads', async () => {
    render(<AnalysisStreamEventsPanel analysisId="job_test" />)

    act(() => {
      for (const listener of listenersByName.get('error') ?? []) {
        listener({ type: 'error' })
      }
    })

    expect(screen.queryByText('Failed to parse event JSON.')).not.toBeInTheDocument()
    expect(screen.getByText('No events yet.')).toBeInTheDocument()
  })

  it('still renders typed error events when they include JSON data', async () => {
    render(<AnalysisStreamEventsPanel analysisId="job_test" />)

    act(() => {
      for (const listener of listenersByName.get('error') ?? []) {
        listener({
          data: JSON.stringify({
            schema_version: 'analysis-stream-event-v1',
            seq: 1,
            timestamp: '2026-05-22T00:00:00Z',
            event_type: 'error',
            payload: { message: 'agent plan execution failed' },
          }),
        })
      }
    })

    expect(await screen.findByText('agent plan execution failed')).toBeInTheDocument()
  })
})
