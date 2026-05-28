import { expect, test } from '@playwright/test'

import { resolveE2EBaseUrl } from './base-url'

const BASE = resolveE2EBaseUrl()
const E2E_AUTH_COOKIE = 'br_e2e_auth'

test.describe('Hub workspace smoke', () => {
  test.use({ storageState: { cookies: [], origins: [] } })

  test('hub mounts a same-origin hosted marimo workspace shell', async ({
    context,
    page,
  }) => {
    await context.addCookies([
      {
        name: E2E_AUTH_COOKIE,
        value: '1',
        url: BASE,
      },
    ])

    const sessionId = 'studio_demo123'
    const runtimeId = 'rt_demo123'
    const runtimeTargetUrl = `${BASE}/hub/br-marimo-${runtimeId}`

    await page.route('**/api/hub/sessions', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          session: {
            id: sessionId,
            project_id: 'proj_demo',
            owner_user_id: 'e2e-user',
            display_name: 'Hosted Workspace',
            runtime_profile_id: 'standard',
            runtime_session_id: runtimeId,
            assistant_session_id: 'ast_demo123',
            status: 'ready',
            metadata: {},
            created_at: '2026-04-22T00:00:00Z',
            updated_at: '2026-04-22T00:00:00Z',
            last_activity_at: '2026-04-22T00:00:00Z',
          },
          runtime: {
            id: runtimeId,
            project_id: 'proj_demo',
            owner_user_id: 'e2e-user',
            runtime_profile_id: 'standard',
            kind: 'marimo',
            status: 'ready',
            marimo_base_url: `${BASE}/hub`,
            marimo_port: 2718,
            working_directory: 'projects/proj_demo',
            metadata: {},
            created_at: '2026-04-22T00:00:00Z',
            updated_at: '2026-04-22T00:00:00Z',
            last_activity_at: '2026-04-22T00:00:00Z',
          },
          handoff: {
            session_id: sessionId,
            project_id: 'proj_demo',
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
            notebook_path: 'projects/proj_demo/notebooks/analysis.py',
            open_artifact_id: null,
            initial_focus: null,
            materialize_notebook_if_needed: false,
          },
        }),
      })
    })

    await page.route(`**/hub/br-marimo-${runtimeId}*`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/html',
        body: '<html><body><h1>runtime ok</h1></body></html>',
      })
    })

    await page.goto(
      `${BASE}/hub?project_id=proj_demo&path=projects/proj_demo/notebooks/analysis.py`,
      {
        waitUntil: 'domcontentloaded',
      },
    )

    await expect(
      page.getByText(/Hosted Marimo Workspace/i),
    ).toBeVisible()
    await expect(page.getByText(new RegExp(`Session ${sessionId}`))).toBeVisible()

    const openRuntime = page.getByRole('link', { name: /Open runtime/i })
    await expect(openRuntime).toHaveAttribute(
      'href',
      `${runtimeTargetUrl}?session_id=${sessionId}`,
    )
    await expect(openRuntime).toHaveAttribute('target', '_blank')

    const iframe = page.locator('iframe[title="Hosted Marimo workspace"]')
    await expect(iframe).toBeVisible()
    await expect(iframe).toHaveAttribute(
      'src',
      `${runtimeTargetUrl}?session_id=${sessionId}`,
    )

    await page.reload({ waitUntil: 'domcontentloaded' })
    await expect(page.getByText(new RegExp(`Session ${sessionId}`))).toBeVisible()
    await expect(iframe).toHaveAttribute(
      'src',
      `${runtimeTargetUrl}?session_id=${sessionId}`,
    )
  })
})
