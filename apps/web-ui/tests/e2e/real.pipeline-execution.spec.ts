import { test, expect } from '@playwright/test'

type AnalysisStatus =
  | 'pending'
  | 'queued'
  | 'running'
  | 'completed'
  | 'failed'
  | 'cancelled'
  | 'cancelling'
  | 'retrying'
  | 'paused'
  | 'timeout'
  | 'unknown'

const DEFAULT_DATASET_ID = 'ds:openneuro:ds000001'
const DEFAULT_TEMPLATE_ID = 'connectivity/nilearn_connectivity'

const DATASET_ID = process.env.BR_TEST_DATASET_ID || DEFAULT_DATASET_ID
const TEMPLATE_ID = process.env.BR_TEST_TEMPLATE_ID || DEFAULT_TEMPLATE_ID

const MAX_WAIT_MS = (() => {
  const raw = process.env.BR_TEST_MAX_RUN_MS || process.env.BR_TEST_MAX_RUN_MINUTES
  if (!raw) return 30 * 60_000
  const value = Number(raw)
  if (!Number.isFinite(value) || value <= 0) return 30 * 60_000
  // If user passes minutes, convert to ms; accept ms directly.
  return value < 1_000 ? value * 60_000 : value
})()

const ARTIFACT_WAIT_MS = (() => {
  const raw = process.env.BR_TEST_ARTIFACT_WAIT_MS
  if (!raw) return 60_000
  const value = Number(raw)
  if (!Number.isFinite(value) || value <= 0) return 60_000
  return value
})()

function safeParseJson(value: string | undefined): Record<string, unknown> | undefined {
  if (!value) return undefined
  try {
    const parsed = JSON.parse(value) as unknown
    if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
      return parsed as Record<string, unknown>
    }
  } catch {
    // ignore
  }
  return undefined
}

function normalizeStatus(value: unknown): AnalysisStatus {
  if (typeof value !== 'string') return 'unknown'
  const normalized = value.trim().toLowerCase()
  if (normalized === 'succeeded') return 'completed'
  if (normalized === 'claimed') return 'running'
  if (normalized === 'skipped') return 'cancelled'
  const allowed = new Set<AnalysisStatus>([
    'pending',
    'queued',
    'running',
    'completed',
    'failed',
    'cancelled',
    'cancelling',
    'retrying',
    'paused',
    'timeout',
    'unknown',
  ])
  return allowed.has(normalized as AnalysisStatus) ? (normalized as AnalysisStatus) : 'unknown'
}

function extractArtifacts(raw: unknown): unknown[] {
  if (!raw) return []
  if (Array.isArray(raw)) return raw
  if (typeof raw === 'object') {
    const obj = raw as any
    if (Array.isArray(obj.artifacts)) return obj.artifacts
  }
  return []
}

function extractDetailArtifacts(detail: any): unknown[] {
  const direct = extractArtifacts(detail?.artifacts)
  if (direct.length) return direct
  const planArtifacts = extractArtifacts(detail?.plan?.artifacts)
  return planArtifacts
}

function deriveDatasetQuery(datasetId: string): string {
  const decoded = decodeURIComponent(datasetId).trim()
  const openNeuroMatch = decoded.match(/ds\\d{6}/i)
  if (openNeuroMatch) return openNeuroMatch[0]
  const parts = decoded.split(':').filter(Boolean)
  const suffix = parts.at(-1)
  return suffix?.trim() ? suffix.trim() : decoded
}

async function fetchJson(page: any, url: string) {
  const resp = await page.request.get(url, { failOnStatusCode: false })
  const text = await resp.text()
  let json: any = null
  try {
    json = text ? JSON.parse(text) : null
  } catch {
    json = null
  }
  return { ok: resp.ok(), status: resp.status(), json, text }
}

async function waitForTerminalStatus(page: any, analysisId: string) {
  const terminal = new Set<AnalysisStatus>(['completed', 'failed', 'cancelled', 'timeout'])
  const start = Date.now()
  let lastStatus: AnalysisStatus = 'unknown'
  let lastDetail: any = null

  while (Date.now() - start < MAX_WAIT_MS) {
    // eslint-disable-next-line no-await-in-loop
    const result = await fetchJson(page, `/api/analyses/${encodeURIComponent(analysisId)}`)
    if (result.ok && result.json) {
      const status = normalizeStatus(result.json.status)
      lastStatus = status
      lastDetail = result.json
      if (terminal.has(status)) {
        return { status, detail: result.json }
      }
    } else {
      // Preserve last detail for debugging.
      lastDetail = result.json || result.text
    }

    // eslint-disable-next-line no-await-in-loop
    await new Promise((r) => setTimeout(r, 5_000))
  }

  throw new Error(
    `Timed out after ${Math.round(MAX_WAIT_MS / 1000)}s waiting for analysis ${analysisId} to finish. Last status=${lastStatus}. Last detail=${JSON.stringify(lastDetail)?.slice(0, 800)}`,
  )
}

async function waitForArtifacts(page: any, analysisId: string) {
  const start = Date.now()
  let lastDetail: any = null

  while (Date.now() - start < ARTIFACT_WAIT_MS) {
    // eslint-disable-next-line no-await-in-loop
    const result = await fetchJson(page, `/api/analyses/${encodeURIComponent(analysisId)}`)
    if (result.ok && result.json) {
      lastDetail = result.json
      const artifacts = extractDetailArtifacts(result.json)
      if (artifacts.length) {
        return { artifacts, detail: result.json }
      }
    } else {
      lastDetail = result.json || result.text
    }

    // eslint-disable-next-line no-await-in-loop
    await new Promise((r) => setTimeout(r, 2_500))
  }

  const summary = JSON.stringify(lastDetail)?.slice(0, 2_000)
  throw new Error(`Timed out waiting for artifacts to appear. Last detail=${summary}`)
}

test.describe('Real pipeline execution (opt-in)', () => {
  test.describe.configure({ mode: 'serial' })

  let analysisId = ''
  let resolvedDatasetId = DATASET_ID
  let finalDetail: any = null

  test('Agent is reachable via /api/health', async ({ page }) => {
    const res = await fetchJson(page, '/api/health')
    expect(res.ok).toBeTruthy()
  })

  test('Catalog dataset search resolves the test dataset', async ({ page }) => {
    const query = deriveDatasetQuery(DATASET_ID)

    const search = await fetchJson(
      page,
      `/api/catalog/datasets/search?q=${encodeURIComponent(query)}&limit=5`,
    )
    expect(search.ok, `Dataset search failed (${search.status}): ${search.text.slice(0, 200)}`).toBeTruthy()

    const datasets = Array.isArray(search.json?.datasets) ? search.json.datasets : []
    expect(
      datasets.length,
      `No datasets returned for query "${query}". Set BR_TEST_DATASET_ID or start BR-KG/catalog.`,
    ).toBeGreaterThan(0)

    const resolvedId =
      datasets.find((d: any) => d?.id === DATASET_ID)?.id || datasets[0]?.id || DATASET_ID

    resolvedDatasetId = resolvedId

    const detail = await fetchJson(
      page,
      `/api/catalog/datasets/${encodeURIComponent(resolvedId)}`,
    )
    expect(
      detail.ok,
      `Dataset detail failed (${detail.status}): ${detail.text.slice(0, 200)}`,
    ).toBeTruthy()
    expect(detail.json?.id).toBeTruthy()
  })

  test('Create analysis via /api/analyses', async ({ page }) => {
    const params = safeParseJson(process.env.BR_TEST_PARAMS_JSON)
    const title = `E2E Real · ${TEMPLATE_ID} · ${new Date().toISOString()}`

    const resp = await page.request.post('/api/analyses', {
      data: {
        dataset_id: resolvedDatasetId,
        template_id: TEMPLATE_ID,
        ...(params ? { parameters: params } : {}),
        title,
      },
      failOnStatusCode: false,
    })

    const text = await resp.text()
    expect(resp.ok(), `POST /api/analyses failed: ${resp.status()} ${text}`).toBeTruthy()

    const parsed = JSON.parse(text) as any
    analysisId = parsed?.analysis_id || parsed?.run_id || parsed?.job_id || ''
    expect(analysisId).toBeTruthy()
  })

  test('Wait for completion and verify artifacts', async ({ page }) => {
    test.setTimeout(MAX_WAIT_MS + 60_000)

    const result = await waitForTerminalStatus(page, analysisId)
    finalDetail = result.detail

    if (result.status !== 'completed') {
      const summary = JSON.stringify(finalDetail)?.slice(0, 2_000)
      throw new Error(`Analysis did not succeed (status=${result.status}). Detail=${summary}`)
    }

    let artifacts = extractDetailArtifacts(finalDetail)
    if (!artifacts.length) {
      const awaited = await waitForArtifacts(page, analysisId)
      artifacts = awaited.artifacts
      finalDetail = awaited.detail
    }
    expect(artifacts.length, 'Expected at least one artifact after completion').toBeGreaterThan(0)
  })

  test('Export bundle is downloadable', async ({ page }) => {
    const resp = await page.request.get(`/api/analyses/${encodeURIComponent(analysisId)}/export`, {
      failOnStatusCode: false,
    })
    const body = await resp.body().catch(() => Buffer.from(''))
    expect(resp.ok(), `GET export failed: ${resp.status()} ${body.slice(0, 200).toString()}`).toBeTruthy()
    expect(body.length).toBeGreaterThan(0)
  })

  test('Run detail page renders', async ({ page }) => {
    await page.goto(`/analyses/${encodeURIComponent(analysisId)}`)
    await expect(page.getByText('Execution status')).toBeVisible()
    // Status badge should show completed.
    await expect(page.getByText(/^completed$/i)).toBeVisible({ timeout: 60_000 })

    // Artifacts list should be present when the API returned artifacts.
    const artifacts = extractDetailArtifacts(finalDetail)
    if (artifacts.length) {
      await expect(page.getByRole('heading', { name: 'Evidence & outputs' })).toBeVisible()
    }
  })
})
