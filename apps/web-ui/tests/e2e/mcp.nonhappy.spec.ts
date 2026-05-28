import fs from 'node:fs'
import path from 'node:path'

import { test, expect } from '@playwright/test'

const BASE = process.env.E2E_BASE_URL || process.env.BASE_URL || 'http://localhost:3000'

test.describe.configure({ mode: 'serial', timeout: 90_000 })

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

function telemetryPathForToday(): string {
  const date = new Date().toISOString().slice(0, 10)
  const repoRoot = path.resolve(__dirname, '../../../..')
  return path.join(repoRoot, 'data', 'agent_outputs', 'sessions', date, 'tool_call_failed.ndjson')
}

function findTelemetryEvent(jobId: string, threadId: string): any | undefined {
  const file = telemetryPathForToday()
  if (!fs.existsSync(file)) return undefined
  const lines = fs.readFileSync(file, 'utf-8').trim().split('\n').filter(Boolean)
  for (let i = lines.length - 1; i >= 0; i--) {
    try {
      const evt = JSON.parse(lines[i])
      if (evt?.job_id === jobId && evt?.thread_id === threadId) return evt
    } catch {
      // ignore parse errors
    }
  }
  return undefined
}

async function runForcedTool(page: any, toolName: string, opts?: { budgetMs?: number; toolParams?: any }) {
  const threadId = `e2e_thread_${toolName.replace(/[^\w]/g, '_')}_${Date.now()}`
  const budgetMs = opts?.budgetMs
  const toolParams = opts?.toolParams

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

    const patched: any = {
      ...body,
      session_id: threadId,
      tools: { mode: 'force', whitelist: [toolName] },
      tools_whitelist: [toolName],
    }
    if (budgetMs !== undefined) patched.budget_ms = budgetMs
    if (toolParams !== undefined) patched.tool_params = toolParams

    await route.continue({
      headers: { ...req.headers(), 'content-type': 'application/json' },
      postData: JSON.stringify(patched),
    })
  })

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

  await expect(async () => {
    await input.click()
    await input.fill(`Please run ${toolName}.`)
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

  const runId = body?.runCard?.run_id || body?.runCard?.runId || body?.run_id
  const sessionId = body?.session_id || body?.thread_id || body?.threadId || threadId

  return { apiBody: body, runId, threadId: sessionId }
}

test('MCP server down shows explainable error + telemetry', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('onboarding-dismissed', 'true')
  })
  await ensureAuth(page)

  const { apiBody, runId, threadId } = await runForcedTool(page, 'mcp.test_server_down', {
    budgetMs: 1_000,
  })

  expect(runId, 'run id').toBeTruthy()
  const toolCalls = apiBody?.tool_calls || []
  expect(toolCalls.length).toBeGreaterThan(0)
  expect(toolCalls[0]?.name).toBe('mcp.test_server_down')
  expect(toolCalls[0]?.status).toBe('error')
  expect(toolCalls[0]?.error_category).toBe('infra')

  const assistantMessage = page.getByTestId('chat-message-assistant').last()
  await expect(assistantMessage).toContainText('Error category:', { timeout: 20_000 })

  await expect(async () => {
    const evt = findTelemetryEvent(runId, threadId)
    expect(evt, 'telemetry event').toBeTruthy()
    expect(evt?.error_category).toBe('infra')
  }).toPass({ timeout: 20_000 })
})

test('MCP timeout shows explainable error + telemetry', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('onboarding-dismissed', 'true')
  })
  await ensureAuth(page)

  const { apiBody, runId, threadId } = await runForcedTool(page, 'mcp.test_timeout', {
    budgetMs: 200,
    toolParams: { seconds: 5 },
  })

  expect(runId, 'run id').toBeTruthy()
  const toolCalls = apiBody?.tool_calls || []
  expect(toolCalls.length).toBeGreaterThan(0)
  expect(toolCalls[0]?.name).toBe('mcp.test_timeout')
  expect(toolCalls[0]?.status).toBe('error')
  expect(toolCalls[0]?.error_category).toBe('infra')

  const assistantMessage = page.getByTestId('chat-message-assistant').last()
  await expect(assistantMessage).toContainText('Error category:', { timeout: 20_000 })

  await expect(async () => {
    const evt = findTelemetryEvent(runId, threadId)
    expect(evt, 'telemetry event').toBeTruthy()
    expect(evt?.error_category).toBe('infra')
  }).toPass({ timeout: 20_000 })
})

test('MCP schema mismatch shows explainable error + telemetry', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.setItem('onboarding-dismissed', 'true')
  })
  await ensureAuth(page)

  const { apiBody, runId, threadId } = await runForcedTool(page, 'mcp.test_schema_mismatch')

  expect(runId, 'run id').toBeTruthy()
  const toolCalls = apiBody?.tool_calls || []
  expect(toolCalls.length).toBeGreaterThan(0)
  expect(toolCalls[0]?.name).toBe('mcp.test_schema_mismatch')
  expect(toolCalls[0]?.status).toBe('error')
  expect(toolCalls[0]?.error_category).toBe('user_input')

  const assistantMessage = page.getByTestId('chat-message-assistant').last()
  await expect(assistantMessage).toContainText('Error category:', { timeout: 20_000 })

  await expect(async () => {
    const evt = findTelemetryEvent(runId, threadId)
    expect(evt, 'telemetry event').toBeTruthy()
    expect(evt?.error_category).toBe('user_input')
  }).toPass({ timeout: 20_000 })
})
