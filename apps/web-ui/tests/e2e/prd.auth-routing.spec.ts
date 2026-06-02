import { test, expect } from '@playwright/test'

import { resolveE2EBaseUrl } from './base-url'

const BASE = resolveE2EBaseUrl()
const BASE_URL = new URL(BASE)
const E2E_AUTH_COOKIE = 'br_e2e_auth'

async function addE2EAuth(context: any) {
  await context.addCookies([
    {
      name: E2E_AUTH_COOKIE,
      value: '1',
      url: BASE,
    },
  ])
}

async function stubCommon(page: any) {
  await page.route('**/api/events', async (route: any) => {
    await route.fulfill({ status: 204, body: '' })
  })

  await page.route('**/api/errors/report', async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true }),
    })
  })

  await page.route('**/api/health', async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'healthy' }),
    })
  })
}

async function stubHubWorkspace(page: any) {
  const sessionId = 'auth_routing_hub_session'
  const runtimeId = 'rt_auth_routing_hub'
  const runtimeTargetUrl = `${BASE}/hub/br-marimo-${runtimeId}`
  const handoff = {
    session_id: sessionId,
    project_id: 'proj_auth_routing',
    runtime_session_id: runtimeId,
    runtime_profile_id: 'standard',
    runtime_kind: 'marimo',
    runtime_status: 'ready',
    hub_base_url: `${BASE}/hub`,
    launch_mode: 'reuse_active_runtime',
    workspace_url: `${BASE}/hub?session_id=${sessionId}`,
    runtime_target_url: runtimeTargetUrl,
    runtime_websocket_url: runtimeTargetUrl.replace('http', 'ws'),
    runtime_connection_mode: 'iframe',
    runtime_target_ready: true,
    runtime_target_reason: 'ready',
    target_path: null,
    notebook_path: null,
    open_artifact_id: null,
    initial_focus: null,
    materialize_notebook_if_needed: false,
  }
  const envelope = {
    session: {
      id: sessionId,
      project_id: 'proj_auth_routing',
      owner_user_id: 'e2e-user',
      display_name: 'Hosted Workspace',
      runtime_profile_id: 'standard',
      runtime_session_id: runtimeId,
      assistant_session_id: 'ast_auth_routing',
      status: 'ready',
      metadata: {},
      created_at: '2026-05-26T00:00:00Z',
      updated_at: '2026-05-26T00:00:00Z',
      last_activity_at: '2026-05-26T00:00:00Z',
    },
    runtime: {
      id: runtimeId,
      project_id: 'proj_auth_routing',
      owner_user_id: 'e2e-user',
      runtime_profile_id: 'standard',
      kind: 'marimo',
      status: 'ready',
      marimo_base_url: `${BASE}/hub`,
      marimo_port: 2718,
      working_directory: 'projects/proj_auth_routing',
      metadata: {},
      created_at: '2026-05-26T00:00:00Z',
      updated_at: '2026-05-26T00:00:00Z',
      last_activity_at: '2026-05-26T00:00:00Z',
    },
    handoff,
  }

  await page.route('**/api/hub/sessions**', async (route: any) => {
    const req = route.request()
    const url = new URL(req.url())
    if (req.method() === 'POST' && url.pathname.endsWith('/handoff')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ handoff }),
      })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(envelope),
    })
  })

  await page.route(`**/hub/br-marimo-${runtimeId}*`, async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'text/html',
      body: '<html><body><h1>runtime ok</h1></body></html>',
    })
  })

  return { sessionId, runtimeTargetUrl }
}

async function expectHubWorkspace(page: any, sessionId: string, runtimeTargetUrl: string) {
  await expect(page).toHaveURL(/\/hub(?:\?|$)/, { timeout: 30_000 })
  await expect(page.getByText(/Hosted Marimo Workspace/i)).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText(new RegExp(`Session ${sessionId}`))).toBeVisible()
  await expect(page.locator('iframe[title="Hosted Marimo workspace"]')).toHaveAttribute(
    'src',
    `${runtimeTargetUrl}?session_id=${sessionId}`,
  )
}

test.describe('PRD auth + routing (root/landing/studio)', () => {
  test('auth: / renders the public landing page', async ({ context, page }) => {
    await addE2EAuth(context)
    await stubCommon(page)
    await page.addInitScript(() => {
      try {
        Object.keys(localStorage)
          .filter((key) => key.startsWith('br:plan:'))
          .forEach((key) => localStorage.removeItem(key))
      } catch {
        // ignore
      }
    })

    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await expect(page).toHaveURL(/\/(?:\?|$)/, { timeout: 30_000 })

    const url = new URL(page.url())
    expect(url.searchParams.get('onboarding')).toBeNull()
    await expect(page.getByTestId('landing-page')).toHaveAttribute('data-hydrated', '1')
    await expect(page.getByRole('heading', { name: /Take any neuroimaging workflow/i })).toBeVisible()
  })

  test('auth: / ignores legacy br_studio_visited cookie and still renders Landing', async ({
    context,
    page,
  }) => {
    await addE2EAuth(context)
    await stubCommon(page)
    await page.context().addCookies([
      {
        name: 'br_studio_visited',
        value: '1',
        url: BASE_URL.origin,
      },
    ])

    await page.goto('/', { waitUntil: 'domcontentloaded' })
    await expect(page).toHaveURL(/\/(?:\?|$)/, { timeout: 30_000 })

    const url = new URL(page.url())
    expect(url.searchParams.get('onboarding')).toBeNull()
    await expect(page.getByTestId('landing-page')).toHaveAttribute('data-hydrated', '1')
    await expect(page.getByRole('heading', { name: /Take any neuroimaging workflow/i })).toBeVisible()
  })

  test('auth: legacy /studio onboarding query redirects into hosted Hub', async ({
    context,
    page,
  }) => {
    await addE2EAuth(context)
    await stubCommon(page)
    const { sessionId, runtimeTargetUrl } = await stubHubWorkspace(page)
    await page.addInitScript(() => {
      try {
        Object.keys(localStorage)
          .filter((key) => key.startsWith('br:plan:'))
          .forEach((key) => localStorage.removeItem(key))
      } catch {
        // ignore
      }
    })

    await page.goto('/studio?onboarding=true', { waitUntil: 'domcontentloaded' })
    await expectHubWorkspace(page, sessionId, runtimeTargetUrl)

    const current = new URL(page.url())
    expect(current.pathname).toBe('/hub')
    expect(current.searchParams.get('onboarding')).toBe('true')
  })

  test.describe('unauth', () => {
    test.use({ storageState: { cookies: [], origins: [] } })

    test('unauth: / renders Landing', async ({ page }) => {
      await stubCommon(page)
      await page.goto('/', { waitUntil: 'domcontentloaded' })
      await expect(page.getByTestId('landing-page')).toHaveAttribute('data-hydrated', '1')
      await expect(page.getByRole('heading', { name: /Take any neuroimaging workflow/i })).toBeVisible()
      // Screen 1: MCP setup steps
      await expect(page.getByRole('heading', { name: /Configure MCP/i })).toBeVisible()
      // Screen 2: paper + code
      await expect(
        page.getByRole('heading', { name: /Read the paper, run the code/i }),
      ).toBeVisible()
      await expect(page.getByText(/Open-source release coming soon/i)).toBeVisible()

      const keyboardHelp = page.getByTitle('Keyboard Shortcuts (⌘ ?)')
      const feedback = page.getByRole('button', { name: 'Open feedback menu' })
      await expect(keyboardHelp).toBeVisible()
      await expect(feedback).toBeVisible()

      const keyboardBox = await keyboardHelp.boundingBox()
      const feedbackBox = await feedback.boundingBox()
      expect(keyboardBox).toBeTruthy()
      expect(feedbackBox).toBeTruthy()
      if (keyboardBox && feedbackBox) {
        const overlapX = Math.max(
          0,
          Math.min(keyboardBox.x + keyboardBox.width, feedbackBox.x + feedbackBox.width) -
            Math.max(keyboardBox.x, feedbackBox.x),
        )
        const overlapY = Math.max(
          0,
          Math.min(keyboardBox.y + keyboardBox.height, feedbackBox.y + feedbackBox.height) -
            Math.max(keyboardBox.y, feedbackBox.y),
        )
        expect(overlapX * overlapY).toBe(0)
      }
    })

    test('unauth: /studio redirects through Hub to sign-in', async ({ page }) => {
      await stubCommon(page)
      await page.goto('/studio', { waitUntil: 'domcontentloaded' })
      const loginHeading = page.getByRole('heading', { name: /Sign in to your account/i })
      await expect(page).toHaveURL(/\/auth\/login\?callbackUrl=%2Fhub(?:$|&)/, {
        timeout: 30_000,
      })
      await expect(loginHeading).toBeVisible()
    })

    test('unauth: Landing Studio CTA → /auth/signup carries callbackUrl=/studio', async ({
      page,
    }) => {
      await stubCommon(page)
      await page.goto('/', { waitUntil: 'domcontentloaded' })
      await expect(page.getByTestId('landing-page')).toHaveAttribute('data-hydrated', '1')

      // The in-page "Open Studio" CTA (Try-it section) gates an unauthenticated
      // user through signup, preserving the intended Studio destination. Scope to
      // the section since the site nav also exposes an "Open Studio" signup link.
      const cta = page.locator('#try-it').getByRole('link', { name: 'Open Studio' })
      await expect(cta).toHaveAttribute('href', '/auth/signup?callbackUrl=%2Fstudio')

      await cta.click()
      await expect(page).toHaveURL(/\/auth\/signup\?/, { timeout: 30_000 })

      const url = new URL(page.url())
      const callbackUrl = url.searchParams.get('callbackUrl')
      expect(callbackUrl).toBe('/studio')
      expect(callbackUrl).not.toContain('onboarding=')
    })

    test('unauth: legal pages stay public', async ({ page }) => {
      await stubCommon(page)
      await page.goto('/terms', { waitUntil: 'domcontentloaded' })
      await expect(page).toHaveURL(/\/terms(?:\?|$)/, { timeout: 30_000 })
      await expect(page).not.toHaveURL(/\/auth\/login/, { timeout: 30_000 })
      await expect(page.getByRole('heading', { name: 'Terms of Service' })).toBeVisible()

      await page.goto('/privacy', { waitUntil: 'domcontentloaded' })
      await expect(page).toHaveURL(/\/privacy(?:\?|$)/, { timeout: 30_000 })
      await expect(page).not.toHaveURL(/\/auth\/login/, { timeout: 30_000 })
      await expect(page.getByRole('heading', { name: 'Privacy Policy' })).toBeVisible()
    })
  })
})
