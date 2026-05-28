import { test, expect } from '@playwright/test'

import { resolveE2EBaseUrl } from './base-url'

test.describe.configure({ mode: 'serial', timeout: 120_000 })

const BASE = resolveE2EBaseUrl()
const DATASET_ID = 'ds:openneuro:ds000001'
const DATASET_NAME = 'Balloon Analog Risk-taking Task'
const PIPELINE_ID = 'nilearn_connectivity'

const DATASET_CARD = {
  id: DATASET_ID,
  name: DATASET_NAME,
  description: 'Mock dataset for PRD Tier2 tests.',
  category: 'task',
  modalities: ['fmri'],
  acquisitions: [],
  subjects_count: 16,
  sessions_count: 1,
  access_type: 'open',
  license: 'CC0',
  tags: ['balloon'],
  tasks: ['balloon analog risk task'],
  has_derivatives: false,
  preview_media: [],
  source_repo: 'openneuro',
  source_repo_id: 'ds000001',
  primary_url: 'https://openneuro.org/datasets/ds000001',
  updated_at: new Date().toISOString(),
  created_at: new Date().toISOString(),
}

const DATASET_DETAIL = {
  id: DATASET_ID,
  name: DATASET_NAME,
  description: 'Mock dataset detail for PRD Tier2 tests.',
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
  // Force deterministic E2E fixtures for server-rendered pages (SSR fetch isn't interceptable via page.route).
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

  // Various pages post anonymous search tracking; keep tests deterministic.
  await page.route('**/api/search/track**', async (route: any) => {
    await route.fulfill({ status: 204, body: '' })
  })
}

async function stubHubWorkspace(page: any, sessionId = 'tier2_hub_session') {
  const runtimeId = `rt_${sessionId}`
  const runtimeTargetUrl = `${BASE}/hub/br-marimo-${runtimeId}`
  const handoff = {
    session_id: sessionId,
    project_id: 'proj_tier2',
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
      project_id: 'proj_tier2',
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
      project_id: 'proj_tier2',
      owner_user_id: 'e2e-user',
      runtime_profile_id: 'standard',
      kind: 'marimo',
      status: 'ready',
      marimo_base_url: `${BASE}/hub`,
      marimo_port: 2718,
      working_directory: 'projects/proj_tier2',
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

test('Tier2: Datasets → Add to Plan redirects into Hub with dataset query', async ({ page }) => {
  await stubCommon(page)
  const { sessionId, runtimeTargetUrl } = await stubHubWorkspace(page, 'tier2_dataset_session')

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
          { id: 'workflow_compatible', label: 'Workflow compatible', status: 'blocked', detail: 'Pipeline required' },
          { id: 'inputs_provided', label: 'All inputs provided', status: 'blocked', detail: 'Pipeline required' },
          { id: 'credits_sufficient', label: 'Credits sufficient', status: 'warning', detail: 'Billing not configured yet.' },
        ],
        estimate: null,
      }),
    })
  })

  // Use a deterministic query that resolves to an E2E fixture dataset via the server route.
  await page.goto('/datasets?q=ds000001', { waitUntil: 'domcontentloaded' })

  await expect(page.getByRole('heading', { name: DATASET_NAME })).toBeVisible({ timeout: 30_000 })
  await page.getByRole('link', { name: 'Add to Plan', exact: true }).first().click()

  await expectHubWorkspace(page, sessionId, runtimeTargetUrl)

  const current = new URL(page.url())
  expect(current.searchParams.get('datasetId')).toBe(DATASET_ID)
})

test('Tier2: Dataset detail pick mode preserves returnTo and redirects into Hub', async ({
  page,
}) => {
  await stubCommon(page)
  const { sessionId, runtimeTargetUrl } = await stubHubWorkspace(
    page,
    'tier2_dataset_detail_session',
  )

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

  const returnTo = `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}`
  await page.goto(
    `/datasets/${encodeURIComponent(DATASET_ID)}?pick=1&returnTo=${encodeURIComponent(returnTo)}`,
    { waitUntil: 'domcontentloaded' },
  )

  await expect(page.getByRole('heading', { name: DATASET_NAME })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('link', { name: /Back to Datasets/i })).toHaveAttribute(
    'href',
    `/datasets?pick=1&returnTo=${encodeURIComponent(returnTo)}`,
  )

  await page.getByRole('link', { name: 'Add to Plan', exact: true }).click()

  await expectHubWorkspace(page, sessionId, runtimeTargetUrl)

  const current = new URL(page.url())
  expect(current.pathname).toBe('/hub')
  expect(current.searchParams.get('datasetId')).toBe(DATASET_ID)
  expect(current.searchParams.get('pipeline')).toBe(PIPELINE_ID)
  expect(current.searchParams.get('tab')).toBe('plan')
})

test('Tier2: Workflows → Add to Plan redirects into Hub with pipeline query', async ({ page }) => {
  await stubCommon(page)
  const { sessionId, runtimeTargetUrl } = await stubHubWorkspace(page, 'tier2_workflow_session')

  await page.goto('/library', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'Workflows' })).toBeVisible()

  await page.getByRole('link', { name: 'Add to Studio plan', exact: true }).first().click()

  await expectHubWorkspace(page, sessionId, runtimeTargetUrl)

  const current = new URL(page.url())
  expect(current.searchParams.get('pipeline')).toBeTruthy()
})

test('Tier2: BR-KG → Add to Plan redirects into Hub with concept query', async ({ page }) => {
  await stubCommon(page)
  const { sessionId, runtimeTargetUrl } = await stubHubWorkspace(page, 'tier2_kg_session')

  const conceptId = 'dmn'
  const conceptLabel = 'DMN'

  await page.route('**/api/neurokg/health', async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ status: 'ok' }) })
  })

  await page.route('**/api/kg/concepts**', async (route: any) => {
    const url = new URL(route.request().url())
    if (!url.pathname.endsWith('/api/kg/concepts')) {
      await route.continue()
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([{ id: conceptId, label: conceptLabel, category: 'concept' }]),
    })
  })

  await page.route('**/api/kg/concepts/tree**', async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        roots: [{ id: conceptId, label: conceptLabel, depth: 0, children: [], hasChildren: false }],
      }),
    })
  })

  await page.route('**/api/neurokg/graph**', async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ nodes: [], edges: [], counts: { nodes: 0, edges: 0 }, backend: 'Neo4j' }),
    })
  })

  await page.route(`**/api/kg/concept/${conceptId}/summary`, async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: conceptId,
        label: conceptLabel,
        status: 'online',
        origin: 'e2e',
        spaces: [],
        atlases: [],
        features: { statmaps: 0, coords: 0, timeseries: 0, datasets: 0, papers: 0 },
      }),
    })
  })

  await page.route(`**/api/kg/concept/${conceptId}`, async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ parents: [], children: [] }) })
  })

  await page.route(`**/api/kg/concept/${conceptId}/evidence**`, async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ groups: { statmaps: [], coords: [], timeseries: [], datasets: [], papers: [] } }),
    })
  })

  await page.route('**/api/neurokg/graph/query', async (route: any) => {
    if (route.request().method() !== 'POST') {
      await route.continue()
      return
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ nodes: [], edges: [] }) })
  })

  await page.goto('/kg?tab=onvoc', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'Knowledge Graph' })).toBeVisible()

  await expect(page.getByRole('tab', { name: 'ONVOC', exact: true })).toHaveAttribute(
    'data-state',
    'active',
  )
  await page.getByPlaceholder('Search concepts').fill('DMN')
  await page.getByRole('button', { name: /DMN/ }).first().click()

  await expect(page.getByRole('button', { name: 'Add to Plan', exact: true })).toBeVisible({ timeout: 30_000 })
  await page.getByRole('button', { name: 'Add to Plan', exact: true }).click()

  await expectHubWorkspace(page, sessionId, runtimeTargetUrl)

  const current = new URL(page.url())
  expect(current.searchParams.get('conceptId')).toBe(conceptId)
})

test.skip('Tier2: KG Suggestions accept/reject wiring works (mocked)', async ({ page }) => {
  await stubCommon(page)

  const suggestion = {
    id: 's1',
    type: 'add_edge',
    target: 'DMN → Hippocampus',
    change: 'Relation: functional_connectivity (weight: 0.72)',
    confidence: 'high',
    source: { analysis_id: 'a1b2c3d4', created_at: new Date().toISOString() },
    evidence: { artifacts: [{ name: 'connectivity_matrix.csv', url: '/api/share/fake/matrix.csv' }] },
  }

  await page.route('**/api/neurokg/suggestions', async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ count: 1, items: [suggestion] }),
    })
  })

  await page.route('**/api/neurokg/suggestions/s1/accept', async (route: any) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) })
  })

  await page.goto('/kg?tab=suggestions', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('tab', { name: /Suggestions/i })).toBeVisible()

  await expect(page.getByText('DMN → Hippocampus')).toBeVisible({ timeout: 30_000 })
  await page.getByRole('button', { name: 'Review', exact: true }).click()

  const dialog = page.getByRole('dialog', { name: 'Review Suggestion' })
  await expect(dialog).toBeVisible({ timeout: 10_000 })
  await expect(dialog.getByText('Proposed values')).toBeVisible()

  // Accept (from list) removes the card.
  const accept = dialog.getByRole('button', { name: 'Accept', exact: true })
  await accept.scrollIntoViewIfNeeded()
  await accept.click()
  await expect(page.getByText('DMN → Hippocampus')).toBeHidden({ timeout: 10_000 })
})

test.skip('Tier2: KG Suggestions reject removes the suggestion (mocked)', async ({ page }) => {
  await stubCommon(page)

  const suggestion = {
    id: 's1',
    type: 'update_attr',
    target: 'PCC',
    change: 'threshold: 0.5 → 0.65',
    confidence: 'medium',
    source: { analysis_id: 'a1b2c3d4', created_at: new Date().toISOString() },
    evidence: { artifacts: [] },
  }

  await page.route('**/api/neurokg/suggestions', async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ count: 1, items: [suggestion] }),
    })
  })

  await page.route('**/api/neurokg/suggestions/s1/reject', async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true }),
    })
  })

  await page.goto('/kg?tab=suggestions', { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('threshold: 0.5 → 0.65')).toBeVisible({ timeout: 30_000 })
  await page.getByRole('button', { name: 'Review', exact: true }).click()

  const dialog = page.getByRole('dialog', { name: 'Review Suggestion' })
  await expect(dialog).toBeVisible({ timeout: 10_000 })

  const reject = dialog.getByRole('button', { name: 'Reject', exact: true })
  await reject.scrollIntoViewIfNeeded()
  await reject.click()

  await expect(page.getByText('threshold: 0.5 → 0.65')).toBeHidden({ timeout: 10_000 })
})

test('Tier2: Analysis Detail → Review plan in Studio redirects into Hub', async ({ page }) => {
  await stubCommon(page)
  const { sessionId, runtimeTargetUrl } = await stubHubWorkspace(page, 'tier2_review_plan_session')

  const analysisId = `e2e_analysis_${Date.now()}`
  const threadId = 'thread_e2e'

  await page.route(`**/api/analyses/${analysisId}`, async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        analysis_id: analysisId,
        thread_id: threadId,
        status: 'completed',
        title: 'E2E analysis',
        dataset: { dataset_id: DATASET_ID, name: DATASET_NAME },
        template: { template_id: PIPELINE_ID, pipeline_id: PIPELINE_ID },
        artifacts: [],
        methods: { text: 'Methods draft', generated: true },
        parameters: {},
      }),
    })
  })

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
        estimate: { runtime: '~1 min', credits: 'TBD' },
      }),
    })
  })

  await page.goto(`/analyses/${encodeURIComponent(analysisId)}`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'E2E analysis' })).toBeVisible({ timeout: 30_000 })

  await page.getByRole('link', { name: 'Review plan in Studio', exact: true }).click()

  await expectHubWorkspace(page, sessionId, runtimeTargetUrl)

  const current = new URL(page.url())
  expect(current.searchParams.get('datasetId')).toBe(DATASET_ID)
  expect(current.searchParams.get('pipeline')).toBe(PIPELINE_ID)
  expect(current.searchParams.get('tab')).toBe('plan')
})

test('Tier2: Share Modal generates a link and share page is read-only (mocked)', async ({ page, context }) => {
  await stubCommon(page)

  const analysisId = `e2e_share_${Date.now()}`
  const shareToken = 'abc123'

  await page.route(`**/api/analyses/${analysisId}`, async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        analysis_id: analysisId,
        thread_id: null,
        status: 'completed',
        title: 'E2E share',
        dataset: { dataset_id: DATASET_ID, name: DATASET_NAME },
        template: { template_id: PIPELINE_ID, pipeline_id: PIPELINE_ID },
        artifacts: [],
        methods: { text: 'Methods', generated: true },
        parameters: {},
      }),
    })
  })

  await page.route(`**/api/analyses/${analysisId}/share`, async (route: any) => {
    if (route.request().method() !== 'POST') {
      await route.continue()
      return
    }
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
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) })
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        analysis_id: analysisId,
        status: 'completed',
        title: 'E2E share',
        share_level: 'summary',
        dataset: { dataset_id: DATASET_ID, name: DATASET_NAME },
        template: { template_id: PIPELINE_ID, pipeline_id: PIPELINE_ID },
        artifacts: [],
        methods: { text: 'Methods', generated: true },
        parameters: {},
      }),
    })
  })

  await page.goto(`/analyses/${encodeURIComponent(analysisId)}`, { waitUntil: 'domcontentloaded' })
  await page.getByRole('button', { name: 'Share', exact: true }).click()

  const dialog = page.getByRole('dialog', { name: 'Share Result Package' })
  await expect(dialog).toBeVisible({ timeout: 10_000 })
  await expect(dialog.getByText('Summary package (recommended)')).toBeVisible()

  // Generate link (Copy triggers creation).
  await dialog.getByRole('button', { name: 'Copy', exact: true }).click()
  const linkInput = dialog.getByPlaceholder('Generate a link to share…')
  await expect(linkInput).toHaveValue(new RegExp(`/share/${shareToken}`), { timeout: 10_000 })
  const shareUrl = await linkInput.inputValue()

  const browser = context.browser()
  if (!browser) throw new Error('Playwright context is missing a browser instance')

  const baseURL = process.env.E2E_BASE_URL || process.env.BASE_URL || 'http://localhost:3000'
  const unauthContext = await browser.newContext({ baseURL, storageState: { cookies: [], origins: [] } })
  const unauthPage = await unauthContext.newPage()
  await stubCommon(unauthPage)
  await unauthPage.route(`**/api/share/${shareToken}`, async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        analysis_id: analysisId,
        status: 'completed',
        title: 'E2E share',
        share_level: 'summary',
        dataset: { dataset_id: DATASET_ID, name: DATASET_NAME },
        template: { template_id: PIPELINE_ID, pipeline_id: PIPELINE_ID },
        artifacts: [],
        methods: { text: 'Methods', generated: true },
        parameters: {},
      }),
    })
  })

  await unauthPage.goto(shareUrl, { waitUntil: 'domcontentloaded' })
  await expect(unauthPage.getByText('Shared Result Package (read-only)')).toBeVisible({ timeout: 30_000 })
  await expect(unauthPage.getByRole('button', { name: 'Share', exact: true })).toBeHidden()
  await unauthContext.close()
})

test('Tier2: Workflows search filters workflows', async ({ page }) => {
  await stubCommon(page)

  await page.goto('/library?q=qsiprep', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'Workflows' })).toBeVisible()

  await expect(page.getByTestId('library-workflow-card-workflow_qsiprep')).toBeVisible()
  await expect(page.getByTestId('library-workflow-card-workflow_fmriprep_preprocessing')).toBeHidden()
})

test('Tier2: Workflows search → Add to Plan redirects into Hub with pipeline query', async ({
  page,
}) => {
  await stubCommon(page)
  const { sessionId, runtimeTargetUrl } = await stubHubWorkspace(
    page,
    'tier2_workflow_search_session',
  )

  await page.goto('/library?q=qsiprep', { waitUntil: 'domcontentloaded' })
  await expect(page.getByTestId('library-workflow-card-workflow_qsiprep')).toBeVisible()

  await page.getByTestId('library-add-to-plan-workflow_qsiprep').click()
  await expectHubWorkspace(page, sessionId, runtimeTargetUrl)

  const current = new URL(page.url())
  expect(current.searchParams.get('pipeline')).toBe('workflow_qsiprep')
})

test('Tier2: Workflow detail renders tabs + default parameters', async ({ page }) => {
  await stubCommon(page)
  await page.route('**/api/workflows/workflow_qsiprep/schema', async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        workflow_id: 'workflow_qsiprep',
        direct_run_enabled: false,
        schema_source: 'catalog',
        schema: {
          type: 'object',
          properties: {
            workflow: { type: 'string', enum: ['qsiprep'], default: 'qsiprep' },
          },
          required: ['workflow'],
        },
        defaults: {
          schema_property_defaults: { workflow: 'qsiprep' },
          workflow_defaults: {},
          merged: { workflow: 'qsiprep' },
        },
        discovered_inputs: ['workflow'],
        missing_contract_fields: [],
      }),
    })
  })

  await page.goto('/library/workflow_qsiprep?tab=pipeline', { waitUntil: 'domcontentloaded' })
  await expect(page.getByTestId('library-workflow-detail')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'QSIPrep' })).toBeVisible()

  const stepCard = page.getByText('Step 1', { exact: true }).locator('..')
  await expect(stepCard).toBeVisible()
  await expect(stepCard.getByText('qsiprep', { exact: true })).toBeVisible()

  await page.goto('/library/workflow_qsiprep?tab=parameters', { waitUntil: 'domcontentloaded' })
  const workflowRow = page.getByText('workflow', { exact: true }).locator('..').locator('..')
  await expect(workflowRow).toBeVisible()
  await expect(workflowRow.getByText('qsiprep', { exact: true })).toBeVisible()

  await page.goto('/library/workflow_qsiprep?tab=versions', { waitUntil: 'domcontentloaded' })
  await expect(page.getByText(/Versioning metadata is not wired yet/i)).toBeVisible()
})
