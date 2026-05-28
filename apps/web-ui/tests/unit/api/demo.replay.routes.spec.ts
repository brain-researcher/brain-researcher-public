import fs from 'fs'
import os from 'os'
import path from 'path'

import { NextRequest } from 'next/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { buildAnalysisDetail } from '@/lib/server/analysis-detail'
import { ensureDemoRunExists } from '@/lib/server/demo-seed'
import { issueInternalJwt } from '@/lib/server/internal-jwt'
import { isRequestAuthenticated } from '@/lib/server/request-auth'

vi.mock('@/lib/server/analysis-detail', () => ({
  buildAnalysisDetail: vi.fn(),
}))

vi.mock('@/lib/server/request-auth', () => ({
  isRequestAuthenticated: vi.fn(),
}))

vi.mock('@/lib/server/internal-jwt', () => ({
  issueInternalJwt: vi.fn(),
}))

vi.mock('@/lib/server/demo-seed', () => ({
  ensureDemoRunExists: vi.fn(),
}))

vi.mock('@/lib/server/downstream', () => ({
  forwardAuthHeaders: () => new Headers({ authorization: 'Bearer user-token' }),
}))

function writeFile(filePath: string, content: string) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true })
  fs.writeFileSync(filePath, content, 'utf-8')
}

function writeJson(filePath: string, value: unknown) {
  writeFile(filePath, JSON.stringify(value, null, 2))
}

function createRequest(url: string) {
  return new NextRequest(new URL(url))
}

describe('API Routes: demo replay', () => {
  const authMock = vi.mocked(isRequestAuthenticated)
  const issueJwtMock = vi.mocked(issueInternalJwt)
  const buildDetailMock = vi.mocked(buildAnalysisDetail)
  const ensureDemoRunExistsMock = vi.mocked(ensureDemoRunExists)

  let tmpRoot = ''
  let demoIndexPath = ''
  let bundleRoot = ''
  let manuscriptMapPath = ''
  let artifactPath = ''
  let casePath = ''
  let runbookPath = ''

  beforeEach(() => {
    vi.resetModules()
    vi.clearAllMocks()

    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'br-demo-replay-'))
    demoIndexPath = path.join(tmpRoot, 'demo_index.json')
    bundleRoot = path.join(tmpRoot, 'demo_runs')
    manuscriptMapPath = path.join(tmpRoot, 'manuscript_map.yaml')

    casePath = path.join(tmpRoot, 'synthetic_robustness_replay_case.md')
    runbookPath = path.join(tmpRoot, 'synthetic_robustness_replay_runbook.md')
    artifactPath = path.join(tmpRoot, 'r2_robustness_minimal.yaml')

    writeFile(
      casePath,
      [
        '# CASE 8 Template',
        '',
        '## Step 0: User Query (Raw)',
        '',
        '```text',
        '"Run a multiverse GLM audit and show which conclusions are stable vs fragile."',
        '```',
        '',
      ].join('\n'),
    )

    writeFile(
      runbookPath,
      [
        '# Runbook',
        '',
        '## Coding Agent Track (What You Type to Codex/Agent)',
        '',
        '```text',
        'Compare two robustness artifacts and summarize stable vs fragile claims.',
        '```',
        '',
      ].join('\n'),
    )

    writeFile(
      artifactPath,
      [
        'r2_output:',
        '  dominant_driver_discovered:',
        '    axis: "hrf_family"',
        '    contribution: 0.38',
        '  default_pipeline_risk:',
        '    risk_statement: "Canonical HRF assumptions can change conclusions in higher-order networks."',
        '',
      ].join('\n'),
    )

    writeJson(demoIndexPath, {
      demos: [
        {
          slug: 'synthetic-robustness-replay',
          analysis_id: 'run_synthetic_robustness_replay',
          title: 'Synthetic Robustness Replay',
          stage_tags: ['R2', 'R4'],
          prerequisites: ['HCP Emotion dataset mounted locally'],
          primary_prompt: 'Run a curated robustness replay and summarize stability decisions.',
          coding_prompt: 'Summarize robust vs fragile outputs from artifacts.',
          mcp_prompt: 'Use BR-KG/MCP only and return provenance IDs for each claim.',
          source_run_ids: ['run_source_001'],
        },
      ],
    })

    writeJson(path.join(bundleRoot, 'synthetic-robustness-replay', 'run_bundle.json'), {
      schema_version: 'demo-run-bundle-v2',
      generated_at: '2026-02-23T00:00:00Z',
      source_run_ids: ['run_source_001'],
      artifact_count: 3,
      artifacts: [
        {
          id: 'a001',
          path: casePath,
          mime_type: 'text/markdown; charset=utf-8',
          roles: ['prompt_source'],
          stage: 'R0',
        },
        {
          id: 'a002',
          path: runbookPath,
          mime_type: 'text/markdown; charset=utf-8',
          roles: ['runbook'],
          stage: 'R5',
        },
        {
          id: 'a003',
          path: artifactPath,
          mime_type: 'application/yaml',
          roles: ['evidence', 'reference_summary_source'],
          stage: 'R2',
        },
      ],
      prompt_pack: {
        primary_prompt: 'Bundle prompt: run robustness replay.',
        source_artifact_id: 'a001',
        followup_prompts: ['Bundle follow-up prompt'],
        coding_agent_prompts: ['Bundle coding prompt'],
        mcp_prompts: ['Bundle MCP prompt'],
      },
      reference_output: {
        summary: 'Dominant driver: hrf_family (0.38)',
        summary_kind: 'answer',
        source_artifact_id: 'a003',
        document_ids: ['a003'],
        highlights: ['Dominant driver: hrf_family (0.38)'],
        generated_at: '2026-02-23T00:00:00Z',
      },
      replay: {
        source: 'bundle_steps',
        steps: [
          {
            step_id: 'stage_r2_1',
            stage: 'R2',
            title: 'Robustness audit',
            status: 'completed',
            prompt_text: 'Audit robustness across preprocessing choices.',
            response_text: 'Dominant driver is HRF family.',
            artifact_ref_ids: ['a003'],
          },
          {
            step_id: 'stage_r4_2',
            stage: 'R4',
            title: 'Conclusions',
            status: 'completed',
            response_text: 'Report stable and fragile findings separately.',
            artifact_ref_ids: ['a003'],
          },
        ],
      },
      fallback: {
        level: 'none',
        reasons: [],
      },
    })

    writeFile(
      manuscriptMapPath,
      [
        'version: 1',
        'figures:',
        '  Fig4:',
        '    title: "UC2 Robustness"',
        '    demos:',
        '      - slug: "synthetic-robustness-replay"',
        '        primary_artifacts:',
        `          - "${casePath}"`,
        `          - "${runbookPath}"`,
        '',
      ].join('\n'),
    )

    process.env.BR_DEMO_INDEX_PATH = demoIndexPath
    process.env.BR_DEMO_RUN_BUNDLE_ROOT = bundleRoot
    process.env.BR_MANUSCRIPT_MAP_PATH = manuscriptMapPath

    authMock.mockResolvedValue(false)
    issueJwtMock.mockReturnValue('demo-token')
    ensureDemoRunExistsMock.mockResolvedValue(false)
    buildDetailMock.mockResolvedValue({
      ok: false,
      status: 404,
      body: { detail: 'Run not found.' },
    } as any)
  })

  afterEach(() => {
    delete process.env.BR_DEMO_INDEX_PATH
    delete process.env.BR_DEMO_RUN_BUNDLE_ROOT
    delete process.env.BR_MANUSCRIPT_MAP_PATH
    if (tmpRoot && fs.existsSync(tmpRoot)) {
      fs.rmSync(tmpRoot, { recursive: true, force: true })
    }
    vi.resetAllMocks()
  })

  it('builds prompt-first replay payload with fallback analysis and bundle evidence', async () => {
    const { GET } = await import('@/app/api/demo/replay/[demoId]/route')
    const res = await GET(
      createRequest('http://test/api/demo/replay/synthetic-robustness-replay'),
      {
        params: { demoId: 'synthetic-robustness-replay' },
      },
    )

    expect(res.status).toBe(200)
    const payload = await res.json()

    expect(payload.demo.slug).toBe('synthetic-robustness-replay')
    expect(payload.prompt.primary_prompt).toContain('curated robustness replay')
    expect(payload.replay.steps.length).toBeGreaterThan(0)
    expect(payload.replay.steps[0].narrative_title).toContain('R2')
    expect(typeof payload.replay.steps[0].narrative_order).toBe('number')
    expect(payload.replay.source).toBe('bundle_steps')
    expect(payload.presentation.mode).toBe('curated')
    expect(payload.presentation.disclaimer.length).toBeGreaterThan(0)
    expect(payload.presentation.overview).toContain('Replay includes')
    expect(payload.reference_output.summary).toContain('Dominant driver')
    expect(payload.reference_output.generated_at).toBe('2026-02-23T00:00:00Z')
    expect(payload.reference_output.dataset_version).toBeNull()
    expect(payload.reference_output.documents.length).toBeGreaterThan(0)
    expect(payload.reference_output.documents[0].id).toBe('a003')
    expect(payload.reference_output.documents[0].path).toBe(artifactPath)
    expect(payload.reference_output.documents[0].content).toContain(
      'dominant_driver_discovered',
    )
    expect(payload.bundle.items).toHaveLength(3)
    expect(payload.bundle.items.find((item: any) => item.id === 'a003')?.preview).toContain(
      'dominant_driver_discovered',
    )
    expect(payload.notes.join('\n')).toContain('Evidence provenance:')
    expect(payload.reproduce.requirements).toContain('HCP Emotion dataset mounted locally')
    expect(payload.reproduce.snippets.length).toBeGreaterThan(0)
    expect(payload.reproduce.snippets[0].snippet_id).toBe('prerequisites')
    expect(payload.prompt.coding_agent_prompts[0]).toContain('robust vs fragile')
    expect(payload.prompt.mcp_prompts[0]).toContain('Use BR-KG/MCP only')
    expect(payload.prompt.source_path).toBe(casePath)
    expect(payload.reproduce.snippets.map((s: any) => s.snippet_id)).toContain('mcp_prompt')
    expect(payload.reproduce.commands.join('\n')).toContain('run_get(run_id=run_source_001)')
  })

  it('treats PDF-only manuscript case reports as curated bundle replays', async () => {
    const reportPath = path.join(tmpRoot, 'case1_report.pdf')
    writeFile(reportPath, '%PDF-1.7\n')

    const index = JSON.parse(fs.readFileSync(demoIndexPath, 'utf-8'))
    index.demos.push({
      slug: 'case1-report',
      analysis_id: 'run_case1_report',
      title: 'Case 1 Report',
      description: 'Curated PDF case report.',
      primary_prompt: 'Review the curated PDF report.',
      demo_type: 'manuscript_case_report',
      evidence_mode: 'real',
      log_mode: 'summary_only',
      source_run_ids: [],
      is_template: false,
    })
    writeJson(demoIndexPath, index)

    writeJson(path.join(bundleRoot, 'case1-report', 'run_bundle.json'), {
      schema_version: 'demo-run-bundle-v2',
      generated_at: '2026-05-26T00:00:00Z',
      source_run_ids: [],
      artifact_count: 1,
      artifacts: [
        {
          id: 'a001',
          path: reportPath,
          mime_type: 'application/pdf',
          roles: ['reference_summary_source', 'evidence'],
          stage: 'R5',
          title: 'Case 1 PDF Report',
        },
      ],
      prompt_pack: {
        primary_prompt: 'Review the curated PDF report.',
        followup_prompts: [],
        coding_agent_prompts: [],
        mcp_prompts: [],
      },
      reference_output: {
        summary: 'Curated PDF case report.',
        summary_kind: 'answer',
        source_artifact_id: 'a001',
        document_ids: [],
        highlights: ['Case 1 PDF Report'],
      },
      replay: {
        source: 'bundle_steps',
        steps: [
          {
            step_id: 'stage_R5_1',
            stage: 'R5',
            title: 'Curated PDF Case Report',
            status: 'completed',
            response_text: 'The curated PDF report is available as artifact a001.',
            artifact_ref_ids: ['a001'],
          },
        ],
      },
      fallback: {
        level: 'none',
        reasons: [],
      },
    })

    const { GET } = await import('@/app/api/demo/replay/[demoId]/route')
    const res = await GET(createRequest('http://test/api/demo/replay/case1-report'), {
      params: { demoId: 'case1-report' },
    })

    expect(res.status).toBe(200)
    const payload = await res.json()

    expect(buildDetailMock).not.toHaveBeenCalled()
    expect(ensureDemoRunExistsMock).not.toHaveBeenCalled()
    expect(payload.presentation.mode).toBe('curated')
    expect(payload.presentation.disclaimer).toContain('Curated replay mode')
    expect(payload.analysis.warnings.join('\n')).not.toContain('Live run unavailable')
    expect(payload.analysis.warnings.join('\n')).toContain('Showing curated demo bundle')
    expect(payload.bundle.items[0].mime_type).toBe('application/pdf')
  })
})
