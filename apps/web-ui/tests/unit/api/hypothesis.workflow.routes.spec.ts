import { NextRequest } from 'next/server'
import { describe, expect, it } from 'vitest'

function createRequest(url: string, options: RequestInit = {}) {
  return new NextRequest(new URL(url), options)
}

describe('API Routes: hypothesis workflow helpers', () => {
  it('POST /api/hypothesis/clarify rejects missing term', async () => {
    const { POST } = await import('@/app/api/hypothesis/clarify/route')
    const req = createRequest('http://test/api/hypothesis/clarify', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({}),
    })

    const res = await POST(req)
    expect(res.status).toBe(400)
  })

  it('POST /api/hypothesis/clarify returns questions and suggested canvas', async () => {
    const { POST } = await import('@/app/api/hypothesis/clarify/route')
    const req = createRequest('http://test/api/hypothesis/clarify', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ term: 'working memory' }),
    })

    const res = await POST(req)
    expect(res.status).toBe(200)
    const payload = await res.json()

    expect(Array.isArray(payload.questions)).toBe(true)
    expect(payload.suggested_canvas?.term).toContain('Working memory')
  })

  it('POST /api/hypothesis/candidates returns fixed 5 candidates by default', async () => {
    const { POST } = await import('@/app/api/hypothesis/candidates/route')
    const req = createRequest('http://test/api/hypothesis/candidates', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        term: 'working memory',
        canvas: {
          term: 'Working memory',
          goal: 'mechanism_explanation',
          modality: 'fmri_task',
          population: 'Healthy adults',
          primary_outcome: 'Working memory effect',
          constraints: 'Allow public datasets.',
          research_question: 'When does working memory alter fronto-parietal activation?',
        },
        count: 8,
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(200)
    const payload = await res.json()

    expect(payload.candidates).toHaveLength(5)
  })

  it('POST /api/hypothesis/validate returns non_fixable when dataset is missing and constraints are strict', async () => {
    const { POST } = await import('@/app/api/hypothesis/validate/route')
    const req = createRequest('http://test/api/hypothesis/validate', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        canvas: {
          term: 'Working memory',
          goal: 'mechanism_explanation',
          modality: 'fmri_task',
          population: 'Healthy adults',
          primary_outcome: 'BOLD signal change',
          constraints: 'Use internal-only cohort.',
          research_question: 'How does working memory alter BOLD response?',
        },
        plan: {
          id: 'plan-1',
          mvp_steps: ['Run test'],
          full_steps: [],
          falsifier: 'No effect direction change',
          success_criteria: ['Primary effect direction replicated'],
          assumptions: [],
        },
        context: {
          dataset_id: null,
        },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(200)
    const payload = await res.json()

    expect(payload.validation.triage.status).toBe('non_fixable')
    expect(payload.validation.triage.reason_codes).toContain('DATA_UNAVAILABLE')
    expect(payload.validation.blocked_report).toBeTruthy()
  })

  it('POST /api/hypothesis/plan-patch enforces patch limit', async () => {
    const { POST } = await import('@/app/api/hypothesis/plan-patch/route')
    const req = createRequest('http://test/api/hypothesis/plan-patch', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        patch_count: 1,
        plan: {
          id: 'plan-1',
          mvp_steps: ['Run test'],
          full_steps: [],
          falsifier: 'No change',
          success_criteria: ['criterion'],
          assumptions: [],
        },
        validation: {
          status: 'fail',
          triage: {
            status: 'fixable',
            reason_codes: ['METHOD_INCOMPATIBLE'],
            user_actions: ['Add steps'],
          },
          checks: [],
        },
      }),
    })

    const res = await POST(req)
    expect(res.status).toBe(409)
  })
})
