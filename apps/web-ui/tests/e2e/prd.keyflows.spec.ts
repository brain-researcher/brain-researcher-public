import { test, expect } from '@playwright/test'

import { resolveE2EBaseUrl } from './base-url'

test.describe.configure({ mode: 'serial', timeout: 120_000 })

const BASE = resolveE2EBaseUrl()
const E2E_AUTH_COOKIE = 'br_e2e_auth'
const DATASET_ID = 'ds:openneuro:ds000001'
const DATASET_NAME = 'Balloon Analog Risk-taking Task'
const PIPELINE_ID = 'nilearn_connectivity'

const DATASET_DETAIL = {
  id: DATASET_ID,
  name: DATASET_NAME,
  description: 'Mock dataset for PRD keyflows smoke test.',
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

  await page.route('**/api/auth/session**', async (route: any) => {
    if (route.request().method() !== 'GET') {
      await route.continue()
      return
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        user: {
          name: 'E2E User',
          email: 'e2e@example.com',
          role: 'user',
        },
        expires: '2099-01-01T00:00:00.000Z',
      }),
    })
  })

  await page.route('**/api/analyses*', async (route: any) => {
    const req = route.request()
    const url = new URL(req.url())

    if (req.method() !== 'GET' || !url.pathname.endsWith('/api/analyses')) {
      await route.fallback()
      return
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [], count: 0, next_cursor: null }),
    })
  })
}

test('PRD key flow smoke: legacy studio entry → hub workspace → result share → demo → credits', async ({ context, page }) => {
  await page.addInitScript(() => {
    // Keep the smoke test deterministic (no persisted plan draft).
    try {
      Object.keys(localStorage)
        .filter((k) => k.startsWith('br:plan:'))
        .forEach((k) => localStorage.removeItem(k))
    } catch {
      // ignore
    }
  })

  await context.addCookies([
    {
      name: E2E_AUTH_COOKIE,
      value: '1',
      url: BASE,
    },
  ])

  await stubCommon(page)

  const sessionId = 'studio_keyflow_session'
  const runtimeId = 'rt_keyflow_session'
  const runtimeTargetUrl = `${BASE}/hub/br-marimo-${runtimeId}`

  await page.route('**/api/hub/sessions**', async (route: any) => {
    const req = route.request()
    const url = new URL(req.url())
    const handoff = {
      session_id: sessionId,
      project_id: 'proj_workspace',
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
        project_id: 'proj_workspace',
        owner_user_id: 'e2e-user',
        display_name: 'Hosted Workspace',
        runtime_profile_id: 'standard',
        runtime_session_id: runtimeId,
        assistant_session_id: 'ast_keyflow_session',
        status: 'ready',
        metadata: {},
        created_at: '2026-05-26T00:00:00Z',
        updated_at: '2026-05-26T00:00:00Z',
        last_activity_at: '2026-05-26T00:00:00Z',
      },
      runtime: {
        id: runtimeId,
        project_id: 'proj_workspace',
        owner_user_id: 'e2e-user',
        runtime_profile_id: 'standard',
        kind: 'marimo',
        status: 'ready',
        marimo_base_url: `${BASE}/hub`,
        marimo_port: 2718,
        working_directory: 'projects/proj_workspace',
        metadata: {},
        created_at: '2026-05-26T00:00:00Z',
        updated_at: '2026-05-26T00:00:00Z',
        last_activity_at: '2026-05-26T00:00:00Z',
      },
      handoff,
    }

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
            description: 'Mock pipeline for keyflows smoke test.',
            steps: [{ order: 1, tool: 'nilearn', description: 'Connectivity computation' }],
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

  const now = Date.now()
  const runId = `e2e_keyflow_${now}`
  const threadId = 'thread_keyflow'
  const shareToken = 'keyflow_share_token'
  // /demos/[demoId] performs server-side slug resolution from the local demo index.
  // Use a real catalog slug so routing stays deterministic in E2E.
  const demoId = 'case2-cocaine-network-segregation'

  await page.route(`**/api/analyses/${runId}`, async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        analysis_id: runId,
        thread_id: threadId,
        status: 'completed',
        title: 'E2E keyflow',
        dataset: { dataset_id: DATASET_ID, name: DATASET_NAME },
        template: { template_id: PIPELINE_ID, pipeline_id: PIPELINE_ID },
        artifacts: [],
        methods: { text: 'Methods', generated: true },
        parameters: {},
      }),
    })
  })

  await page.route(`**/api/analyses/${runId}/observation`, async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        run_card: {
          id: runId,
          outputs: { text: '- Processed 16 subjects\n- Generated a connectivity matrix\n- Exported a report\n' },
          artifacts: [],
          execution: { steps: [] },
          provenance: { nodes: [], edges: [] },
          citations: [],
          reproducibility: {},
        },
      }),
    })
  })

  await page.route(`**/api/analyses/${runId}/share`, async (route: any) => {
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
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        analysis_id: runId,
        status: 'completed',
        title: 'E2E keyflow share',
        share_level: 'summary',
        dataset: { dataset_id: DATASET_ID, name: DATASET_NAME },
        template: { template_id: PIPELINE_ID, pipeline_id: PIPELINE_ID },
        artifacts: [],
        methods: { text: 'Methods', generated: true },
        parameters: {},
      }),
    })
  })

  await page.route('**/api/demo/index', async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        demos: [
          {
            slug: demoId,
            analysis_id: demoId,
            title: 'E2E Demo',
            description: 'Synthetic demo for keyflow smoke test.',
            tags: ['demo'],
            created_at: new Date().toISOString(),
          },
        ],
      }),
    })
  })

  await page.route(`**/api/analyses/${demoId}`, async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        analysis_id: demoId,
        thread_id: null,
        status: 'completed',
        title: 'E2E Demo',
        dataset: { dataset_id: DATASET_ID, name: DATASET_NAME },
        template: { template_id: PIPELINE_ID, pipeline_id: PIPELINE_ID },
        artifacts: [],
        methods: { text: 'Methods', generated: true },
        parameters: {},
      }),
    })
  })

  await page.route(`**/api/demo/replay/${demoId}`, async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        demo: {
          slug: demoId,
          analysis_id: demoId,
          title: 'E2E Demo Replay',
          description: 'Synthetic demo for keyflow smoke test.',
          is_template: false,
        },
        analysis: {
          analysis_id: demoId,
          status: 'completed',
          title: 'E2E Demo Replay',
          created_at: Math.floor(Date.now() / 1000),
          started_at: Math.floor(Date.now() / 1000),
          finished_at: Math.floor(Date.now() / 1000),
          warnings: [],
        },
        prompt: {
          primary_prompt: 'Summarize this demo replay.',
          followup_prompts: [],
          coding_agent_prompts: [],
          mcp_prompts: [],
          source_path: null,
        },
        presentation: {
          mode: 'curated',
          overview: 'Synthetic replay payload for keyflow smoke.',
          disclaimer: 'E2E synthetic replay payload.',
        },
        replay: {
          source: 'synthetic',
          steps: [
            {
              step_id: 'stage_r1_1',
              stage: 'R1',
              title: 'Replay step',
              status: 'completed',
              tool: null,
              tool_calls: [],
              prompt_text: 'Run replay',
              response_text: 'Replay completed',
              artifact_refs: [],
              started_at: null,
              finished_at: null,
              duration_ms: null,
            },
          ],
        },
        reference_output: {
          summary: 'Replay summary',
          highlights: ['Synthetic highlight'],
          documents: [],
          generated_at: new Date().toISOString(),
          dataset_version: null,
        },
        reproduce: {
          requirements: [],
          commands: ['echo replay'],
          snippets: [],
          source_path: null,
        },
        bundle: {
          available: true,
          generated_at: null,
          artifact_count: 0,
          source_run_ids: [],
          items: [],
        },
        notes: [],
      }),
    })
  })

  await page.route('**/api/credits/balance', async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        workspace_id: 'workspace_e2e',
        user_id: 'user_e2e',
        balance: 450,
        balance_milli: 450000,
        updated_at: '2026-05-26T00:00:00Z',
      }),
    })
  })

  await page.route('**/api/credits/api-usd/balance', async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        workspace_id: 'workspace_e2e',
        user_id: 'user_e2e',
        bucket: 'api_usd',
        currency: 'USD',
        balance: 0,
        balance_milli: 0,
        updated_at: '2026-05-26T00:00:00Z',
      }),
    })
  })

  await page.route('**/api/credits/ledger**', async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ items: [], next_cursor: null }),
    })
  })

  await page.goto(
    `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&datasetId=${encodeURIComponent(DATASET_ID)}`,
    { waitUntil: 'domcontentloaded' },
  )

  await expect(page).toHaveURL(/\/hub\?/)
  await expect(page.getByText(/Hosted Marimo Workspace/i)).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText(new RegExp(`Session ${sessionId}`))).toBeVisible()
  await expect(page.locator('iframe[title="Hosted Marimo workspace"]')).toHaveAttribute(
    'src',
    `${runtimeTargetUrl}?session_id=${sessionId}`,
  )

  // Results/share are now validated from the canonical result-package route instead of
  // the retired in-Studio plan canvas.
  await page.goto(`/analyses/${runId}`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'E2E keyflow' })).toBeVisible({
    timeout: 30_000,
  })

  // A run should expose Share in the top bar.
  const shareButton = page.getByRole('button', { name: 'Share', exact: true }).first()
  await expect(shareButton).toBeVisible({ timeout: 30_000 })

  // Share: open modal and generate link.
  await shareButton.click()
  const shareDialog = page.getByRole('dialog', { name: 'Share Result Package' })
  await expect(shareDialog).toBeVisible()

  // Clicking "Copy" triggers link creation; clipboard may be unavailable in headless.
  await shareDialog.getByRole('button', { name: 'Copy' }).click()
  const shareLinkInput = shareDialog.getByPlaceholder('Generate a link to share…')
  await expect(shareLinkInput).toHaveValue(/\/share\//, { timeout: 30_000 })
  const shareUrl = await shareLinkInput.inputValue()

  // Visit share URL and ensure read-only banner renders.
  await page.goto(shareUrl, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('Shared Result Package (read-only)')).toBeVisible({ timeout: 30_000 })

  // Demo: open catalog and ensure at least one demo card is shown.
  await page.goto('/demos', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: 'Demo Runs' })).toBeVisible()
  const firstDemoLink = page.getByRole('link', { name: /open replay/i }).first()
  await expect(firstDemoLink).toBeVisible()
  await firstDemoLink.click()
  // Next dev compiles this route on-demand; wait for navigation and replay shell.
  await page.waitForURL(/\/demos\/[^?]+/, { timeout: 30_000 })
  await expect(page.getByRole('link', { name: /Back to Demos/i })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('heading', { name: 'E2E Demo Replay' })).toBeVisible({
    timeout: 30_000,
  })
  await expect(page.getByText('The Prompt')).toBeVisible({ timeout: 30_000 })

  // Credits: ensure Settings reflects the browser-facing credits API.
  await page.goto('/settings?tab=credits', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('tab', { name: 'Credits' })).toBeVisible()
  await expect(page.getByText('450 credits')).toBeVisible({
    timeout: 10_000,
  })
})

test('PRD regression: Failed analysis result package exposes diagnostics and handoff links', async ({ page }) => {
  await stubCommon(page)
  await page.context().addCookies([
    {
      name: 'br_e2e_auth',
      value: '1',
      domain: 'localhost',
      path: '/',
    },
  ])

  // Create a deterministic failed analysis view without relying on a worker executing a run.
  // This validates the current result-package diagnostics surface even when the backend is slow or queued.
  const runId = `e2e_failed_${Date.now()}`

  await page.route(`**/api/analyses/${runId}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        analysis_id: runId,
        id: runId,
        thread_id: 'thread_diagnosis_e2e',
        status: 'failed',
        title: 'E2E forced failure',
        dataset: { dataset_id: 'ds:openneuro:ds000001', name: 'Balloon Analog Risk-taking Task' },
        template: {
          template_id: 'fmriprep',
          pipeline_id: 'fmriprep',
          name: 'fmriprep',
        },
        warnings: ['Missing required arguments'],
        preflight: {
          status: 'failed',
          route: 'fmriprep',
          detail: 'Missing required arguments',
        },
        steps_summary: [
          {
            id: 'step-1',
            name: 'fmriprep',
            tool: 'fmriprep',
            status: 'failed',
            detail: 'Missing required arguments',
          },
        ],
        logs_summary: [
          {
            name: 'stderr.log',
            path: 'logs/stderr.log',
            kind: 'stderr',
            url: `/api/analyses/${runId}/artifacts/download?url=logs%2Fstderr.log`,
          },
        ],
      }),
    })
  })

  await page.route(`**/api/analyses/${runId}/observation**`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        run_card: {
          id: runId,
          version: 'e2e',
          created_at: new Date().toISOString(),
          prompt: 'E2E forced failure',
          analysis: {
            name: 'E2E forced failure',
            description: 'Diagnosis wiring regression test',
            pipeline: 'fmriprep',
          },
          datasets: [
            {
              id: 'ds:openneuro:ds000001',
              name: 'Balloon Analog Risk-taking Task',
              source: 'openneuro',
              n_subjects: 16,
            },
          ],
          tools: [{ name: 'fmriprep', version: '23.0.0' }],
          parameters: {},
          outputs: { artifacts: [] },
          artifacts: [],
          execution: {
            steps: [
              {
                id: 'step-1',
                name: 'fmriprep',
                tool: 'fmriprep',
                args: {},
                status: 'failed',
                error: 'Missing required arguments',
              },
            ],
          },
          provenance: { nodes: [], edges: [] },
          citations: [],
          reproducibility: {},
        },
      }),
    })
  })

  await page.goto(`/analyses/${encodeURIComponent(runId)}`, {
    waitUntil: 'domcontentloaded',
  })

  await expect(page.getByRole('heading', { name: 'E2E forced failure' })).toBeVisible({
    timeout: 30_000,
  })
  await expect(page.getByText('Result Package: evidence · diagnostics · reproducibility')).toBeVisible()
  await expect(page.getByText('Run trace evidence')).toBeVisible()
  await expect(page.getByText('Preflight snapshot')).toBeVisible()
  await expect(page.getByText('Steps summary')).toBeVisible()
  await expect(page.getByText('Logs & trace files')).toBeVisible()
  await expect(page.getByText('Missing required arguments').first()).toBeVisible()

  const reviewPlan = page.getByRole('link', { name: 'Review plan in Studio' })
  await expect(reviewPlan).toBeVisible()
  await expect(reviewPlan).toHaveAttribute(
    'href',
    '/studio?tab=plan&pipeline=fmriprep&datasetId=ds%3Aopenneuro%3Ads000001&thread=thread_diagnosis_e2e',
  )

  const mcpHandoff = page.getByRole('link', { name: 'Continue via MCP recipe' })
  await expect(mcpHandoff).toBeVisible()
})

test('PRD regression: Share revoke invalidates the link (revocable=true)', async ({ page }) => {
  await stubCommon(page)

  const analysisId = `e2e_revoke_${Date.now()}`
  const shareToken = `revoke_${Date.now()}`

  await page.route(`**/api/analyses/${analysisId}`, async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        analysis_id: analysisId,
        thread_id: null,
        status: 'completed',
        title: 'E2E revoke share link',
        dataset: { dataset_id: DATASET_ID, name: DATASET_NAME },
        template: { template_id: PIPELINE_ID, pipeline_id: PIPELINE_ID },
        artifacts: [],
        methods: { text: 'Methods', generated: true },
        parameters: {},
      }),
    })
  })

  await page.route(`**/api/analyses/${analysisId}/observation`, async (route: any) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        run_card: {
          id: analysisId,
          outputs: { text: '- Exported a report\n' },
          artifacts: [],
          execution: { steps: [] },
          provenance: { nodes: [], edges: [] },
          citations: [],
          reproducibility: {},
        },
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
      status: 410,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'Share link has been revoked.' }),
    })
  })

  await page.goto(`/analyses/${encodeURIComponent(analysisId)}`, {
    waitUntil: 'domcontentloaded',
  })

  const shareButton = page.getByRole('button', { name: 'Share', exact: true }).first()
  await expect(shareButton).toBeVisible({ timeout: 30_000 })
  await shareButton.click()

  const shareDialog = page.getByRole('dialog', { name: 'Share Result Package' })
  await expect(shareDialog).toBeVisible()

  await shareDialog.getByRole('button', { name: 'Copy' }).click()
  const shareLinkInput = shareDialog.getByPlaceholder('Generate a link to share…')
  await expect(shareLinkInput).toHaveValue(/\/share\//, { timeout: 30_000 })
  const shareUrl = await shareLinkInput.inputValue()

  const revokeButton = shareDialog.getByRole('button', { name: 'Revoke Access' })
  await expect(revokeButton).toBeEnabled()

  page.once('dialog', (dialog) => dialog.accept())
  await revokeButton.click()

  await shareDialog.getByRole('button', { name: 'Done' }).click()

  await page.goto(shareUrl, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('Share link has been revoked.')).toBeVisible({ timeout: 30_000 })
})

test('PRD regression: Typed analysis stream renders known + unknown events', async ({ page }) => {
  const runId = `e2e_stream_${Date.now()}`
  const now = new Date().toISOString()

  await stubCommon(page)
  await page.context().addCookies([
    {
      name: 'br_e2e_auth',
      value: '1',
      domain: 'localhost',
      path: '/',
    },
  ])

  await page.addInitScript(() => {
    localStorage.setItem('br:settings:preferences', JSON.stringify({ advancedMode: true }))
  })

  await page.route(`**/api/analyses/${runId}`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        analysis_id: runId,
        status: 'running',
      }),
    })
  })

  await page.route(`**/api/analyses/${runId}/observation**`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        run_card: {
          id: runId,
          execution: { steps: [] },
          outputs: { artifacts: [] },
          artifacts: [],
          provenance: { nodes: [], edges: [] },
          citations: [],
          reproducibility: {},
        },
      }),
    })
  })

  await page.route(`**/api/analyses/${runId}/runcard**`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: runId,
        execution: { steps: [] },
        outputs: { artifacts: [] },
        artifacts: [],
        provenance: { nodes: [], edges: [] },
        citations: [],
        reproducibility: {},
      }),
    })
  })

  await page.route(`**/api/analyses/${runId}/steps`, async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        job_id: runId,
        state: 'queued',
        steps: [],
      }),
    })
  })

  await page.route(`**/api/analyses/${runId}/steps/stream**`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: {
        'content-type': 'text/event-stream; charset=utf-8',
        'cache-control': 'no-cache',
        connection: 'keep-alive',
      },
      body: `event: complete\ndata: ${JSON.stringify({ job_id: runId, final_state: 'queued', total_steps: 0 })}\n\n`,
    })
  })

  await page.route(`**/api/analyses/${runId}/stream`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: {
        'content-type': 'text/event-stream; charset=utf-8',
        'cache-control': 'no-cache',
        connection: 'keep-alive',
      },
      body: `event: stage\ndata: ${JSON.stringify({ status: 'running', overall_progress: 45 })}\n\n`,
    })
  })

  const sseEvents = [
    {
      schema_version: 'analysis-stream-event-v1',
      seq: 1,
      timestamp: now,
      event_type: 'job.started',
      payload: { status: 'running', message: 'starting' },
    },
    {
      schema_version: 'analysis-stream-event-v1',
      seq: 2,
      timestamp: now,
      event_type: 'tool.call.started',
      payload: {
        tool_call_id: 'tc-1',
        tool_id: 'fmriprep',
        params: { mock: true },
      },
    },
    {
      schema_version: 'analysis-stream-event-v1',
      seq: 3,
      timestamp: now,
      event_type: 'log.line',
      payload: { stream: 'stdout', line: 'Hello from tool' },
    },
    {
      schema_version: 'analysis-stream-event-v1',
      seq: 4,
      timestamp: now,
      event_type: 'artifact.written',
      payload: {
        artifact: {
          schema_version: 'artifact-v1',
          kind: 'file',
          uri: 'file://mock/output/report.html',
          media_type: 'text/html',
        },
      },
    },
    {
      schema_version: 'analysis-stream-event-v1',
      seq: 5,
      timestamp: now,
      event_type: 'new.event.type',
      payload: { note: 'This event should render as unknown.' },
    },
    {
      schema_version: 'analysis-stream-event-v1',
      seq: 6,
      timestamp: now,
      event_type: 'analysis.completed',
      payload: { status: 'succeeded', message: 'done' },
    },
  ]

  const sseBody = sseEvents
    .map((evt) => `event: analysis_stream_event\ndata: ${JSON.stringify(evt)}\n\n`)
    .join('')

  await page.route(`**/api/analyses/${runId}/analysis-stream**`, async (route) => {
    await route.fulfill({
      status: 200,
      headers: {
        'content-type': 'text/event-stream; charset=utf-8',
        'cache-control': 'no-cache',
        connection: 'keep-alive',
      },
      body: sseBody,
    })
  })

  await page.goto(`/analyses/${encodeURIComponent(runId)}`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByText('Diagnostics stream')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByText('tool=fmriprep')).toBeVisible({ timeout: 10_000 })
  await expect(page.getByText('Hello from tool', { exact: true })).toBeVisible()
  await expect(page.getByText('analysis.completed', { exact: true })).toBeVisible()
  await expect(page.getByText('Unknown event')).toBeVisible()
})
