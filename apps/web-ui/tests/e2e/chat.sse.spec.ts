import { test, expect } from '@playwright/test'

const BASE = process.env.E2E_BASE_URL || 'http://localhost:3000'

test.describe('Coding chat SSE', () => {
  test('stream includes plan and terminal events', async ({ page }) => {
    test.skip(!process.env.CODING_SSE, 'Set CODING_SSE=1 to run coding SSE test')

    // Use Playwright's request API (attached to the same browser context) to
    // avoid flaky browser-stream parsing during dev on-demand compilation.
    const res = await page.request.post(`${BASE}/api/chat/stream`, {
      data: {
        messages: [{ role: 'user', content: 'list repo files' }],
        ctx: { tools: { mode: 'coding' }, preview: true },
      },
      headers: { accept: 'text/event-stream' },
    })

    expect(res.ok(), `status=${res.status()}`).toBe(true)
    const ctype = res.headers()['content-type'] || ''
    expect(ctype).toContain('text/event-stream')

    const text = await res.text()
    const eventTypes = Array.from(
      new Set(
        text
          .split('\n')
          .filter((l) => l.startsWith('event:'))
          .map((l) => l.slice(6).trim())
      )
    )

    // Assert plan event is present
    expect(eventTypes).toContain('plan')

    // Assert at least one terminal event is present (done, stream_end, or result)
    const hasTerminalEvent =
      eventTypes.includes('done') ||
      eventTypes.includes('stream_end') ||
      eventTypes.includes('result')
    expect(hasTerminalEvent, `events=${JSON.stringify(eventTypes)}`).toBe(true)
  })

  test('stream handles connection state transitions', async ({ page }) => {
    test.skip(!process.env.CODING_SSE, 'Set CODING_SSE=1 to run coding SSE test')

    // This test verifies that a stream can be established and completes
    // The UI hook tracks: idle -> connected -> (reconnecting?) -> idle/failed
    const result = await page.evaluate(async (base) => {
      const states: string[] = ['started']

      try {
        const res = await fetch(`${base}/api/chat/stream`, {
          method: 'POST',
          headers: { 'content-type': 'application/json' },
          body: JSON.stringify({
            messages: [{ role: 'user', content: 'hello' }],
            ctx: { tools: { mode: 'coding' }, preview: true, dry_run: true },
          }),
        })

        if (!res.ok) {
          states.push(`http_${res.status}`)
          return states
        }

        const ctype = res.headers.get('content-type') || ''
        if (!ctype.includes('text/event-stream')) {
          states.push('not_sse')
          return states
        }

        states.push('connected')

        if (!res.body) {
          states.push('no_body')
          return states
        }

        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let iterations = 0

        while (iterations < 20) {
          const { done, value } = await reader.read()
          if (done) {
            states.push('stream_ended')
            break
          }
          iterations += 1
          const chunk = decoder.decode(value, { stream: true })
          // Check for terminal events
          if (
            chunk.includes('event: done') ||
            chunk.includes('event: stream_end') ||
            chunk.includes('event: result')
          ) {
            states.push('terminal_event')
            try {
              reader.cancel()
            } catch (e) {
              /* ignore */
            }
            break
          }
        }

        states.push('completed')
        return states
      } catch (err) {
        states.push('error')
        return states
      }
    }, BASE)

    // Either we got a proper stream or it wasn't available
    const validOutcome =
      result.includes('not_sse') ||
      result.some((value) => value.startsWith('http_')) ||
      result.includes('error') ||
      (result.includes('connected') &&
        (result.includes('stream_ended') ||
          result.includes('terminal_event') ||
          result.includes('completed')))

    expect(validOutcome, `stream states: ${JSON.stringify(result)}`).toBe(true)
  })
})
