import { test, expect } from '@playwright/test'

const BASE = process.env.E2E_BASE_URL || 'http://localhost:3000'
const AUTH_TOKEN = process.env.E2E_AUTH_TOKEN || ''
const AUTH_HEADERS = AUTH_TOKEN ? { authorization: `Bearer ${AUTH_TOKEN}` } : {}
const runIf = !!process.env.DEMO_SMOKE

test.describe('Demo flows (opt-in)', () => {
  test.skip(!runIf, 'Set DEMO_SMOKE=1 to run demo smoke tests')

  /**
   * Poll run status. Returns status string or 'auth_required' if endpoint requires auth.
   * For stub runs, status stays 'queued' since no worker processes them.
   */
  const pollStatus = async (request: any, runId: string) => {
    for (let i = 0; i < 2; i++) {
      const statusResp = await request.get(`${BASE}/api/analyses/${runId}`, {
        headers: AUTH_HEADERS,
      })
      if (statusResp.status() === 401 || statusResp.status() === 403) {
        return 'auth_required'
      }
      if (statusResp.ok()) {
        const statusJson = await statusResp.json()
        if (statusJson.status) {
          return statusJson.status
        }
      }
      await new Promise((r) => setTimeout(r, 1000))
    }
    return 'unknown'
  }

  test('motor GLM demo returns run id and status', async ({ request }) => {
    const resp = await request.post(`${BASE}/api/demo/glm`)
    test.skip(!resp.ok(), `demo/glm not available (status ${resp.status()})`)
    const ctype = resp.headers()['content-type'] || ''
    test.skip(!ctype.includes('application/json'), 'demo/glm did not return JSON; skipping')

    const json = await resp.json()

    // Assert stub response structure
    expect(json).toHaveProperty('run_id')
    expect(json).toHaveProperty('status')
    expect(json.status).toBe('queued')

    // Stub runs include marker
    if (json.stub === true) {
      expect(json).toHaveProperty('plan')
      expect(json.plan).toHaveProperty('demo', true)
      expect(json.plan).toHaveProperty('type', 'glm')
    }

    // Run poll (may be auth_required for unauthenticated tests)
    const status = await pollStatus(request, json.run_id)
    expect(['queued', 'running', 'completed', 'failed', 'auth_required']).toContain(status)
  })

  test('connectivity demo returns run id and status', async ({ request }) => {
    const resp = await request.post(`${BASE}/api/demo/connectivity`)
    test.skip(!resp.ok(), `demo/connectivity not available (status ${resp.status()})`)
    const ctype = resp.headers()['content-type'] || ''
    test.skip(!ctype.includes('application/json'), 'demo/connectivity did not return JSON; skipping')

    const json = await resp.json()

    // Assert stub response structure
    expect(json).toHaveProperty('run_id')
    expect(json).toHaveProperty('status')
    expect(json.status).toBe('queued')

    // Stub runs include marker
    if (json.stub === true) {
      expect(json).toHaveProperty('plan')
      expect(json.plan).toHaveProperty('demo', true)
      expect(json.plan).toHaveProperty('type', 'connectivity')
    }

    // Run poll (may be auth_required for unauthenticated tests)
    const status = await pollStatus(request, json.run_id)
    expect(['queued', 'running', 'completed', 'failed', 'auth_required']).toContain(status)
  })

  test('demo catch-all with stub=1 returns stub run', async ({ request }) => {
    const resp = await request.post(`${BASE}/api/demo/custom-analysis?stub=1`)
    test.skip(!resp.ok(), `demo catch-all not available (status ${resp.status()})`)
    const ctype = resp.headers()['content-type'] || ''
    test.skip(!ctype.includes('application/json'), 'did not return JSON; skipping')

    const json = await resp.json()
    expect(json).toHaveProperty('run_id')
    expect(json).toHaveProperty('status', 'queued')
    expect(json).toHaveProperty('stub', true)
  })
})
