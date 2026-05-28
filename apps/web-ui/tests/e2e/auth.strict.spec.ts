import { test, expect, request as playwrightRequest } from '@playwright/test'

const BASE = process.env.E2E_BASE_URL || process.env.BASE_URL || 'http://localhost:3000'

test.describe.configure({ mode: 'serial' })

test('Strict auth: /api/threads requires a valid session', async ({ request }) => {
  // Authenticated request context is created from globalSetup storageState.
  const authed = await request.get('/api/threads?limit=1')
  expect(authed.status()).toBe(200)
  const authedBody = await authed.json()
  expect(Array.isArray(authedBody?.threads)).toBeTruthy()
  expect(authedBody?.user_id).toBeTruthy()
  expect(authedBody?.user_id).not.toBe('dev-user')

  // Unauthenticated context should be rejected by the Agent (not redirected by Next).
  const unauth = await playwrightRequest.newContext({
    baseURL: BASE,
    storageState: { cookies: [], origins: [] },
  })
  const unauthResp = await unauth.get('/api/threads?limit=1')
  expect(unauthResp.status()).toBe(401)
  const unauthBody = await unauthResp.json().catch(() => ({}))
  expect(unauthBody?.error).toBe('missing_bearer_token')
  await unauth.dispose()
})
