import { test, expect } from '@playwright/test'

// This test relies on an orchestrator/agent that can emit a failed step.
// It validates the API contract consumed by the evidence rail. UI auth is
// covered separately because CI uses bearer auth instead of a NextAuth session.

const BASE = process.env.E2E_BASE_URL || 'http://localhost:3000'
const AUTH_TOKEN = process.env.E2E_AUTH_TOKEN || ''
const AUTH_HEADERS = AUTH_TOKEN ? { authorization: `Bearer ${AUTH_TOKEN}` } : {}

test('forced failure run exposes a failed step via the evidence API', async ({ page }) => {
  test.skip(!AUTH_TOKEN, 'E2E_AUTH_TOKEN required for /api/analyses');

  // 1) Create a run that is expected to fail quickly
  const createResp = await page.request.post(`${BASE}/api/analyses`, {
    headers: { 'content-type': 'application/json', ...AUTH_HEADERS },
    data: {
      plan: {
        type: 'chat',
        prompt: 'Trigger a failure',
        parameters: { force_failure: true }
      }
    }
  })

  if (!createResp.ok()) {
    throw new Error(`status ${createResp.status()}: ${await createResp.text()}`)
  }
  const { analysis_id } = await createResp.json()
  const id = analysis_id
  expect(id).toBeTruthy()

  let failedStep: any = null
  let lastPayload: any = null
  for (let attempt = 0; attempt < 30; attempt += 1) {
    const stepsResp = await page.request.get(`${BASE}/api/analyses/${encodeURIComponent(id)}/steps`, {
      headers: AUTH_HEADERS,
    })
    if (!stepsResp.ok()) {
      throw new Error(`status ${stepsResp.status()}: ${await stepsResp.text()}`)
    }
    lastPayload = await stepsResp.json()
    failedStep = Array.isArray(lastPayload.steps)
      ? lastPayload.steps.find(
          (step: any) => String(step.state || step.status || '').toLowerCase() === 'failed',
        )
      : null
    if (failedStep) break
    await page.waitForTimeout(1000)
  }

  expect(failedStep, `last steps payload: ${JSON.stringify(lastPayload)}`).toBeTruthy()
  expect(failedStep.step_id || failedStep.name).toBeTruthy()
})
