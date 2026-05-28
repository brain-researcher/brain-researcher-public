import { test, expect } from '@playwright/test'

const BASE = process.env.E2E_BASE_URL || process.env.BASE_URL || 'http://localhost:3000'

test.describe.configure({ mode: 'serial', timeout: 60_000 })

async function ensureAuth(page: any) {
  const email = process.env.E2E_DEV_EMAIL || process.env.DEV_CREDENTIALS_EMAIL
  const password = process.env.E2E_DEV_PASSWORD || process.env.DEV_CREDENTIALS_PASSWORD

  test.skip(!email || !password, 'Set DEV_CREDENTIALS_EMAIL/DEV_CREDENTIALS_PASSWORD for auth')

  if (!page.url().startsWith(BASE)) {
    await page.goto(BASE, { waitUntil: 'domcontentloaded' })
  }

  const authResult = await page.evaluate(
    async ({ email: userEmail, password: userPassword }) => {
      const csrfResp = await fetch('/api/auth/csrf', { credentials: 'include' })
      const csrfData = await csrfResp.json()
      if (!csrfData?.csrfToken) {
        return { ok: false, error: 'missing_csrf' }
      }

      const body = new URLSearchParams({
        csrfToken: csrfData.csrfToken,
        email: userEmail,
        password: userPassword,
        callbackUrl: `${window.location.origin}/dashboard`,
        json: 'true',
      })

      const authResp = await fetch('/api/auth/callback/credentials', {
        method: 'POST',
        headers: { 'content-type': 'application/x-www-form-urlencoded' },
        body,
        credentials: 'include',
        redirect: 'manual',
      })

      return { ok: authResp.ok, status: authResp.status }
    },
    { email, password }
  )

  if (!authResult.ok) {
    throw new Error(`Auth failed (${authResult.status ?? 'unknown'})`)
  }

  const session = await page.evaluate(async () => {
    const resp = await fetch('/api/auth/session', { credentials: 'include' })
    return resp.json()
  })

  if (!session?.user) {
    throw new Error('Auth session missing after credential login')
  }
}

test('UI chat triggers MCP tool call and returns tool result', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('onboarding-dismissed', 'true')
  })

  // Force the outgoing /api/chat request to use a single MCP tool for determinism.
  await page.route('**/api/chat', async (route) => {
    const req = route.request()
    if (req.method() !== 'POST') {
      await route.continue()
      return
    }

    let body: any = {}
    try {
      const raw = req.postData()
      body = raw ? JSON.parse(raw) : {}
    } catch {
      body = {}
    }
    const patched = {
      ...body,
      tools: { mode: 'force', whitelist: ['mcp.server_info'] },
      tools_whitelist: ['mcp.server_info'],
    }
    await route.continue({
      headers: { ...req.headers(), 'content-type': 'application/json' },
      postData: JSON.stringify(patched),
    })
  })

  await ensureAuth(page)
  await page.goto(`${BASE}/studio`, { waitUntil: 'domcontentloaded' })

  await page.addStyleTag({
    content: `
      [role="dialog"] { display: none !important; }
      .modal, .dialog, .onboarding-modal, .onboarding-overlay {
        display: none !important;
      }
    `,
  })

  const input = page.getByPlaceholder('Ask anything about neuroimaging')
  await expect(input).toBeVisible({ timeout: 10_000 })
  const sendButton = page.getByTestId('chat-send-button')

  // Ensure React hydration has taken over before we rely on controlled inputs.
  // Sometimes the DOM value gets overwritten during hydration, which can flake E2E.
  await expect(async () => {
    await input.click()
    await input.fill('Please run the server_info tool and summarize the result.')
    await expect(input).toHaveValue(/server_info tool/i)
    await expect(sendButton).toBeEnabled()
  }).toPass({ timeout: 45_000 })

  const responsePromise = page.waitForResponse(
    (resp) =>
      resp.url().includes('/api/chat') &&
      resp.request().method() === 'POST' &&
      resp.status() === 200
  )
  await sendButton.click()
  const response = await responsePromise
  const body = await response.json().catch(() => ({}))

  const toolCalls =
    body?.tool_calls ||
    body?.runCard?.provenance?.tool_calls ||
    body?.runCard?.provenance?.toolCalls ||
    []

  expect(Array.isArray(toolCalls), 'tool calls array').toBeTruthy()
  expect(toolCalls.length, 'tool calls length').toBeGreaterThan(0)
  const toolNames = toolCalls.map((call: any) => call?.name || call?.tool || call?.id)
  expect(toolNames, 'tool call names').toContain('mcp.server_info')

  const assistantMessage = page.getByTestId('chat-message-assistant').last()
  await expect(assistantMessage).toBeVisible({ timeout: 20_000 })
})
