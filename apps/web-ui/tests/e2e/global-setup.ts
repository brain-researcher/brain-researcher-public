import fs from 'node:fs'
import path from 'node:path'

import { chromium, type FullConfig } from '@playwright/test'

const E2E_AUTH_COOKIE = 'br_e2e_auth'

async function globalSetup(config: FullConfig) {
  const baseURL =
    process.env.E2E_BASE_URL ||
    process.env.BASE_URL ||
    (config.projects[0]?.use?.baseURL as string | undefined) ||
    'http://localhost:3000'

  const email =
    process.env.E2E_DEV_EMAIL ||
    process.env.DEV_CREDENTIALS_EMAIL ||
    // Default local placeholder account (safe for dev)
    'demo@example.com'

  const password =
    process.env.E2E_DEV_PASSWORD ||
    process.env.DEV_CREDENTIALS_PASSWORD ||
    // Default local placeholder account (safe for dev)
    'DemoPass123!'

  const repoRoot = path.resolve(__dirname, '../../../..')
  const storageStatePath = path.join(repoRoot, 'artifacts', 'playwright', '.auth', 'storageState.json')
  fs.mkdirSync(path.dirname(storageStatePath), { recursive: true })

  // If we have a CI-auth header token, we can skip interactive NextAuth sign-in.
  // The smoke tests call `/api/analyses*` using bearer auth (not cookies).
  if (process.env.E2E_AUTH_TOKEN) {
    const browser = await chromium.launch()
    const context = await browser.newContext()
    const page = await context.newPage()
    await page.goto(baseURL, { waitUntil: 'domcontentloaded' })
    await context.addCookies([
      {
        name: E2E_AUTH_COOKIE,
        value: '1',
        url: baseURL,
      },
    ])
    await context.storageState({ path: storageStatePath })
    await browser.close()
    return
  }

  const browser = await chromium.launch()
  const context = await browser.newContext()
  const page = await context.newPage()

  await page.goto(baseURL, { waitUntil: 'domcontentloaded' })

  // Always set the deterministic e2e auth cookie in non-production so tests
  // can bypass NextAuth-protected pages and SSR fetches consistently.
  await context.addCookies([
    {
      name: E2E_AUTH_COOKIE,
      value: '1',
      url: baseURL,
    },
  ])

  // Prefer a deterministic e2e cookie auth bypass when CredentialsProvider isn't enabled.
  // This keeps the PRD tests runnable without needing real accounts.
  const providers = await context.request
    .get(`${baseURL}/api/auth/providers`)
    .then(async (resp) => (resp.ok() ? resp.json().catch(() => ({} as any)) : ({} as any)))
    .catch(() => ({} as any))

  const hasCredentialsProvider = Boolean((providers as any)?.credentials)
  if (!hasCredentialsProvider) {
    await context.storageState({ path: storageStatePath })
    await browser.close()
    return
  }

  const csrfResp = await context.request.get(`${baseURL}/api/auth/csrf`)
  const csrfData = await csrfResp.json().catch(() => ({} as any))
  const csrfToken = (csrfData as any)?.csrfToken

  const authResp = await context.request.post(`${baseURL}/api/auth/callback/credentials`, {
    form: {
      csrfToken,
      email,
      password,
      callbackUrl: `${baseURL}/dashboard`,
      json: 'true',
    },
  })
  const authJson = await authResp.json().catch(() => ({} as any))
  const authResult = {
    ok: authResp.ok(),
    status: authResp.status(),
    url: (authJson as any)?.url,
    error: (authJson as any)?.error,
  }

  if (
    !authResult.ok ||
    (typeof authResult.url === 'string' &&
      (authResult.url.includes('/api/auth/signin') ||
        authResult.url.includes('csrf=true') ||
        authResult.url.includes('error=')))
  ) {
    await context.storageState({ path: storageStatePath })
    await browser.close()
    return
  }

  // In dev mode, the first request to /api/auth/* can trigger on-demand compilation.
  // Poll until a valid session with user is available to avoid flaky startup races.
  const deadlineMs = Date.now() + 20_000
  let lastSession: any = null
  while (Date.now() < deadlineMs) {
    // eslint-disable-next-line no-await-in-loop
    lastSession = await context.request
      .get(`${baseURL}/api/auth/session`)
      .then(async (resp) => ({ status: resp.status(), json: await resp.json().catch(() => ({})) }))

    if (lastSession?.status === 200 && lastSession?.json?.user) {
      break
    }

    // eslint-disable-next-line no-await-in-loop
    await new Promise((r) => setTimeout(r, 500))
  }

  if (!lastSession?.json?.user) {
    throw new Error(
      'Playwright globalSetup: credential auth succeeded but /api/auth/session is missing user.'
    )
  }

  await context.storageState({ path: storageStatePath })
  await browser.close()
}

export default globalSetup
