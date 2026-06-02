import { describe, expect, it } from 'vitest'

import { fetchSidebarRuns, type RunSidebarItem } from '../runs'

// normalizeRun is not exported directly; exercise it through fetchSidebarRuns,
// which calls it on every item in the /api/runs payload. We stub fetch to return
// a single raw run shaped like what the orchestrator returns (with the full
// `plan` payload the from-dataset flow writes).
async function normalizeOne(raw: unknown): Promise<RunSidebarItem> {
  const originalFetch = globalThis.fetch
  globalThis.fetch = (async () =>
    new Response(JSON.stringify({ runs: [raw], count: 1 }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })) as typeof fetch
  try {
    const items = await fetchSidebarRuns({ limit: 1 })
    expect(items).toHaveLength(1)
    return items[0]
  } finally {
    globalThis.fetch = originalFetch
  }
}

describe('normalizeRun enrichment', () => {
  it('extracts title/task/dataset_label/workflow_label from the plan payload', async () => {
    const item = await normalizeOne({
      run_id: 'run_1',
      status: 'succeeded',
      plan: {
        intent: 'GLM · Nilearn first-level',
        dataset_id: 'ds000001',
        pipeline: 'glm',
        metadata: { intent: 'GLM · Nilearn first-level' },
        parameters: {
          dataset_label: 'Motor Task',
          dataset_tasks: ['motor'],
          analysis_label: 'GLM',
          pipeline_label: 'Nilearn first-level',
          task_id: 'motor',
        },
      },
    })
    expect(item.title).toBe('GLM · Nilearn first-level')
    expect(item.task).toBe('motor')
    expect(item.dataset_label).toBe('Motor Task')
    expect(item.workflow_label).toBe('Nilearn first-level')
    // Existing fields keep working.
    expect(item.status).toBe('completed') // succeeded -> completed
    expect(item.dataset_id).toBe('ds000001')
  })

  it('falls back to first dataset_tasks entry when task_id is absent', async () => {
    const item = await normalizeOne({
      run_id: 'run_2',
      status: 'running',
      plan: { parameters: { dataset_tasks: ['nback', 'rest'] } },
    })
    expect(item.task).toBe('nback')
  })

  it('leaves enrichment fields null when the plan lacks parameters', async () => {
    const item = await normalizeOne({
      run_id: 'run_3',
      status: 'running',
      workflow_id: 'wf_raw',
      plan: {},
    })
    // No human title -> null (RunsSidebar then falls back to workflow_id).
    expect(item.title).toBeNull()
    expect(item.task).toBeNull()
    expect(item.dataset_label).toBeNull()
    // workflow_label falls back through plan.pipeline/workflowFromPlan, which are
    // absent here, so it stays null too.
    expect(item.workflow_label).toBeNull()
    expect(item.workflow_id).toBe('wf_raw')
  })

  it('keeps source unknown when the backend omits it', async () => {
    const item = await normalizeOne({ run_id: 'run_4', status: 'completed', plan: {} })
    expect(item.source).toBe('unknown')
  })

  it('maps backend source=internal to internal (Studio badge)', async () => {
    const item = await normalizeOne({
      run_id: 'run_internal',
      status: 'completed',
      source: 'internal',
      plan: {},
    })
    expect(item.source).toBe('internal')
  })

  it('maps backend source=external to external (External agent badge)', async () => {
    const item = await normalizeOne({
      run_id: 'run_external',
      status: 'running',
      source: 'external',
      plan: {},
    })
    expect(item.source).toBe('external')
  })

  it('maps raw async-run origin literals to external (defense-in-depth)', async () => {
    const origins = [
      'mcp_pipeline_execute',
      'api_tools_run',
      'tools_run_compat',
      'direct',
    ]
    for (const source of origins) {
      const item = await normalizeOne({
        run_id: `run_${source}`,
        status: 'queued',
        source,
        plan: {},
      })
      expect(item.source).toBe('external')
    }
  })

  it('keeps an unrecognized source value unknown', async () => {
    const item = await normalizeOne({
      run_id: 'run_weird',
      status: 'completed',
      source: 'totally-made-up',
      plan: {},
    })
    expect(item.source).toBe('unknown')
  })
})
