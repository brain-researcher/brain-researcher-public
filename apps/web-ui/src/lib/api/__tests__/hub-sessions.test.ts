import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  HubSessionGatewayError,
  createOrAttachHubSession,
  isRetryableHubGatewayError,
} from '../hub-sessions'

const originalFetch = globalThis.fetch

afterEach(() => {
  globalThis.fetch = originalFetch
  vi.restoreAllMocks()
})

describe('requestJson error typing', () => {
  it('throws HubSessionGatewayError with status from a non-OK 500 response', async () => {
    globalThis.fetch = vi.fn(async () =>
      new Response(JSON.stringify({ detail: 'kernel exploded' }), {
        status: 500,
        statusText: 'Internal Server Error',
        headers: { 'content-type': 'application/json' },
      }),
    ) as unknown as typeof fetch

    const err = await createOrAttachHubSession({
      project_id: 'p',
      display_name: 'd',
    }).catch((e) => e)

    expect(err).toBeInstanceOf(HubSessionGatewayError)
    expect((err as HubSessionGatewayError).status).toBe(500)
    expect((err as HubSessionGatewayError).message).toMatch(
      /^Hub session gateway request failed:/,
    )
    // status comes from response.status, not parsed from the JSON detail text.
    expect((err as HubSessionGatewayError).message).toContain('kernel exploded')
  })

  it('throws HubSessionGatewayError with status 0 when fetch rejects (network)', async () => {
    globalThis.fetch = vi.fn(async () => {
      throw new TypeError('Failed to fetch')
    }) as unknown as typeof fetch

    const err = await createOrAttachHubSession({
      project_id: 'p',
      display_name: 'd',
    }).catch((e) => e)

    expect(err).toBeInstanceOf(HubSessionGatewayError)
    expect((err as HubSessionGatewayError).status).toBe(0)
    expect((err as HubSessionGatewayError).message).toMatch(
      /^Hub session gateway request failed:/,
    )
    expect((err as HubSessionGatewayError).message).toContain('Failed to fetch')
  })

  it('preserves the "Hub session not found" detail prefix for 404', async () => {
    globalThis.fetch = vi.fn(async () =>
      new Response(JSON.stringify({ detail: 'Hub session not found' }), {
        status: 404,
        statusText: 'Not Found',
        headers: { 'content-type': 'application/json' },
      }),
    ) as unknown as typeof fetch

    const err = await createOrAttachHubSession({
      project_id: 'p',
      display_name: 'd',
    }).catch((e) => e)

    expect(err).toBeInstanceOf(HubSessionGatewayError)
    expect((err as HubSessionGatewayError).status).toBe(404)
    expect((err as HubSessionGatewayError).message).toBe(
      'Hub session gateway request failed: Hub session not found',
    )
  })
})

describe('isRetryableHubGatewayError', () => {
  it('treats network (status 0) and 5xx as retryable', () => {
    expect(isRetryableHubGatewayError(new HubSessionGatewayError('x', 0))).toBe(true)
    expect(isRetryableHubGatewayError(new HubSessionGatewayError('x', 500))).toBe(true)
    expect(isRetryableHubGatewayError(new HubSessionGatewayError('x', 503))).toBe(true)
  })

  it('treats 4xx as non-retryable', () => {
    expect(isRetryableHubGatewayError(new HubSessionGatewayError('x', 401))).toBe(false)
    expect(isRetryableHubGatewayError(new HubSessionGatewayError('x', 403))).toBe(false)
    expect(isRetryableHubGatewayError(new HubSessionGatewayError('x', 404))).toBe(false)
    expect(isRetryableHubGatewayError(new HubSessionGatewayError('x', 422))).toBe(false)
  })

  it('treats a plain Error (and non-errors) as non-retryable', () => {
    expect(isRetryableHubGatewayError(new Error('Hub session gateway request failed: boom'))).toBe(
      false,
    )
    expect(isRetryableHubGatewayError('nope')).toBe(false)
    expect(isRetryableHubGatewayError(null)).toBe(false)
  })
})
