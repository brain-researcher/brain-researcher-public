import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ensureDemoRunExists } from '@/lib/server/demo-seed'
import { issueInternalJwt } from '@/lib/server/internal-jwt'

const mockFetch = vi.fn()
global.fetch = mockFetch

vi.mock('@/lib/server/downstream', () => ({
  resolveOrchestratorBaseUrl: () => 'http://orchestrator',
}))

vi.mock('@/lib/server/internal-jwt', () => ({
  issueInternalJwt: vi.fn(),
}))

describe('ensureDemoRunExists', () => {
  const issueJwtMock = vi.mocked(issueInternalJwt)

  beforeEach(() => {
    vi.clearAllMocks()
    issueJwtMock.mockReturnValue('demo-seed-token')
  })

  afterEach(() => {
    vi.resetAllMocks()
  })

  it('does not seed curated manuscript report demos', async () => {
    const ok = await ensureDemoRunExists({
      slug: 'case1-report',
      analysis_id: 'run_case1_report',
      title: 'Case 1 Report',
      demo_type: 'manuscript_case_report',
    } as any)

    expect(ok).toBe(false)
    expect(issueJwtMock).not.toHaveBeenCalled()
    expect(mockFetch).not.toHaveBeenCalled()
  })

  it('returns early when orchestrator already has the seeded analysis', async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ analysis_id: 'demo_run_001' }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      }),
    )

    const ok = await ensureDemoRunExists({
      slug: 'demo-run',
      analysis_id: 'demo_run_001',
      title: 'Demo Run',
    } as any)

    expect(ok).toBe(true)
    expect(mockFetch).toHaveBeenCalledTimes(1)
    expect(String(mockFetch.mock.calls[0]?.[0] || '')).toBe(
      'http://orchestrator/api/jobs/demo_run_001',
    )
  })

  it('creates a deterministic orchestrator demo placeholder when the job is missing', async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: 'not found' }), {
        status: 404,
        headers: { 'content-type': 'application/json' },
      }),
    )
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ job_id: 'demo_run_002', analysis_id: 'demo_run_002' }), {
        status: 201,
        headers: { 'content-type': 'application/json' },
      }),
    )

    const ok = await ensureDemoRunExists({
      slug: 'demo-run',
      analysis_id: 'demo_run_002',
      title: 'Demo Run',
    } as any)

    expect(ok).toBe(true)
    expect(mockFetch).toHaveBeenCalledTimes(2)
    expect(String(mockFetch.mock.calls[0]?.[0] || '')).toBe(
      'http://orchestrator/api/jobs/demo_run_002',
    )
    expect(String(mockFetch.mock.calls[1]?.[0] || '')).toBe('http://orchestrator/run')
    expect(mockFetch.mock.calls[1]?.[1]?.method).toBe('POST')
    const payload = JSON.parse(String(mockFetch.mock.calls[1]?.[1]?.body || '{}'))
    expect(payload.requested_job_id).toBe('demo_run_002')
    expect(payload.parameters?.demo_seed).toBe(true)
  })

  it('does not fall back to agent when orchestrator is temporarily unavailable', async () => {
    mockFetch.mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: 'temporary outage' }), {
        status: 503,
        headers: { 'content-type': 'application/json' },
      }),
    )

    const ok = await ensureDemoRunExists({
      slug: 'demo-run',
      analysis_id: 'demo_run_003',
      title: 'Demo Run',
    } as any)

    expect(ok).toBe(false)
    expect(mockFetch).toHaveBeenCalledTimes(1)
  })
})
