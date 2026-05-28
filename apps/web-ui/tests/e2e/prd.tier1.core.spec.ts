import { test, expect } from '@playwright/test'

import { resolveE2EBaseUrl } from './base-url'

test.describe.configure({ mode: 'serial', timeout: 120_000 })

const BASE = resolveE2EBaseUrl()
const E2E_AUTH_COOKIE = 'br_e2e_auth'
const DATASET_ID = 'ds:openneuro:ds000001'
const PIPELINE_ID = 'nilearn_connectivity'

const DATASET_DETAIL = {
  id: DATASET_ID,
  name: 'Balloon Analog Risk-taking Task',
  description: 'Mock dataset for PRD Tier1 tests.',
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
  tags: ['fmri'],
  tasks: ['balloon analog risk task'],
  has_derivatives: false,
  preview_media: [],
  species: ['human'],
  disease_flags: [],
  search_blob: '',
  created_at: '2026-05-26T00:00:00Z',
  updated_at: '2026-05-26T00:00:00Z',
}

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

  await page.route('**/health', async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ status: 'healthy' }),
    })
  })
}

async function stubHubWorkspace(
  page: any,
  options: {
    sessionId?: string
    runtimeId?: string
    runtimeReady?: boolean
    runtimeReason?: string
    runtimeMode?: string
    notebookPath?: string | null
  } = {},
) {
  const sessionId = options.sessionId ?? 'tier1_hub_session'
  const runtimeId = options.runtimeId ?? 'rt_tier1_hub_session'
  const runtimeReady = options.runtimeReady ?? true
  const runtimeReason = options.runtimeReason ?? (runtimeReady ? 'ready' : 'provisioning')
  const runtimeMode = options.runtimeMode ?? 'iframe'
  const runtimeTargetUrl = `${BASE}/hub/br-marimo-${runtimeId}`
  const handoff = {
    session_id: sessionId,
    project_id: 'proj_tier1',
    runtime_session_id: runtimeId,
    runtime_profile_id: 'standard',
    runtime_kind: 'marimo',
    runtime_status: runtimeReady ? 'ready' : 'queued',
    hub_base_url: `${BASE}/hub`,
    launch_mode: 'reuse_active_runtime',
    workspace_url: `${BASE}/hub?session_id=${sessionId}`,
    runtime_target_url: runtimeTargetUrl,
    runtime_websocket_url: runtimeTargetUrl.replace('http', 'ws'),
    runtime_connection_mode: runtimeMode,
    runtime_target_ready: runtimeReady,
    runtime_target_reason: runtimeReason,
    target_path: null,
    notebook_path: options.notebookPath ?? null,
    open_artifact_id: null,
    initial_focus: null,
    materialize_notebook_if_needed: false,
  }
  const envelope = {
    session: {
      id: sessionId,
      project_id: 'proj_tier1',
      owner_user_id: 'e2e-user',
      display_name: 'Hosted Workspace',
      runtime_profile_id: 'standard',
      runtime_session_id: runtimeId,
      assistant_session_id: 'ast_tier1',
      status: runtimeReady ? 'ready' : 'queued',
      metadata: {},
      created_at: '2026-05-26T00:00:00Z',
      updated_at: '2026-05-26T00:00:00Z',
      last_activity_at: '2026-05-26T00:00:00Z',
    },
    runtime: {
      id: runtimeId,
      project_id: 'proj_tier1',
      owner_user_id: 'e2e-user',
      runtime_profile_id: 'standard',
      kind: 'marimo',
      status: runtimeReady ? 'ready' : 'queued',
      marimo_base_url: `${BASE}/hub`,
      marimo_port: 2718,
      working_directory: 'projects/proj_tier1',
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

  if (runtimeReady) {
    await page.route(`**/hub/br-marimo-${runtimeId}*`, async (route: any) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/html',
        body: '<html><body><h1>runtime ok</h1></body></html>',
      })
    })
  }

  return { sessionId, runtimeId, runtimeTargetUrl }
}

async function stubDatasetSearch(page: any) {
  await page.route('**/api/catalog/datasets/search**', async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        datasets: [DATASET_DETAIL],
        total: 1,
        limit: 60,
        offset: 0,
        has_more: false,
        search_time_ms: 1,
        facets: {},
        last_updated: '2026-05-26T00:00:00Z',
      }),
    })
  })
}

async function stubAnalysesList(page: any, items: any[] = []) {
  await page.route('**/api/analyses*', async (route: any) => {
    const req = route.request()
    const url = new URL(req.url())
    if (req.method() === 'GET' && url.pathname.endsWith('/api/analyses')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ items, count: items.length, next_cursor: null }),
      })
      return
    }
    await route.fallback()
  })
}

async function stubAnalysisDetail(page: any, analysisId: string, detail: Record<string, any>) {
  await page.route(`**/api/analyses/${analysisId}`, async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        analysis_id: analysisId,
        dataset: { dataset_id: DATASET_ID, name: DATASET_DETAIL.name },
        template: { template_id: PIPELINE_ID, pipeline_id: PIPELINE_ID },
        artifacts: [],
        parameters: {},
        ...detail,
      }),
    })
  })
}

test('Tier1: legacy Studio entry redirects to hosted Hub workspace', async ({ context, page }) => {
  await addE2EAuth(context)
  await stubCommon(page)
  const { sessionId, runtimeTargetUrl } = await stubHubWorkspace(page)

  await page.goto('/studio?tab=plan', { waitUntil: 'domcontentloaded' })

  await expect(page).toHaveURL(/\/hub\?tab=plan/)
  await expect(page.getByText(/Hosted Marimo Workspace/i)).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText(new RegExp(`Session ${sessionId}`))).toBeVisible()
  await expect(page.locator('iframe[title="Hosted Marimo workspace"]')).toHaveAttribute(
    'src',
    `${runtimeTargetUrl}?session_id=${sessionId}`,
  )
})

test('Tier1: dataset picker keeps canonical Studio returnTo link', async ({ context, page }) => {
  await addE2EAuth(context)
  await stubCommon(page)
  await stubDatasetSearch(page)

  const returnTo = `/studio?tab=plan&pipeline=${PIPELINE_ID}`
  await page.goto(`/datasets?pick=1&returnTo=${encodeURIComponent(returnTo)}`, {
    waitUntil: 'domcontentloaded',
  })

  await expect(page.getByRole('heading', { name: 'Pick a dataset' })).toBeVisible({
    timeout: 30_000,
  })
  await expect(page.getByText(DATASET_DETAIL.name).first()).toBeVisible()
  await expect(page.getByRole('link', { name: 'Add to Plan' }).first()).toHaveAttribute(
    'href',
    `/studio?tab=plan&pipeline=${PIPELINE_ID}&datasetId=${encodeURIComponent(DATASET_ID)}`,
  )
})

test('Tier1: Hub workspace shows a clear runtime-not-ready fallback', async ({ context, page }) => {
  await addE2EAuth(context)
  await stubCommon(page)
  const { sessionId } = await stubHubWorkspace(page, {
    sessionId: 'tier1_pending_session',
    runtimeId: 'rt_tier1_pending',
    runtimeReady: false,
    runtimeReason: 'provisioning',
  })

  await page.goto('/hub?project_id=proj_tier1', { waitUntil: 'domcontentloaded' })

  await expect(page.getByText(/Hosted Marimo Workspace/i)).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText(new RegExp(`Session ${sessionId}`))).toBeVisible()
  await expect(page.getByText('Runtime target is not ready yet')).toBeVisible()
  await expect(page.getByText('provisioning')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Refresh runtime target' })).toBeVisible()
})

test('Tier1: running result package renders execution status', async ({ context, page }) => {
  await addE2EAuth(context)
  await stubCommon(page)
  const analysisId = `tier1_running_${Date.now()}`
  await stubAnalysesList(page)
  await stubAnalysisDetail(page, analysisId, {
    status: 'running',
    title: 'Tier1 running analysis',
    created_at: '2026-05-26T00:00:00Z',
  })
  await page.route(`**/api/analyses/${analysisId}/stream`, async (route: any) => {
    await route.fulfill({
      status: 200,
      headers: {
        'content-type': 'text/event-stream; charset=utf-8',
        'cache-control': 'no-cache',
        connection: 'keep-alive',
      },
      body: [
        `event: progress_update\ndata: ${JSON.stringify({ status: 'running', overall_progress: 45 })}\n\n`,
        `event: milestone\ndata: ${JSON.stringify({ stage: 'data_check', status: 'running' })}\n\n`,
      ].join(''),
    })
  })

  await page.goto(`/analyses/${encodeURIComponent(analysisId)}`, {
    waitUntil: 'domcontentloaded',
  })

  await expect(page.getByRole('heading', { name: 'Tier1 running analysis' })).toBeVisible({
    timeout: 30_000,
  })
  await expect(page.getByText('Result Package: evidence · diagnostics · reproducibility')).toBeVisible()
  await expect(page.getByText('Execution status')).toBeVisible()
  await expect(page.getByText('Stage: Data check')).toBeVisible({ timeout: 30_000 })
})

test('Tier1: completed result package renders methods, outputs, and attempts', async ({
  context,
  page,
}) => {
  await addE2EAuth(context)
  await stubCommon(page)
  const threadId = 'thread_tier1_result'
  const latestId = `tier1_completed_${Date.now()}`
  const previousId = `tier1_previous_${Date.now()}`
  await stubAnalysesList(page, [
    {
      analysis_id: latestId,
      thread_id: threadId,
      status: 'completed',
      created_at: Math.floor(Date.now() / 1000),
      title: 'Latest completed',
    },
    {
      analysis_id: previousId,
      thread_id: threadId,
      status: 'failed',
      created_at: Math.floor(Date.now() / 1000) - 500,
      title: 'Previous failed',
    },
  ])
  await stubAnalysisDetail(page, latestId, {
    thread_id: threadId,
    status: 'completed',
    title: 'Tier1 completed analysis',
    methods: { text: 'Methods text for tier1 result package.', generated: true },
    parameters: { confounds: '24p', atlas: 'schaefer_100' },
    artifact_contract: { required_outputs: ['group_report.html', 'connectivity_matrix.csv'] },
    artifacts: [
      { id: 'a1', name: 'group_report.html', type: 'html', path: 'outputs/group_report.html' },
      { id: 'a2', name: 'connectivity_matrix.csv', type: 'table', path: 'outputs/connectivity_matrix.csv' },
    ],
  })

  await page.goto(`/analyses/${encodeURIComponent(latestId)}`, {
    waitUntil: 'domcontentloaded',
  })

  await expect(page.getByRole('heading', { name: 'Tier1 completed analysis' })).toBeVisible({
    timeout: 30_000,
  })
  await expect(page.getByText('Attempts')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('heading', { name: 'Methods (draft)' })).toBeVisible()
  await expect(page.getByText('Methods text for tier1 result package.')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Evidence & outputs' })).toBeVisible()
  await expect(page.getByText('group_report.html').first()).toBeVisible()
  await expect(page.getByText('connectivity_matrix.csv').first()).toBeVisible()
})

test('Tier1: failed result package surfaces readable input-path error', async ({
  context,
  page,
}) => {
  await addE2EAuth(context)
  await stubCommon(page)
  const analysisId = `tier1_failed_${Date.now()}`
  const detail =
    'Connectivity run requires an existing BOLD NIfTI file. Resolved img "/app/data/openneuro/ds000001/sub-01/func/sub-01_task-rest_bold.nii.gz" does not exist or is not a file.'
  await stubAnalysesList(page)
  await stubAnalysisDetail(page, analysisId, {
    status: 'failed',
    title: 'Tier1 failed analysis',
    warnings: [detail],
    preflight: {
      status: 'failed',
      route: PIPELINE_ID,
      detail,
    },
    steps_summary: [
      {
        id: 'connectivity-inputs',
        name: 'Validate connectivity inputs',
        status: 'failed',
        detail,
      },
    ],
  })

  await page.goto(`/analyses/${encodeURIComponent(analysisId)}`, {
    waitUntil: 'domcontentloaded',
  })

  await expect(page.getByRole('heading', { name: 'Tier1 failed analysis' })).toBeVisible({
    timeout: 30_000,
  })
  await expect(page.getByText(/Connectivity run requires an existing BOLD NIfTI file/i).first()).toBeVisible()
  await expect(page.getByText('Run trace evidence')).toBeVisible()
  await expect(page.getByRole('link', { name: 'Continue via MCP recipe' })).toBeVisible()
})

test('Tier1: result package can create and revoke a public share link', async ({
  context,
  page,
}) => {
  await addE2EAuth(context)
  await stubCommon(page)
  const analysisId = `tier1_share_${Date.now()}`
  const shareToken = `tier1_share_token_${Date.now()}`
  await stubAnalysesList(page)
  await stubAnalysisDetail(page, analysisId, {
    status: 'completed',
    title: 'Tier1 shareable analysis',
    methods: { text: 'Shareable methods.', generated: true },
  })
  await page.route(`**/api/analyses/${analysisId}/share`, async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        share_token: shareToken,
        revocable: true,
        share_path: `/share/${shareToken}`,
      }),
    })
  })
  await page.route(`**/api/share/${shareToken}`, async (route: any) => {
    if (route.request().method() === 'DELETE') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ok: true }),
      })
      return
    }
    await route.fulfill({
      status: 410,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Share link has been revoked.' }),
    })
  })

  await page.goto(`/analyses/${encodeURIComponent(analysisId)}`, {
    waitUntil: 'domcontentloaded',
  })

  await page.getByRole('button', { name: 'Share', exact: true }).click()
  const shareDialog = page.getByRole('dialog', { name: 'Share Result Package' })
  await expect(shareDialog).toBeVisible()
  await shareDialog.getByRole('button', { name: 'Copy' }).click()
  const shareLinkInput = shareDialog.getByPlaceholder('Generate a link to share…')
  await expect(shareLinkInput).toHaveValue(/\/share\//, { timeout: 30_000 })
  const shareUrl = await shareLinkInput.inputValue()
  expect(shareUrl).toContain(`/share/${shareToken}`)

  page.once('dialog', (dialog) => dialog.accept())
  await shareDialog.getByRole('button', { name: 'Revoke Access' }).click()
  await shareDialog.getByRole('button', { name: 'Done' }).click()

  await page.goto(shareUrl, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('Share link has been revoked.')).toBeVisible({ timeout: 30_000 })
})
