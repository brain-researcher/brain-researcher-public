import { test, expect } from '@playwright/test'

/**
 * PRD v1.2.2 planned tests for workflow execution UI.
 *
 * This suite covers the retired in-page Studio execution editor
 * (DAG view, typed inputs, streaming console/artifacts). The active Studio
 * entry now redirects into the hosted Hub workspace, so these tests are kept
 * as archived expectations until a new hosted-workspace equivalent exists.
 */

test.describe.configure({ mode: 'serial', timeout: 120_000 })

const DATASET_ID = 'ds:openneuro:ds000001'
const PIPELINE_ID = 'nilearn_connectivity'

const DATASET_DETAIL = {
  id: DATASET_ID,
  name: 'Balloon Analog Risk-taking Task',
  description: 'Mock dataset detail for PRD planned workflow execution tests.',
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

async function stubPlannedDagBasics(page: any) {
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
            name: 'Nilearn Connectivity',
            description: 'Mock pipeline for DAG view tests.',
            modalities: ['fmri'],
            steps: [
              {
                order: 1,
                tool: 'nilearn',
                description: 'Connectivity computation',
                paramNames: ['atlas', 'required_field', 'optional_field'],
                schemas: {
                  v1: {
                    version: 'v1',
                    required: ['required_field'],
                    properties: {
                      atlas: { type: 'string', enum: ['schaefer-200', 'aal'], default: 'schaefer-200' },
                      required_field: { type: 'string', default: 'hello' },
                      optional_field: { type: 'integer', default: 2 },
                    },
                  },
                  v2: {
                    version: 'v2',
                    required: ['required_field'],
                    properties: {
                      atlas: { type: 'string', enum: ['schaefer-200', 'aal', 'yeo'], default: 'yeo' },
                      required_field: { type: 'string', default: 'hello v2' },
                    },
                  },
                },
              },
              {
                order: 2,
                tool: 'report',
                description: 'Generate outputs',
                paramNames: [],
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

test.describe.skip('PRD planned: retired in-page Workflow Execution UI', () => {
  test('P2: Plan DAG View toggle exists and switches views', async ({ page }) => {
    await stubPlannedDagBasics(page)

    await page.goto(
      `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&datasetId=${encodeURIComponent(DATASET_ID)}`,
      { waitUntil: 'domcontentloaded' },
    )

    await openAdvancedPlanEditor(page)

    await expect(page.getByTestId('plan-view-toggle-card')).toBeVisible()
    await expect(page.getByTestId('plan-view-toggle-dag')).toBeVisible()

    await page.getByTestId('plan-view-toggle-dag').click()
    await expect(page.getByTestId('plan-dag-view')).toBeVisible()
  })

  test('P2b: DAG edges use stable ids', async ({ page }) => {
    await stubPlannedDagBasics(page)

    await page.goto(
      `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&datasetId=${encodeURIComponent(DATASET_ID)}`,
      { waitUntil: 'domcontentloaded' },
    )

    await openAdvancedPlanEditor(page)
    await page.getByTestId('plan-view-toggle-dag').click()

    const edge = page.getByTestId('dag-edge-edge-step-1-step-2')
    await expect(edge).toHaveCount(1)
    await expect(edge).toHaveAttribute('data-status', 'pending')
  })

  test('P3: Clicking a DAG node opens Step Inspector', async ({ page }) => {
    await stubPlannedDagBasics(page)

    await page.goto(
      `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&datasetId=${encodeURIComponent(DATASET_ID)}`,
      { waitUntil: 'domcontentloaded' },
    )

    await openAdvancedPlanEditor(page)
    await page.getByTestId('plan-view-toggle-dag').click()

    await page.getByTestId('dag-node-step-1').click()
    await expect(page.getByTestId('step-inspector')).toBeVisible()
  })

  test('P5: DAG nodes reflect step status updates', async ({ page }) => {
    const runId = `e2e_planned_dag_status_${Date.now()}`

    await stubPlannedDagBasics(page)

    await page.route(`**/api/analyses/${runId}/steps`, async (route: any) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          job_id: runId,
          state: 'running',
          steps: [
            { step_id: 'step-1', state: 'pending' },
            { step_id: 'step-2', state: 'pending' },
          ],
        }),
      })
    })

    await page.route(`**/api/analyses/${runId}/steps/stream**`, async (route: any) => {
      const update = {
        job_id: runId,
        state: 'running',
        steps: [
          { step_id: 'step-1', state: 'running' },
          { step_id: 'step-2', state: 'failed', error: 'boom' },
        ],
      }

      await route.fulfill({
        status: 200,
        headers: {
          'content-type': 'text/event-stream; charset=utf-8',
          'cache-control': 'no-cache',
          connection: 'keep-alive',
        },
        body: `event: steps_update\ndata: ${JSON.stringify(update)}\n\n`,
      })
    })

    await page.goto(
      `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&datasetId=${encodeURIComponent(DATASET_ID)}&analysisId=${encodeURIComponent(runId)}`,
      { waitUntil: 'domcontentloaded' },
    )

    await openAdvancedPlanEditor(page)
    await page.getByTestId('plan-view-toggle-dag').click()

    await expect(page.getByTestId('dag-node-step-1')).toHaveAttribute('data-status', 'running')
    await expect(page.getByTestId('dag-node-step-2')).toHaveAttribute('data-status', 'failed')
    const edge = page.getByTestId('dag-edge-edge-step-1-step-2')
    await expect(edge).toHaveCount(1)
    await expect(edge).toHaveAttribute('data-status', 'failed')
  })

  test('P4: DAG supports zoom + pan (smoke)', async ({ page }) => {
    await stubPlannedDagBasics(page)

    await page.goto(
      `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&datasetId=${encodeURIComponent(DATASET_ID)}`,
      { waitUntil: 'domcontentloaded' },
    )

    await openAdvancedPlanEditor(page)
    await page.getByTestId('plan-view-toggle-dag').click()

    const dag = page.getByTestId('plan-dag-view')
    const viewport = page.getByTestId('dag-viewport')

    const zoom0 = Number.parseFloat((await viewport.getAttribute('data-zoom')) ?? '1')
    const x0 = Number.parseFloat((await viewport.getAttribute('data-x')) ?? '0')
    const y0 = Number.parseFloat((await viewport.getAttribute('data-y')) ?? '0')

    const box = await dag.boundingBox()
    if (!box) throw new Error('Missing DAG bounding box')

    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.wheel(0, -400)

    await expect
      .poll(async () => Number.parseFloat((await viewport.getAttribute('data-zoom')) ?? '1'))
      .toBeGreaterThan(zoom0)

    await page.keyboard.down(' ')
    await page.mouse.down()
    await page.mouse.move(box.x + box.width / 2 + 80, box.y + box.height / 2 + 40)
    await page.mouse.up()
    await page.keyboard.up(' ')

    await expect
      .poll(async () => {
        const x = Number.parseFloat((await viewport.getAttribute('data-x')) ?? '0')
        const y = Number.parseFloat((await viewport.getAttribute('data-y')) ?? '0')
        return { x, y }
      })
      .not.toEqual({ x: x0, y: y0 })
  })

  test('P8: Holding Space enables pan; otherwise drag does not pan', async ({ page }) => {
    await stubPlannedDagBasics(page)

    await page.goto(
      `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&datasetId=${encodeURIComponent(DATASET_ID)}`,
      { waitUntil: 'domcontentloaded' },
    )

    await openAdvancedPlanEditor(page)
    await page.getByTestId('plan-view-toggle-dag').click()

    const dag = page.getByTestId('plan-dag-view')
    const viewport = page.getByTestId('dag-viewport')

    await dag.click({ position: { x: 20, y: 20 } })

    const x0 = Number.parseFloat((await viewport.getAttribute('data-x')) ?? '0')
    const y0 = Number.parseFloat((await viewport.getAttribute('data-y')) ?? '0')

    const box = await dag.boundingBox()
    if (!box) throw new Error('Missing DAG bounding box')

    const startX = box.x + 30
    const startY = box.y + 30

    await page.mouse.move(startX, startY)
    await page.mouse.down()
    await page.mouse.move(startX + 120, startY + 60)
    await page.mouse.up()

    await expect
      .poll(async () => {
        const x = Number.parseFloat((await viewport.getAttribute('data-x')) ?? '0')
        const y = Number.parseFloat((await viewport.getAttribute('data-y')) ?? '0')
        return { x, y }
      })
      .toEqual({ x: x0, y: y0 })

    await page.keyboard.down('Space')
    await expect(dag).toHaveAttribute('data-space-pressed', 'true')
    await page.mouse.move(startX, startY)
    await page.mouse.down()
    await page.mouse.move(startX + 120, startY + 60)
    await page.mouse.up()
    await page.keyboard.up('Space')
    await expect(dag).toHaveAttribute('data-space-pressed', 'false')

    await expect
      .poll(async () => {
        const x = Number.parseFloat((await viewport.getAttribute('data-x')) ?? '0')
        const y = Number.parseFloat((await viewport.getAttribute('data-y')) ?? '0')
        return { x, y }
      })
      .not.toEqual({ x: x0, y: y0 })
  })

  test('P8b: Holding Space allows panning even when drag starts on a node', async ({ page }) => {
    await stubPlannedDagBasics(page)

    await page.goto(
      `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&datasetId=${encodeURIComponent(DATASET_ID)}`,
      { waitUntil: 'domcontentloaded' },
    )

    await openAdvancedPlanEditor(page)
    await page.getByTestId('plan-view-toggle-dag').click()

    const dag = page.getByTestId('plan-dag-view')
    const viewport = page.getByTestId('dag-viewport')

    await dag.click({ position: { x: 20, y: 20 } })

    const x0 = Number.parseFloat((await viewport.getAttribute('data-x')) ?? '0')
    const y0 = Number.parseFloat((await viewport.getAttribute('data-y')) ?? '0')

    const node = page.getByTestId('dag-node-step-1')
    const nodeBox = await node.boundingBox()
    if (!nodeBox) throw new Error('Missing DAG node bounding box')

    await page.keyboard.down('Space')
    await expect(dag).toHaveAttribute('data-space-pressed', 'true')

    await page.mouse.move(nodeBox.x + nodeBox.width / 2, nodeBox.y + nodeBox.height / 2)
    await page.mouse.down()
    await page.mouse.move(nodeBox.x + nodeBox.width / 2 + 140, nodeBox.y + nodeBox.height / 2 + 60)
    await page.mouse.up()

    await page.keyboard.up('Space')

    await expect
      .poll(async () => {
        const x = Number.parseFloat((await viewport.getAttribute('data-x')) ?? '0')
        const y = Number.parseFloat((await viewport.getAttribute('data-y')) ?? '0')
        return { x, y }
      })
      .not.toEqual({ x: x0, y: y0 })

    await expect(page.getByTestId('step-inspector')).not.toBeVisible()
  })

  test('P8c: Pan cursor switches between grab/grabbing while Space is held', async ({ page }) => {
    await stubPlannedDagBasics(page)

    await page.goto(
      `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&datasetId=${encodeURIComponent(DATASET_ID)}`,
      { waitUntil: 'domcontentloaded' },
    )

    await openAdvancedPlanEditor(page)
    await page.getByTestId('plan-view-toggle-dag').click()

    const dag = page.getByTestId('plan-dag-view')
    const box = await dag.boundingBox()
    if (!box) throw new Error('Missing DAG bounding box')

    await expect(dag).not.toHaveClass(/cursor-grab/)
    await page.keyboard.down('Space')
    await expect(dag).toHaveAttribute('data-space-pressed', 'true')
    await expect(dag).toHaveClass(/cursor-grab/)

    await page.mouse.move(box.x + 30, box.y + 30)
    await page.mouse.down()
    await expect(dag).toHaveClass(/cursor-grabbing/)
    await page.mouse.up()

    await expect(dag).toHaveClass(/cursor-grab/)
    await page.keyboard.up('Space')
    await expect(dag).not.toHaveClass(/cursor-grab/)
  })

  test('P8d: Holding Space allows panning when drag starts on an edge', async ({ page }) => {
    await stubPlannedDagBasics(page)

    await page.goto(
      `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&datasetId=${encodeURIComponent(DATASET_ID)}`,
      { waitUntil: 'domcontentloaded' },
    )

    await openAdvancedPlanEditor(page)
    await page.getByTestId('plan-view-toggle-dag').click()

    const dag = page.getByTestId('plan-dag-view')
    const viewport = page.getByTestId('dag-viewport')

    await dag.click({ position: { x: 20, y: 20 } })

    const x0 = Number.parseFloat((await viewport.getAttribute('data-x')) ?? '0')
    const y0 = Number.parseFloat((await viewport.getAttribute('data-y')) ?? '0')

    const edge = page.getByTestId('dag-edge-edge-step-1-step-2')
    const edgeBox = await edge.boundingBox()
    if (!edgeBox) throw new Error('Missing DAG edge bounding box')

    await page.keyboard.down('Space')
    await expect(dag).toHaveAttribute('data-space-pressed', 'true')

    await page.mouse.move(edgeBox.x + edgeBox.width / 2, edgeBox.y + edgeBox.height / 2)
    await page.mouse.down()
    await page.mouse.move(edgeBox.x + edgeBox.width / 2 + 160, edgeBox.y + edgeBox.height / 2 + 60)
    await page.mouse.up()

    await page.keyboard.up('Space')

    await expect
      .poll(async () => {
        const x = Number.parseFloat((await viewport.getAttribute('data-x')) ?? '0')
        const y = Number.parseFloat((await viewport.getAttribute('data-y')) ?? '0')
        return { x, y }
      })
      .not.toEqual({ x: x0, y: y0 })
  })

  test('P8e: Holding Space prevents opening the Step Inspector', async ({ page }) => {
    await stubPlannedDagBasics(page)

    await page.goto(
      `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&datasetId=${encodeURIComponent(DATASET_ID)}`,
      { waitUntil: 'domcontentloaded' },
    )

    await openAdvancedPlanEditor(page)
    await page.getByTestId('plan-view-toggle-dag').click()

    const dag = page.getByTestId('plan-dag-view')

    await dag.click({ position: { x: 20, y: 20 } })
    await page.keyboard.down('Space')
    await expect(dag).toHaveAttribute('data-space-pressed', 'true')

    await page.getByTestId('dag-node-step-1').click()
    await expect(page.getByTestId('step-inspector')).not.toBeVisible()

    await page.keyboard.up('Space')

    await page.getByTestId('dag-node-step-1').click()
    await expect(page.getByTestId('step-inspector')).toBeVisible()
  })

  test('P9: Keyboard shortcuts (+/-/0) zoom and fit view', async ({ page }) => {
    await stubPlannedDagBasics(page)

    await page.goto(
      `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&datasetId=${encodeURIComponent(DATASET_ID)}`,
      { waitUntil: 'domcontentloaded' },
    )

    await openAdvancedPlanEditor(page)
    await page.getByTestId('plan-view-toggle-dag').click()

    const dag = page.getByTestId('plan-dag-view')
    const viewport = page.getByTestId('dag-viewport')

    const box = await dag.boundingBox()
    if (!box) throw new Error('Missing DAG bounding box')

    await page.mouse.click(box.x + 20, box.y + 20)

    const zoom0 = Number.parseFloat((await viewport.getAttribute('data-zoom')) ?? '1')

    await page.keyboard.press('Shift+=')
    await expect
      .poll(async () => Number.parseFloat((await viewport.getAttribute('data-zoom')) ?? '1'))
      .toBeGreaterThan(zoom0)

    const zoomAfterPlus = Number.parseFloat((await viewport.getAttribute('data-zoom')) ?? '1')
    await page.keyboard.press('-')
    await expect
      .poll(async () => Number.parseFloat((await viewport.getAttribute('data-zoom')) ?? '1'))
      .toBeLessThan(zoomAfterPlus)

    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.wheel(0, -500)
    const zoomAfterWheel = Number.parseFloat((await viewport.getAttribute('data-zoom')) ?? '1')
    expect(zoomAfterWheel).toBeGreaterThan(1)

    await page.keyboard.press('0')
    await expect
      .poll(async () => Number.parseFloat((await viewport.getAttribute('data-zoom')) ?? '1'))
      .toBeLessThan(zoomAfterWheel)
  })

  test('P9b: Keyboard shortcuts are ignored while editing typed inputs', async ({ page }) => {
    await stubPlannedDagBasics(page)

    await page.goto(
      `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&datasetId=${encodeURIComponent(DATASET_ID)}`,
      { waitUntil: 'domcontentloaded' },
    )

    await openAdvancedPlanEditor(page)
    await page.getByTestId('plan-view-toggle-dag').click()

    const viewport = page.getByTestId('dag-viewport')

    await page.getByTestId('dag-node-step-1').click()
    const dialog = page.getByTestId('step-inspector')
    await expect(dialog).toBeVisible()

    const requiredField = dialog.getByTestId('step-param-required_field')
    await requiredField.click()

    const zoom0 = Number.parseFloat((await viewport.getAttribute('data-zoom')) ?? '1')

    await page.keyboard.press('Shift+=')
    await page.keyboard.press('0')
    await page.keyboard.press('-')

    await expect
      .poll(async () => Number.parseFloat((await viewport.getAttribute('data-zoom')) ?? '1'))
      .toBeCloseTo(zoom0, 5)
  })

  test('P6: DAG layout is horizontal', async ({ page }) => {
    await stubPlannedDagBasics(page)

    await page.goto(
      `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&datasetId=${encodeURIComponent(DATASET_ID)}`,
      { waitUntil: 'domcontentloaded' },
    )

    await openAdvancedPlanEditor(page)
    await page.getByTestId('plan-view-toggle-dag').click()

    const node1 = page.getByTestId('dag-node-step-1')
    const node2 = page.getByTestId('dag-node-step-2')
    const box1 = await node1.boundingBox()
    const box2 = await node2.boundingBox()
    if (!box1 || !box2) throw new Error('Missing DAG node bounding box')

    expect(box2.x + box2.width / 2).toBeGreaterThan(box1.x + box1.width / 2)
    expect(Math.abs(box2.y + box2.height / 2 - (box1.y + box1.height / 2))).toBeLessThan(60)
  })

  test('P7: DAG fit view control resets viewport after zooming', async ({ page }) => {
    await stubPlannedDagBasics(page)

    await page.goto(
      `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&datasetId=${encodeURIComponent(DATASET_ID)}`,
      { waitUntil: 'domcontentloaded' },
    )

    await openAdvancedPlanEditor(page)
    await page.getByTestId('plan-view-toggle-dag').click()

    const dag = page.getByTestId('plan-dag-view')
    const viewport = page.getByTestId('dag-viewport')

    const box = await dag.boundingBox()
    if (!box) throw new Error('Missing DAG bounding box')

    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.wheel(0, -400)

    await expect
      .poll(async () => Number.parseFloat((await viewport.getAttribute('data-zoom')) ?? '1'))
      .toBeGreaterThan(1)
    const zoomAfterZoom = Number.parseFloat((await viewport.getAttribute('data-zoom')) ?? '1')

    await page.getByTestId('dag-fitview').click()
    await expect
      .poll(async () => Number.parseFloat((await viewport.getAttribute('data-zoom')) ?? '1'))
      .toBeLessThan(zoomAfterZoom)
  })

  test('P7b: DAG reset control returns viewport to origin', async ({ page }) => {
    await stubPlannedDagBasics(page)

    await page.goto(
      `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&datasetId=${encodeURIComponent(DATASET_ID)}`,
      { waitUntil: 'domcontentloaded' },
    )

    await openAdvancedPlanEditor(page)
    await page.getByTestId('plan-view-toggle-dag').click()

    const dag = page.getByTestId('plan-dag-view')
    const viewport = page.getByTestId('dag-viewport')

    const box = await dag.boundingBox()
    if (!box) throw new Error('Missing DAG bounding box')

    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.wheel(0, -400)

    await page.keyboard.down('Space')
    await page.mouse.move(box.x + 40, box.y + 40)
    await page.mouse.down()
    await page.mouse.move(box.x + 180, box.y + 120)
    await page.mouse.up()
    await page.keyboard.up('Space')

    await expect
      .poll(async () => {
        const x = Number.parseFloat((await viewport.getAttribute('data-x')) ?? '0')
        const y = Number.parseFloat((await viewport.getAttribute('data-y')) ?? '0')
        const zoom = Number.parseFloat((await viewport.getAttribute('data-zoom')) ?? '1')
        return { x, y, zoom }
      })
      .not.toEqual({ x: 0, y: 0, zoom: 1 })

    await page.getByTestId('dag-reset').click()

    await expect
      .poll(async () => {
        const x = Number.parseFloat((await viewport.getAttribute('data-x')) ?? '0')
        const y = Number.parseFloat((await viewport.getAttribute('data-y')) ?? '0')
        const zoom = Number.parseFloat((await viewport.getAttribute('data-zoom')) ?? '1')
        return { x, y, zoom }
      })
      .toEqual({ x: 0, y: 0, zoom: 1 })
  })

  test('P7c: Zoom buttons update viewport zoom', async ({ page }) => {
    await stubPlannedDagBasics(page)

    await page.goto(
      `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&datasetId=${encodeURIComponent(DATASET_ID)}`,
      { waitUntil: 'domcontentloaded' },
    )

    await openAdvancedPlanEditor(page)
    await page.getByTestId('plan-view-toggle-dag').click()

    const viewport = page.getByTestId('dag-viewport')

    const zoom0 = Number.parseFloat((await viewport.getAttribute('data-zoom')) ?? '1')

    await page.getByTestId('dag-zoom-in').click()
    await expect
      .poll(async () => Number.parseFloat((await viewport.getAttribute('data-zoom')) ?? '1'))
      .toBeGreaterThan(zoom0)

    const zoomAfterIn = Number.parseFloat((await viewport.getAttribute('data-zoom')) ?? '1')
    await page.getByTestId('dag-zoom-out').click()
    await expect
      .poll(async () => Number.parseFloat((await viewport.getAttribute('data-zoom')) ?? '1'))
      .toBeLessThan(zoomAfterIn)
  })

  test('S1: Step Inspector renders typed inputs with required markers', async ({ page }) => {
    await stubPlannedDagBasics(page)

    await page.goto(
      `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&datasetId=${encodeURIComponent(DATASET_ID)}`,
      { waitUntil: 'domcontentloaded' },
    )

    await openAdvancedPlanEditor(page)
    await page.getByTestId('plan-view-toggle-dag').click()
    await page.getByTestId('dag-node-step-1').click()

    const dialog = page.getByTestId('step-inspector')
    await expect(dialog).toBeVisible()
    await expect(dialog.getByTestId('step-label-required_field')).toContainText('*')
    await expect(dialog.getByTestId('step-label-optional_field')).not.toContainText('*')
  })

  test('S3: Step Inspector version switch updates schema/params', async ({ page }) => {
    await stubPlannedDagBasics(page)

    await page.goto(
      `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&datasetId=${encodeURIComponent(DATASET_ID)}`,
      { waitUntil: 'domcontentloaded' },
    )

    await openAdvancedPlanEditor(page)
    await page.getByTestId('plan-view-toggle-dag').click()
    await page.getByTestId('dag-node-step-1').click()

    const dialog = page.getByTestId('step-inspector')
    await expect(dialog).toBeVisible()
    await expect(dialog.getByTestId('step-version-select')).toBeVisible()
    await expect(dialog.getByTestId('step-param-optional_field')).toBeVisible()

    await dialog.getByTestId('step-version-select').selectOption('v2')
    await expect(dialog.getByTestId('step-param-optional_field')).toHaveCount(0)
  })

  test('S4: Step Inspector validation disables Save and highlights field', async ({ page }) => {
    await stubPlannedDagBasics(page)

    await page.goto(
      `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&datasetId=${encodeURIComponent(DATASET_ID)}`,
      { waitUntil: 'domcontentloaded' },
    )

    await openAdvancedPlanEditor(page)
    await page.getByTestId('plan-view-toggle-dag').click()
    await page.getByTestId('dag-node-step-1').click()

    const dialog = page.getByTestId('step-inspector')
    await expect(dialog).toBeVisible()

    const requiredField = dialog.getByTestId('step-param-required_field')
    await requiredField.fill('')
    await expect(requiredField).toHaveAttribute('aria-invalid', 'true')
    await expect(dialog.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  test('S5: Pipeline Configure Cancel/Save closes modal and applies overrides', async ({ page }) => {
    await stubPlannedDagBasics(page)

    await page.goto(
      `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&datasetId=${encodeURIComponent(DATASET_ID)}`,
      { waitUntil: 'domcontentloaded' },
    )

    await openAdvancedPlanEditor(page)
    const configure = page.getByRole('button', { name: 'Configure', exact: true })
    await expect(configure).toBeVisible()

    await configure.click()
    const dialog = page.getByTestId('pipeline-parameters')
    await expect(dialog).toBeVisible()
    await dialog.getByTestId('step-param-atlas_name').fill('power-264')
    await dialog.getByTestId('plan-params-cancel').click()
    await expect(dialog).toBeHidden()
    await expect(page.getByTestId('parameter-overrides-count')).toHaveCount(0)

    await configure.click()
    const dialog2 = page.getByTestId('pipeline-parameters')
    await expect(dialog2).toBeVisible()
    await dialog2.getByTestId('step-param-atlas_name').fill('power-264')
    await dialog2.getByTestId('plan-params-save').click()
    await expect(dialog2).toBeHidden()
    await expect(page.getByTestId('parameter-overrides-count')).toContainText('override')
  })

  test('S6: Intent draft persists before navigating to dataset picker', async ({ page }) => {
    await stubPlannedDagBasics(page)

    await page.goto(
      `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&datasetId=${encodeURIComponent(DATASET_ID)}`,
      { waitUntil: 'domcontentloaded' },
    )

    await openAdvancedPlanEditor(page)

    const intentText = 'Run resting-state connectivity with robust confound checks.'
    await page.getByPlaceholder('Describe the plan goal…').fill(intentText)
    await page.getByRole('button', { name: 'Change', exact: true }).click()

    await page.waitForURL(/\/datasets\?pick=1/, { timeout: 30_000 })

    const savedDraftRaw = await page.evaluate(() => window.localStorage.getItem('br:plan:last'))
    expect(savedDraftRaw).toBeTruthy()
    const savedDraft = JSON.parse(savedDraftRaw || '{}')
    expect(savedDraft.intent).toBe(intentText)
    expect(Boolean(savedDraft.intent_touched)).toBe(true)
  })

  test('S6b: Intent remains after returning from dataset picker', async ({ page }) => {
    await stubPlannedDagBasics(page)

    await page.goto(
      `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&datasetId=${encodeURIComponent(DATASET_ID)}`,
      { waitUntil: 'domcontentloaded' },
    )

    await openAdvancedPlanEditor(page)

    const intentText = 'Intent persistence round-trip check.'
    const intentInput = page.getByPlaceholder('Describe the plan goal…')
    await intentInput.fill(intentText)
    await page.getByRole('button', { name: 'Change', exact: true }).click()
    await page.waitForURL(/\/datasets\?pick=1/, { timeout: 30_000 })

    const current = new URL(page.url())
    const returnTo = current.searchParams.get('returnTo') || '/studio?tab=plan'
    await page.goto(returnTo, { waitUntil: 'domcontentloaded' })

    await openAdvancedPlanEditor(page)
    await expect(page.getByPlaceholder('Describe the plan goal…')).toHaveValue(intentText)
  })

  test('S6c: legacy pickDataset query redirects to canonical dataset picker', async ({ page }) => {
    await stubPlannedDagBasics(page)

    await page.goto(
      `/studio?tab=plan&pipeline=${encodeURIComponent(PIPELINE_ID)}&pickDataset=1`,
      { waitUntil: 'domcontentloaded' },
    )

    await page.waitForURL(/\/datasets\?pick=1/, { timeout: 30_000 })

    const current = new URL(page.url())
    const returnTo = current.searchParams.get('returnTo')
    expect(returnTo).toBeTruthy()
    const target = new URL(returnTo || '/studio', 'http://localhost')
    expect(target.pathname).toBe('/studio')
    expect(target.searchParams.get('pipeline')).toBe(PIPELINE_ID)
    expect(target.searchParams.get('tab')).toBe('plan')
  })

  test('X2-X5: Typed stream events update Console/DAG/Artifacts (smoke)', async ({ page }) => {
    const runId = `e2e_planned_stream_${Date.now()}`
    const now = new Date().toISOString()

    await stubPlannedDagBasics(page)

    await page.route(`**/api/analyses/${runId}`, async (route: any) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ analysis_id: runId, status: 'completed' }),
      })
    })

    await page.route(`**/api/analyses/${runId}/steps`, async (route: any) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ job_id: runId, state: 'queued', steps: [] }),
      })
    })

    await page.route(`**/api/analyses/${runId}/steps/stream**`, async (route: any) => {
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

    const sseEvents = [
      {
        schema_version: 'analysis-stream-event-v1',
        seq: 1,
        timestamp: now,
        event_type: 'log.line',
        payload: { stream: 'stdout', line: 'Hello from tool' },
      },
      {
        schema_version: 'analysis-stream-event-v1',
        seq: 2,
        timestamp: now,
        event_type: 'artifact.written',
        payload: {
          artifact: {
            schema_version: 'artifact-v1',
            kind: 'file',
            uri: 'file://mock/output/matrix.csv',
            media_type: 'text/csv',
          },
        },
      },
      {
        schema_version: 'analysis-stream-event-v1',
        seq: 3,
        timestamp: now,
        event_type: 'new.event.type',
        payload: { note: 'unknown' },
      },
    ]

    const sseBody = sseEvents
      .map((evt) => `event: analysis_stream_event\ndata: ${JSON.stringify(evt)}\n\n`)
      .join('')

    await page.route(`**/api/analyses/${runId}/analysis-stream**`, async (route: any) => {
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

    await page.route(`**/api/analyses/${runId}/observation`, async (route: any) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ run_card: { id: runId, outputs: { text: '' }, artifacts: [] } }),
      })
    })

    await page.goto(`/studio?analysisId=${encodeURIComponent(runId)}&tab=results`, { waitUntil: 'domcontentloaded' })
    const consolePanel = page.getByTestId('console-panel')
    await expect(consolePanel).toBeVisible()
    await consolePanel.getByRole('button', { name: 'Logs', exact: true }).click()
    await expect(page.getByTestId('console-stream-logs')).toContainText('Hello from tool', { timeout: 10_000 })
    await expect(page.getByTestId('console-stream-artifacts')).toContainText('matrix.csv')
    await expect(page.getByTestId('console-stream-unknown')).toBeVisible()
  })

  test('X8: Download logs action exports current buffer', async ({ page }) => {
    const runId = `e2e_planned_download_${Date.now()}`
    const now = new Date().toISOString()

    await stubPlannedDagBasics(page)

    await page.route(`**/api/analyses/${runId}`, async (route: any) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ analysis_id: runId, status: 'completed' }),
      })
    })

    await page.route(`**/api/analyses/${runId}/steps`, async (route: any) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ job_id: runId, state: 'queued', steps: [] }),
      })
    })

    await page.route(`**/api/analyses/${runId}/steps/stream**`, async (route: any) => {
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

    const sseBody = `event: analysis_stream_event\ndata: ${JSON.stringify({
      schema_version: 'analysis-stream-event-v1',
      seq: 1,
      timestamp: now,
      event_type: 'log.line',
      payload: { stream: 'stdout', line: 'download-me' },
    })}\n\n`

    await page.route(`**/api/analyses/${runId}/analysis-stream**`, async (route: any) => {
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

    await page.route(`**/api/analyses/${runId}/observation`, async (route: any) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ run_card: { id: runId, outputs: { text: '' }, artifacts: [] } }),
      })
    })

    await page.goto(`/studio?analysisId=${encodeURIComponent(runId)}&tab=results`, { waitUntil: 'domcontentloaded' })
    const consolePanel = page.getByTestId('console-panel')
    await expect(consolePanel).toBeVisible()

    const downloadPromise = page.waitForEvent('download')
    await consolePanel.getByRole('button', { name: /download/i }).click()
    const download = await downloadPromise
    await expect(download).toBeTruthy()
  })

  test('X9: Artifact preview opens previewer for supported types', async ({ page }) => {
    const runId = `e2e_planned_preview_${Date.now()}`
    await stubPlannedDagBasics(page)

    await page.route(`**/api/analyses/${runId}`, async (route: any) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ analysis_id: runId, status: 'completed' }),
      })
    })

    await page.route(`**/api/analyses/${runId}/observation`, async (route: any) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          run_card: {
            id: runId,
            outputs: { text: '- Processed 1 subject\n- Generated a matrix\n' },
            artifacts: [
              {
                id: 'artifact-1',
                name: 'connectivity_matrix.csv',
                type: 'table',
                url: '/api/share/fake/matrix.csv',
              },
            ],
          },
        }),
      })
    })

    await page.route('**/api/share/fake/matrix.csv', async (route: any) => {
      await route.fulfill({
        status: 200,
        contentType: 'text/csv',
        body: 'a,b\n1,2\n',
      })
    })

    await page.goto(`/studio?analysisId=${encodeURIComponent(runId)}&tab=results`, { waitUntil: 'domcontentloaded' })
    await page.getByRole('button', { name: /preview/i }).first().click()
    await expect(page.getByTestId('artifact-preview-dialog')).toBeVisible()
    await expect(page.getByText('a,b', { exact: false })).toBeVisible()
  })
})
