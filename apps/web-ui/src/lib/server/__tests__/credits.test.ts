// @vitest-environment node
import { NextRequest } from 'next/server'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/server/request-auth', () => ({
  getRequestAuthToken: vi.fn(),
}))

import { getRequestAuthToken } from '@/lib/server/request-auth'
import { resolveCreditsIdentity } from '../credits'

function makeRequest(headers?: Record<string, string>): NextRequest {
  return new NextRequest('http://localhost/api/plan/checks', {
    headers: new Headers(headers),
  })
}

describe('resolveCreditsIdentity', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('derives distinct authenticated credit identities from session claims', async () => {
    vi.mocked(getRequestAuthToken)
      .mockResolvedValueOnce({
        sub: 'user-alpha',
        email: 'alpha@example.org',
        tenant_id: 'tenant-alpha',
      })
      .mockResolvedValueOnce({
        sub: 'user-beta',
        email: 'beta@example.org',
        tenant_id: 'tenant-beta',
      })

    await expect(resolveCreditsIdentity(makeRequest())).resolves.toEqual({
      workspaceId: 'tenant-alpha',
      userId: 'user-alpha',
    })
    await expect(resolveCreditsIdentity(makeRequest())).resolves.toEqual({
      workspaceId: 'tenant-beta',
      userId: 'user-beta',
    })
  })

  it('falls back to email and workspace_id claims when primary claim names are absent', async () => {
    vi.mocked(getRequestAuthToken).mockResolvedValueOnce({
      email: 'claim-user@example.org',
      workspace_id: 'workspace-claim',
    })

    await expect(resolveCreditsIdentity(makeRequest())).resolves.toEqual({
      workspaceId: 'workspace-claim',
      userId: 'claim-user@example.org',
    })
  })

  it('uses authenticated claims ahead of explicit request overrides', async () => {
    vi.mocked(getRequestAuthToken).mockResolvedValueOnce({
      sub: 'session-user',
      tenant_id: 'session-tenant',
    })

    await expect(
      resolveCreditsIdentity(
        makeRequest({
          'x-user-id': 'admin-user',
          'x-workspace-id': 'admin-workspace',
        }),
      ),
    ).resolves.toEqual({
      workspaceId: 'session-tenant',
      userId: 'session-user',
    })
  })

  it('uses explicit request ids as a fallback when no authenticated claim exists', async () => {
    vi.mocked(getRequestAuthToken).mockResolvedValueOnce(null)

    await expect(
      resolveCreditsIdentity(
        makeRequest({
          'x-user-id': 'fallback-user',
          'x-workspace-id': 'fallback-workspace',
        }),
      ),
    ).resolves.toEqual({
      workspaceId: 'fallback-workspace',
      userId: 'fallback-user',
    })
  })

  it('uses default/default only when no override or authenticated claim exists', async () => {
    vi.mocked(getRequestAuthToken).mockResolvedValueOnce(null)

    await expect(resolveCreditsIdentity(makeRequest())).resolves.toEqual({
      workspaceId: 'default',
      userId: 'default',
    })
  })
})
