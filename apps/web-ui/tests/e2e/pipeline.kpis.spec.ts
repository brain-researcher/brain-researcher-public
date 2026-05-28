import { test, expect } from '@playwright/test'

const BASE = process.env.E2E_BASE_URL || process.env.BASE_URL || 'http://localhost:3000'
const ORCH =
  process.env.E2E_ORCH_URL ||
  process.env.BR_ORCHESTRATOR_URL ||
  process.env.ORCHESTRATOR_BASE_URL ||
  process.env.ORCHESTRATOR_URL ||
  'http://localhost:3001'

test.describe('Pipeline KPI cards', () => {
  test('renders step counts from pipeline status', async ({ page }) => {
    const payload = {
      pipeline_id: 'kpi-e2e-pipeline',
      name: 'KPI e2e run',
      description: 'Triggered by Playwright',
      nodes: [
        { id: '1', label: 'Data Ingestion', type: 'input', metadata: {} },
        { id: '2', label: 'Preprocessing', type: 'process', metadata: {} },
        { id: '3', label: 'Analysis', type: 'analysis', metadata: {} }
      ],
      edges: [
        { id: '1-2', source: '1', target: '2' },
        { id: '2-3', source: '2', target: '3' }
      ]
    }

    const runResp = await page.request.post(`${ORCH}/orchestrator/pipeline/execute`, {
      data: payload
    })
    expect(runResp.ok()).toBeTruthy()
    const runJson = await runResp.json()
    const rawJobId = runJson.job_id || runJson.jobId
    expect(rawJobId).toBeTruthy()
    const jobId = String(rawJobId).startsWith('job_') ? String(rawJobId) : `job_${rawJobId}`

    await page.goto(`${BASE}/pipeline?job_id=${encodeURIComponent(jobId)}`, {
      waitUntil: 'domcontentloaded'
    })

    const total = page.getByTestId('pipeline-kpi-total')
    const running = page.getByTestId('pipeline-kpi-running')
    const completed = page.getByTestId('pipeline-kpi-completed')
    const failed = page.getByTestId('pipeline-kpi-failed')
    const queued = page.getByTestId('pipeline-kpi-queued')

    await expect(total).toHaveText(/^\d+$/, { timeout: 30_000 })
    await expect(running).toHaveText(/^\d+$/)
    await expect(completed).toHaveText(/^\d+$/)
    await expect(failed).toHaveText(/^\d+$/)
    await expect(queued).toHaveText(/^\d+$/)

    const values = await Promise.all(
      [total, running, completed, failed, queued].map(async (locator) =>
        Number.parseInt((await locator.innerText()).trim(), 10)
      )
    )
    const [totalCount, runningCount, completedCount, failedCount, queuedCount] = values

    expect(totalCount).toBe(3)
    expect(runningCount + completedCount + failedCount + queuedCount).toBe(totalCount)
  })
})
