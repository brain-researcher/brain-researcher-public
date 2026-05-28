import type { DemoIndexEntry } from '@/lib/server/demo-index'
import { resolveOrchestratorBaseUrl } from '@/lib/server/downstream'
import { issueInternalJwt } from '@/lib/server/internal-jwt'

export async function ensureDemoRunExists(demo: DemoIndexEntry): Promise<boolean> {
  if (demo.demo_type === 'manuscript_case_report') return false

  const analysisId = typeof demo.analysis_id === 'string' ? demo.analysis_id.trim() : ''
  if (!analysisId) return false

  const token = issueInternalJwt({
    subject: 'demo-seed',
    email: 'demo-seed@local',
    name: 'demo-seed',
    role: 'demo',
    provider: 'demo-seed',
    ttlSeconds: 10 * 60,
  })
  if (!token) return false

  const headers = {
    authorization: `Bearer ${token}`,
    'content-type': 'application/json',
  }

  try {
    const orchestratorBase = resolveOrchestratorBaseUrl()
    const exists = await fetch(`${orchestratorBase}/api/jobs/${encodeURIComponent(analysisId)}`, {
      method: 'GET',
      headers,
      cache: 'no-store',
    })
    if (exists.ok) return true
    if (exists.status !== 404) return false

    const createRes = await fetch(`${orchestratorBase}/run`, {
      method: 'POST',
      headers,
      cache: 'no-store',
      body: JSON.stringify({
        prompt: demo.primary_prompt || demo.title || analysisId,
        pipeline: 'demo',
        scenario_id: demo.slug,
        requested_job_id: analysisId,
        thread_id: `demo_${demo.slug}`,
        parameters: {
          demo: true,
          demo_seed: true,
          demo_id: demo.slug,
          intent: demo.title,
          manuscript_figure: demo.manuscript_figure || null,
          evidence_mode: demo.evidence_mode || 'hybrid',
          log_mode: demo.log_mode || 'redacted_full_trace',
          stage_tags: demo.stage_tags || [],
          source_run_ids: demo.source_run_ids || [],
          demo_type: demo.demo_type || 'research_demo',
          is_template: Boolean(demo.is_template),
          canonical_name: demo.canonical_name || null,
          template_reason: demo.template_reason || null,
        },
      }),
    })

    return createRes.ok
  } catch {
    return false
  }
}

export async function ensureDemoRunsExist(demos: DemoIndexEntry[]): Promise<void> {
  for (const demo of demos) {
    // Best-effort background seeding; failures are intentionally ignored.
    await ensureDemoRunExists(demo).catch(() => false)
  }
}
