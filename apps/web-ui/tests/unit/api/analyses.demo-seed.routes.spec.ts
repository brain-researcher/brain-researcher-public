import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { NextRequest } from 'next/server'

import { buildAnalysisDetail } from '@/lib/server/analysis-detail'
import { loadDemoIndex } from '@/lib/server/demo-index'
import { issueInternalJwt } from '@/lib/server/internal-jwt'
import { isRequestAuthenticated } from '@/lib/server/request-auth'

vi.mock('@/lib/server/analysis-detail', () => ({
  buildAnalysisDetail: vi.fn(),
}))

vi.mock('@/lib/server/request-auth', () => ({
  isRequestAuthenticated: vi.fn(),
}))

vi.mock('@/lib/server/demo-index', () => ({
  loadDemoIndex: vi.fn(),
}))

vi.mock('@/lib/server/internal-jwt', () => ({
  issueInternalJwt: vi.fn(),
}))

vi.mock('@/lib/server/downstream', () => ({
  forwardAuthHeaders: () => new Headers({ authorization: 'Bearer user-token' }),
}))

const createRequest = (url: string, options: RequestInit = {}) =>
  new NextRequest(new URL(url), options)

describe('API Routes: Analyses demo direct-link fallback', () => {
  const authMock = vi.mocked(isRequestAuthenticated)
  const demoIndexMock = vi.mocked(loadDemoIndex)
  const buildDetailMock = vi.mocked(buildAnalysisDetail)
  const issueInternalJwtMock = vi.mocked(issueInternalJwt)

  beforeEach(() => {
    vi.clearAllMocks()
    authMock.mockResolvedValue(false)
    demoIndexMock.mockReturnValue({
      demos: [
        {
          slug: 'synthetic-robustness-replay',
          analysis_id: 'run_synthetic_robustness_replay',
          title: 'Synthetic Robustness Replay',
        },
      ],
    })
    issueInternalJwtMock.mockReturnValue('demo-viewer-token')
  })

  afterEach(() => {
    vi.resetAllMocks()
  })

  it('returns demo bundle fallback detail when the live analysis is missing', async () => {
    buildDetailMock.mockResolvedValue({
      ok: false,
      status: 404,
      body: { detail: 'Run not found.' },
    } as any)

    const { GET } = await import('@/app/api/analyses/[analysisId]/route')
    const req = createRequest('http://test/api/analyses/run_synthetic_robustness_replay')
    const res = await GET(req, {
      params: { analysisId: 'run_synthetic_robustness_replay' },
    })
    const payload = await res.json()

    expect(res.status).toBe(200)
    expect(buildDetailMock).toHaveBeenCalledTimes(1)
    expect(payload.analysis_id).toBe('run_synthetic_robustness_replay')
    expect(payload.status).toBe('completed')
    expect(Array.isArray(payload.warnings)).toBe(true)
    expect(payload.warnings[0]).toContain('Live run unavailable')
  })

  it('returns curated manuscript report detail without probing live analysis', async () => {
    demoIndexMock.mockReturnValue({
      demos: [
        {
          slug: 'case2-cocaine-network-segregation',
          analysis_id: 'run_case2_cocaine_network_segregation',
          title: 'Case 2: Cocaine Network Segregation Robustness',
          demo_type: 'manuscript_case_report',
          evidence_mode: 'real',
          log_mode: 'summary_only',
        },
      ],
    })

    const { GET } = await import('@/app/api/analyses/[analysisId]/route')
    const req = createRequest('http://test/api/analyses/run_case2_cocaine_network_segregation')
    const res = await GET(req, {
      params: { analysisId: 'run_case2_cocaine_network_segregation' },
    })
    const payload = await res.json()

    expect(res.status).toBe(200)
    expect(buildDetailMock).not.toHaveBeenCalled()
    expect(payload.analysis_id).toBe('run_case2_cocaine_network_segregation')
    expect(payload.status).toBe('completed')
    expect(payload.parameters.demo_type).toBe('manuscript_case_report')
    expect(payload.warnings.join('\n')).not.toContain('Live run unavailable')
  })

  it('rejects unauthenticated non-demo analysis ids', async () => {
    const { GET } = await import('@/app/api/analyses/[analysisId]/route')
    const req = createRequest('http://test/api/analyses/private_run_id')
    const res = await GET(req, { params: { analysisId: 'private_run_id' } })

    expect(res.status).toBe(401)
    expect(buildDetailMock).not.toHaveBeenCalled()
  })

  it('also returns demo bundle fallback for authenticated demo viewers on 404', async () => {
    authMock.mockResolvedValue(true)
    buildDetailMock.mockResolvedValue({
      ok: false,
      status: 404,
      body: { detail: 'Run not found.' },
    } as any)

    const { GET } = await import('@/app/api/analyses/[analysisId]/route')
    const req = createRequest('http://test/api/analyses/run_synthetic_robustness_replay')
    const res = await GET(req, {
      params: { analysisId: 'run_synthetic_robustness_replay' },
    })

    expect(res.status).toBe(200)
    expect(buildDetailMock).toHaveBeenCalledTimes(1)
  })
})
