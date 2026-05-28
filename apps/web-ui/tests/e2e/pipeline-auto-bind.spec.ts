import { test, expect } from '@playwright/test'

const BASE = process.env.E2E_BASE_URL || process.env.BASE_URL || 'http://localhost:3000'
const ORCH =
  process.env.E2E_ORCH_URL ||
  process.env.ORCHESTRATOR_URL ||
  'http://127.0.0.1:8000'

test.describe('Pipeline page auto-bind', () => {
  test('auto-binds latest job without query params', async ({ page }) => {
    const payload = {
      pipeline_id: 'main-pipeline',
      name: 'Auto-bind e2e run',
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
    const jobId = runJson.job_id || runJson.jobId
    expect(jobId).toBeTruthy()

    await page.goto(`${BASE}/pipeline`, { waitUntil: 'domcontentloaded' })
    await expect(page.getByText(`Last run: ${jobId}`)).toBeVisible({ timeout: 30_000 })

    const wsBanner = page.getByText('WebSocket connection')
    await expect(wsBanner).toHaveCount(0)
  })
})
