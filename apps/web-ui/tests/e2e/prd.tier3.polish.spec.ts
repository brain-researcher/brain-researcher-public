import { test, expect } from '@playwright/test'

import { resolveE2EBaseUrl } from './base-url'

test.describe.configure({ mode: 'serial', timeout: 120_000 })

const BASE = resolveE2EBaseUrl()
const DATASET_ID = 'ds:openneuro:ds000001'
const DATASET_NAME = 'Balloon Analog Risk-taking Task'
const PIPELINE_ID = 'nilearn_connectivity'

const DATASET_DETAIL = {
  id: DATASET_ID,
  name: DATASET_NAME,
  description: 'Mock dataset detail for PRD Tier3 tests.',
  category: 'task',
  modalities: ['fmri'],
  acquisitions: [],
  subjects_count: 16,
  sessions_count: 1,
  access_type: 'open',
  license: 'CC0',
  source_repo: 'openneuro',
  source_repo_id: 'ds000001',
  primary_url: 'https://openneuro.org/datasets/ds000001',
  tags: [],
  tasks: ['balloon analog risk task'],
  has_derivatives: false,
  preview_media: [],
  species: ['human'],
  disease_flags: [],
  search_blob: '',
}

async function stubCommon(page: any) {
  // Force deterministic E2E fixtures for server-rendered pages (SSR fetch is not intercepted by page.route).
  await page.context().addCookies([
    {
      name: 'br_e2e_auth',
      value: '1',
      url: BASE,
    },
  ])

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

  await page.route('**/health', async (route: any) => {
    if (route.request().method() !== 'GET') {
      await route.continue()
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'healthy' }),
    })
  })

  await page.route('**/api/policies/behavior', async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ policies: [] }),
    })
  })

  await page.route('**/api/search/track**', async (route: any) => {
    await route.fulfill({ status: 204, body: '' })
  })

  await page.route('**/api/neurokg/suggestions', async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ count: 0, items: [] }),
    })
  })

  await page.route('**/api/threads/**/messages**', async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ messages: [] }),
    })
  })

  await page.route(/\/api\/threads(?:\?.*)?$/, async (route: any) => {
    if (route.request().method() !== 'GET') {
      await route.continue()
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ threads: [], count: 0 }),
    })
  })

  await page.route(/\/api\/analyses(?:\?.*)?$/, async (route: any) => {
    if (route.request().method() !== 'GET') {
      await route.continue()
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [], count: 0, next_cursor: null }),
    })
  })

  await page.route(/\/api\/workflows(?:\?.*)?$/, async (route: any) => {
    if (route.request().method() !== 'GET') {
      await route.continue()
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ workflows: [], count: 0, version: 'e2e' }),
    })
  })

  await page.route('**/api/tools/search**', async (route: any) => {
    if (route.request().method() !== 'GET') {
      await route.continue()
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ tools: [], count: 0 }),
    })
  })
}

async function stubHubWorkspace(page: any, sessionId = 'tier3_hub_session') {
  const runtimeId = `rt_${sessionId}`
  const runtimeTargetUrl = `${BASE}/hub/br-marimo-${runtimeId}`
  const handoff = {
    session_id: sessionId,
    project_id: 'proj_tier3',
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
      project_id: 'proj_tier3',
      owner_user_id: 'e2e-user',
      display_name: 'Hosted Workspace',
      runtime_profile_id: 'standard',
      runtime_session_id: runtimeId,
      assistant_session_id: `ast_${sessionId}`,
      status: 'ready',
      metadata: {},
      created_at: '2026-05-26T00:00:00Z',
      updated_at: '2026-05-26T00:00:00Z',
      last_activity_at: '2026-05-26T00:00:00Z',
    },
    runtime: {
      id: runtimeId,
      project_id: 'proj_tier3',
      owner_user_id: 'e2e-user',
      runtime_profile_id: 'standard',
      kind: 'marimo',
      status: 'ready',
      marimo_base_url: `${BASE}/hub`,
      marimo_port: 2718,
      working_directory: 'projects/proj_tier3',
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

async function openAdvancedPlanEditor(page: any) {
  await expect(page.getByRole('button', { name: /^Run(?: with warnings)?$/i })).toBeVisible({
    timeout: 30_000,
  })
  const trigger = page.getByTestId('plan-advanced-toggle')
  await expect(trigger).toBeVisible({ timeout: 30_000 })
  for (let attempt = 0; attempt < 3; attempt += 1) {
    if ((await trigger.getAttribute('aria-expanded')) === 'true') return
    await trigger.click()
    await page.waitForTimeout(150)
  }
  await expect(trigger).toHaveAttribute('aria-expanded', 'true', { timeout: 5_000 })
}

test('Tier3: failed Result Package surfaces diagnosis and repair handoffs', async ({ page }) => {
  await stubCommon(page)

  const analysisId = `e2e_failed_${Date.now()}`
  const detail = 'Missing required arguments'

  await page.route(`**/api/analyses/${analysisId}`, async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        analysis_id: analysisId,
        thread_id: 'thread_e2e',
        status: 'failed',
        title: 'E2E failed',
        dataset: { dataset_id: DATASET_ID, name: DATASET_NAME },
        template: { template_id: PIPELINE_ID, pipeline_id: PIPELINE_ID },
        warnings: [detail],
        preflight: {
          status: 'failed',
          route: PIPELINE_ID,
          detail,
        },
        steps_summary: [
          {
            id: 'step-1',
            name: 'fmriprep',
            tool: 'fmriprep',
            status: 'failed',
            detail,
          },
        ],
        artifacts: [],
        methods: { text: '', generated: false },
        parameters: {},
      }),
    })
  })

  await page.goto(`/analyses/${encodeURIComponent(analysisId)}`, {
    waitUntil: 'domcontentloaded',
  })

  await expect(page.getByRole('heading', { name: 'E2E failed' })).toBeVisible({
    timeout: 30_000,
  })
  await expect(page.getByText('Result Package: evidence · diagnostics · reproducibility')).toBeVisible()
  await expect(page.getByText(detail).first()).toBeVisible()
  await expect(page.getByText('Run trace evidence')).toBeVisible()
  await expect(page.getByText('Steps summary')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Continue via MCP recipe' })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Review plan in Studio', exact: true })).toHaveAttribute(
    'href',
    `/studio?tab=plan&pipeline=${PIPELINE_ID}&datasetId=${encodeURIComponent(DATASET_ID)}&thread=thread_e2e`,
  )
})

test('Tier3: legacy Studio mobile entry opens Hub workspace without horizontal overflow', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 })

  await stubCommon(page)
  const { sessionId, runtimeTargetUrl } = await stubHubWorkspace(page, 'tier3_mobile_session')

  await page.goto('/studio?tab=plan', { waitUntil: 'domcontentloaded' })

  await expectHubWorkspace(page, sessionId, runtimeTargetUrl)

  const metrics = await page.evaluate(() => {
    const iframe = document.querySelector('iframe[title="Hosted Marimo workspace"]')
    if (!(iframe instanceof HTMLElement)) {
      throw new Error('Expected hosted workspace iframe to exist')
    }

    const viewportWidth = window.innerWidth
    const doc = document.documentElement
    const iframeRect = iframe.getBoundingClientRect()

    return {
      viewportWidth,
      iframeLeft: iframeRect.left,
      iframeRight: iframeRect.right,
      pageXOverflow: Math.max(doc.scrollWidth, document.body.scrollWidth) - viewportWidth,
    }
  })

  expect(metrics.iframeLeft).toBeGreaterThanOrEqual(0)
  expect(metrics.iframeRight).toBeLessThanOrEqual(metrics.viewportWidth + 1)
  expect(metrics.pageXOverflow).toBeLessThanOrEqual(1)
})

test.skip('Tier3: Step Inspector edits persist (legacy Studio inspector retired)', async ({ page }) => {
  await stubCommon(page)

  await page.route('**/api/catalog/datasets/**', async (route: any) => {
    const req = route.request()
    if (req.method() !== 'GET') {
      await route.continue()
      return
    }
    const url = new URL(req.url())
    if (url.pathname.endsWith('/api/catalog/datasets/search')) {
      await route.continue()
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(DATASET_DETAIL),
    })
  })

  await page.route('**/api/pipelines', async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        pipelines: [
          {
            id: PIPELINE_ID,
            description: 'Mock pipeline with steps for inspector test.',
            steps: [
              {
                order: 1,
                tool: 'nilearn',
                description: 'Connectivity computation',
                paramNames: ['atlas'],
              },
            ],
          },
        ],
      }),
    })
  })

  await page.route('**/api/plan/checks', async (route: any) => {
    if (route.request().method() !== 'POST') {
      await route.continue()
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        checks: [
          { id: 'data_validated', label: 'Data validated', status: 'passed' },
          { id: 'workflow_compatible', label: 'Workflow compatible', status: 'passed' },
          { id: 'inputs_provided', label: 'All inputs provided', status: 'passed' },
          { id: 'credits_sufficient', label: 'Credits sufficient', status: 'warning', detail: 'Billing not configured yet.' },
        ],
        estimate: { runtime: '~1 min', credits: 1 },
      }),
    })
  })

  await page.goto(
    `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&datasetId=${encodeURIComponent(DATASET_ID)}`,
    { waitUntil: 'domcontentloaded' },
  )

  await openAdvancedPlanEditor(page)
  await expect(page.getByRole('button', { name: 'Inspect', exact: true })).toBeVisible({ timeout: 30_000 })
  await page.getByRole('button', { name: 'Inspect', exact: true }).click()

  const dialog = page.getByRole('dialog', { name: /Step/i })
  await expect(dialog).toBeVisible({ timeout: 10_000 })

  const atlasInput = dialog.locator('input[aria-label="atlas"]')
  await atlasInput.fill('AAL')
  await dialog.getByRole('button', { name: 'Save', exact: true }).click()
  await expect(dialog).toBeHidden()

  // Re-open and verify persistence.
  await page.getByRole('button', { name: 'Inspect', exact: true }).click()
  const dialog2 = page.getByRole('dialog', { name: /Step/i })
  await expect(dialog2).toBeVisible({ timeout: 10_000 })
  await expect(dialog2.locator('input[aria-label="atlas"]')).toHaveValue('AAL')
})

test.skip('Tier3: Step Inspector Ask Agent injects step context into chat prompt (legacy Studio inspector retired)', async ({ page }) => {
  await stubCommon(page)

  await page.route('**/api/catalog/datasets/**', async (route: any) => {
    const req = route.request()
    if (req.method() !== 'GET') {
      await route.continue()
      return
    }
    const url = new URL(req.url())
    if (url.pathname.endsWith('/api/catalog/datasets/search')) {
      await route.continue()
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(DATASET_DETAIL),
    })
  })

  await page.route('**/api/pipelines', async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        pipelines: [
          {
            id: PIPELINE_ID,
            description: 'Mock pipeline with steps for inspector Ask Agent test.',
            steps: [
              {
                order: 1,
                tool: 'nilearn',
                description: 'Connectivity computation',
                paramNames: ['atlas'],
              },
            ],
          },
        ],
      }),
    })
  })

  await page.route('**/api/plan/checks', async (route: any) => {
    if (route.request().method() !== 'POST') {
      await route.continue()
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        checks: [
          { id: 'data_validated', label: 'Data validated', status: 'passed' },
          { id: 'workflow_compatible', label: 'Workflow compatible', status: 'passed' },
          { id: 'inputs_provided', label: 'All inputs provided', status: 'passed' },
          { id: 'credits_sufficient', label: 'Credits sufficient', status: 'warning', detail: 'Billing not configured yet.' },
        ],
        estimate: { runtime: '~1 min', credits: 1 },
      }),
    })
  })

  let capturedPrompt: string | null = null
  await page.route('**/api/chat', async (route: any) => {
    if (route.request().method() !== 'POST') {
      await route.continue()
      return
    }
    try {
      const body = route.request().postDataJSON?.() ?? null
      capturedPrompt = typeof body?.message === 'string' ? body.message : typeof body?.prompt === 'string' ? body.prompt : null
    } catch {
      // ignore parsing issues
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ message: { content: 'Sure — here are suggested parameter values.' }, tool_calls: [] }),
    })
  })

  await page.goto(
    `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&datasetId=${encodeURIComponent(DATASET_ID)}`,
    { waitUntil: 'domcontentloaded' },
  )

  await openAdvancedPlanEditor(page)
  await page.getByRole('button', { name: 'Inspect', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: /Step/i })
  await expect(dialog).toBeVisible({ timeout: 10_000 })

  await dialog.getByRole('button', { name: 'Ask Agent about this step' }).click()

  await expect.poll(() => capturedPrompt).not.toBeNull()
  expect(capturedPrompt).toContain('Help me configure this pipeline step.')
  expect(capturedPrompt).toContain('Step: 1. nilearn')
})

test('Tier3: Attempts switcher updates analysisId and results content', async ({ page }) => {
  await stubCommon(page)

  const threadId = 'thread_e2e_attempts'
  const latestId = `e2e_latest_${Date.now()}`
  const prevId = `e2e_prev_${Date.now()}`

  await page.route(/\/api\/analyses(?:\?.*)?$/, async (route: any) => {
    const req = route.request()
    if (req.method() !== 'GET') {
      await route.continue()
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [
          {
            analysis_id: latestId,
            thread_id: threadId,
            status: 'completed',
            created_at: Math.floor(Date.now() / 1000),
            title: 'Latest ✓',
          },
          {
            analysis_id: prevId,
            thread_id: threadId,
            status: 'completed',
            created_at: Math.floor(Date.now() / 1000) - 500,
            title: 'Attempt 2',
          },
        ],
        count: 2,
        next_cursor: null,
      }),
    })
  })

  await page.route(`**/api/analyses/${latestId}`, async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        analysis_id: latestId,
        thread_id: threadId,
        status: 'completed',
        title: 'Latest ✓',
        dataset: { dataset_id: DATASET_ID, name: DATASET_NAME },
        template: { template_id: PIPELINE_ID, pipeline_id: PIPELINE_ID },
        artifacts: [],
        methods: { text: '- Latest summary bullet\n', generated: true },
        parameters: {},
      }),
    })
  })
  await page.route(`**/api/analyses/${prevId}`, async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        analysis_id: prevId,
        thread_id: threadId,
        status: 'completed',
        title: 'Attempt 2',
        dataset: { dataset_id: DATASET_ID, name: DATASET_NAME },
        template: { template_id: PIPELINE_ID, pipeline_id: PIPELINE_ID },
        artifacts: [],
        methods: { text: '- Previous summary bullet\n', generated: true },
        parameters: {},
      }),
    })
  })

  await page.route(`**/api/analyses/${latestId}/observation`, async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        run_card: {
          id: latestId,
          outputs: { text: '- Latest summary bullet\n' },
          artifacts: [],
          execution: { steps: [] },
          provenance: { nodes: [], edges: [] },
          citations: [],
          reproducibility: {},
        },
      }),
    })
  })

  await page.route(`**/api/analyses/${prevId}/observation`, async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        run_card: {
          id: prevId,
          outputs: { text: '- Previous summary bullet\n' },
          artifacts: [],
          execution: { steps: [{ id: 's1', name: 'step', status: 'completed' }] },
          provenance: { nodes: [], edges: [] },
          citations: [],
          reproducibility: {},
        },
      }),
    })
  })

  await page.goto(`/analyses/${encodeURIComponent(latestId)}`, {
    waitUntil: 'domcontentloaded',
  })

  await expect(page.getByText('Latest summary bullet')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText('Attempts')).toBeVisible({ timeout: 30_000 })

  // Open select and pick the previous attempt.
  await page.getByTestId('attempt-switcher-select').click()
  await page.getByRole('option', { name: /Attempt 2/i }).click()

  await page.waitForURL(new RegExp(`/analyses/${encodeURIComponent(prevId)}`), { timeout: 30_000 })
  await expect(page.getByText('Latest summary bullet')).toBeHidden({ timeout: 30_000 })
  await expect(page.getByText('Previous summary bullet')).toBeVisible({ timeout: 30_000 })
})

test.skip('Tier3: Cancel run triggers /api/analyses/{id}/cancel (legacy Studio run control retired)', async ({ page }) => {
  await stubCommon(page)

  // Dataset required for Plan -> Run.
  await page.route('**/api/catalog/datasets/**', async (route: any) => {
    const req = route.request()
    if (req.method() !== 'GET') {
      await route.continue()
      return
    }
    const url = new URL(req.url())
    if (url.pathname.endsWith('/api/catalog/datasets/search')) {
      await route.continue()
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(DATASET_DETAIL),
    })
  })

  await page.route('**/api/plan/checks', async (route: any) => {
    if (route.request().method() !== 'POST') {
      await route.continue()
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        checks: [
          { id: 'data_validated', label: 'Data validated', status: 'passed' },
          { id: 'workflow_compatible', label: 'Workflow compatible', status: 'passed' },
          { id: 'inputs_provided', label: 'All inputs provided', status: 'passed' },
          { id: 'credits_sufficient', label: 'Credits sufficient', status: 'warning', detail: 'Billing not configured yet.' },
        ],
        estimate: { runtime: '~1 min', credits: 1 },
      }),
    })
  })

  const runId = `e2e_cancel_${Date.now()}`

  await page.route('**/api/analyses', async (route: any) => {
    if (route.request().method() !== 'POST') {
      await route.continue()
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ analysis_id: runId, thread_id: null, status: 'running' }),
    })
  })

  // Force RealTimeProgress to fall back to polling quickly (EventSource sees non-200).
  await page.route(`**/api/analyses/${runId}/stream**`, async (route: any) => {
    await route.fulfill({ status: 404, body: 'no stream in e2e' })
  })

  // Polling endpoint used by RealTimeProgress (even though the app doesn't implement it yet).
  await page.route(`**/api/analyses/${runId}/progress`, async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        job: {
          id: runId,
          status: 'running',
          overall_progress: 12.5,
          steps: [],
          estimated_remaining: 120,
        },
      }),
    })
  })

  let cancelCalls = 0
  await page.route(`**/api/analyses/${runId}/cancel`, async (route: any) => {
    if (route.request().method() !== 'POST') {
      await route.continue()
      return
    }
    cancelCalls += 1
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) })
  })

  await page.goto(
    `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&datasetId=${encodeURIComponent(DATASET_ID)}`,
    { waitUntil: 'domcontentloaded' },
  )

  const approve = page.getByRole('button', { name: /^Run(?: with warnings)?$/i })
  await expect(approve).toBeEnabled({ timeout: 30_000 })
  await approve.click({ force: true })

  await expect(page.getByRole('tab', { name: 'Results' })).toHaveAttribute('data-state', 'active')
  await expect(page.getByText('Processing')).toBeVisible({ timeout: 30_000 })

  await page.getByTitle('Cancel').click()
  await expect.poll(() => cancelCalls).toBeGreaterThan(0)
})

test('Tier3: MCP settings panel renders client-specific config snippets', async ({ page, context }) => {
  await context.grantPermissions(['clipboard-read', 'clipboard-write'])

  await stubCommon(page)

  await page.route('**/api/mcp/tokens/verify', async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        backend: 'e2e',
        redis_available: true,
        pepper_configured: true,
        has_active_token: false,
      }),
    })
  })

  await page.route('**/api/mcp/tokens', async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ tokens: [], count: 0 }),
    })
  })

  await page.route('**/api/credits/**', async (route: any) => {
    const url = new URL(route.request().url())
    const body = url.pathname.endsWith('/ledger')
      ? { items: [], next_cursor: null }
      : { balance: 0 }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    })
  })

  await page.goto('/settings?tab=integrations', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'Integrations' })).toBeVisible({
    timeout: 30_000,
  })
  await expect(page.getByText('Paste this into your IDE')).toBeVisible()

  await expect(page.getByRole('button', { name: 'Cursor' })).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: 'Copy JSON' }).click()
  const cursorClipboard = await page.evaluate(async () => navigator.clipboard.readText())
  const cursorParsed = JSON.parse(cursorClipboard)
  expect(cursorParsed?.mcpServers?.['brain-researcher']?.url).toBeTruthy()
  expect(cursorParsed?.mcpServers?.['brain-researcher']?.type).toBe('http')
  expect(cursorParsed?.mcpServers?.['brain-researcher']?.headers?.Accept).toBe(
    'application/json, text/event-stream',
  )
  expect(cursorParsed?.mcpServers?.['brain-researcher']?.headers?.Authorization).toMatch(
    /^Bearer (brk_<kid>\.<secret>|brk_[A-Za-z0-9_.-]+)$/,
  )

  await page.getByRole('button', { name: 'Codex' }).click()
  await expect(page.getByText('~/.codex/config.toml').first()).toBeVisible()
  await page.getByRole('button', { name: 'Copy TOML' }).click()
  const codexClipboard = await page.evaluate(async () => navigator.clipboard.readText())
  expect(codexClipboard).toContain('[mcp_servers.brain-researcher]')
  expect(codexClipboard).toContain('url = "https://brain-researcher.com/mcp"')
  expect(codexClipboard).toContain('bearer_token_env_var = "BR_MCP_TOKEN"')
  expect(codexClipboard).toContain('[mcp_servers.brain-researcher.http_headers]')
  expect(codexClipboard).toContain('Accept = "application/json, text/event-stream"')

  await page.getByRole('button', { name: 'Claude Code' }).click()
  await expect(page.getByText('.mcp.json').first()).toBeVisible()
  await page.getByRole('button', { name: 'Copy JSON' }).click()
  const claudeClipboard = await page.evaluate(async () => navigator.clipboard.readText())
  const claudeParsed = JSON.parse(claudeClipboard)
  expect(claudeParsed?.mcpServers?.['brain-researcher']?.url).toBeTruthy()
  expect(claudeParsed?.mcpServers?.['brain-researcher']?.type).toBe('http')
  expect(claudeParsed?.mcpServers?.['brain-researcher']?.headers?.Accept).toBe(
    'application/json, text/event-stream',
  )
  expect(claudeParsed?.mcpServers?.['brain-researcher']?.headers?.Authorization).toBe(
    'Bearer ${BR_MCP_TOKEN}',
  )

  const localTab = page.getByRole('tab', { name: 'Local (Advanced)' })
  await localTab.focus()
  await localTab.press('Enter')
  await expect(page.getByText('npx -y @brain-researcher/mcp-server start')).toBeVisible()
})
