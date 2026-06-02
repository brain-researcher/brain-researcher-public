import fs from 'fs'
import os from 'os'
import path from 'path'

import { NextRequest } from 'next/server'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/server/internal-jwt', () => ({
  issueInternalJwt: () => null,
}))

function createRequest(url: string) {
  return new NextRequest(new URL(url))
}

function writeJson(filePath: string, value: unknown) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true })
  fs.writeFileSync(filePath, JSON.stringify(value, null, 2), 'utf-8')
}

describe('API Routes: demo bundles', () => {
  let tmpRoot = ''
  let demoIndexPath = ''
  let bundleRoot = ''

  beforeEach(() => {
    vi.resetModules()
    tmpRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'br-demo-bundles-'))
    demoIndexPath = path.join(tmpRoot, 'demo_index.json')
    bundleRoot = path.join(tmpRoot, 'demo_runs')

    const artifactPath = path.join(tmpRoot, 'artifact', 'trace.yaml')
    fs.mkdirSync(path.dirname(artifactPath), { recursive: true })
    fs.writeFileSync(artifactPath, 'stage: R1\nstatus: ok\n', 'utf-8')

    writeJson(demoIndexPath, {
      demos: [
        {
          slug: 'demo-one',
          analysis_id: 'run_demo_one',
          title: 'Demo One',
          source_run_ids: ['run_demo_one_source'],
        },
      ],
    })
    writeJson(path.join(bundleRoot, 'demo-one', 'run_bundle.json'), {
      schema_version: 'demo-run-bundle-v2',
      generated_at: '2026-02-23T00:00:00Z',
      source_run_ids: ['run_demo_one_source'],
      artifact_count: 1,
      artifacts: [
        {
          id: 'a001',
          path: artifactPath,
          mime_type: 'application/yaml',
          roles: ['evidence'],
          stage: 'R1',
        },
      ],
      prompt_pack: {
        primary_prompt: 'Prompt source text',
      },
      reference_output: {
        summary: 'Reference summary',
        summary_kind: 'answer',
        document_ids: ['a001'],
      },
      replay: {
        source: 'bundle_steps',
        steps: [],
      },
      fallback: {
        level: 'none',
        reasons: [],
      },
    })

    process.env.BR_DEMO_INDEX_PATH = demoIndexPath
    process.env.BR_DEMO_RUN_BUNDLE_ROOT = bundleRoot
  })

  afterEach(() => {
    delete process.env.BR_DEMO_INDEX_PATH
    delete process.env.BR_DEMO_RUN_BUNDLE_ROOT
    if (tmpRoot && fs.existsSync(tmpRoot)) {
      fs.rmSync(tmpRoot, { recursive: true, force: true })
    }
    vi.resetAllMocks()
  })

  it('GET /api/demo/index merges bundle summary fields', async () => {
    const { GET } = await import('@/app/api/demo/index/route')
    const res = await GET(createRequest('http://test/api/demo/index'))
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.demos).toHaveLength(1)
    expect(body.demos[0].bundle_available).toBe(true)
    expect(body.demos[0].bundle_artifact_count).toBe(1)
  })

  it('GET /api/demo/bundles/:demoId returns artifact items', async () => {
    const { GET } = await import('@/app/api/demo/bundles/[demoId]/route')
    const res = await GET(createRequest('http://test/api/demo/bundles/demo-one'), {
      params: { demoId: 'demo-one' },
    })
    expect(res.status).toBe(200)
    const body = await res.json()
    expect(body.available).toBe(true)
    expect(body.items).toHaveLength(1)
    expect(body.items[0].id).toBe('a001')
    expect(body.items[0].stage).toBe('R1')
    expect(body.items[0].roles).toContain('evidence')
    expect(body.items[0].download_url).toContain('/api/demo/bundles/demo-one/artifact?path=')
  })

  it('GET /api/demo/bundles/:demoId/artifact serves whitelisted artifact file', async () => {
    const { GET } = await import('@/app/api/demo/bundles/[demoId]/artifact/route')
    const res = await GET(
      createRequest('http://test/api/demo/bundles/demo-one/artifact?path=trace.yaml'),
      {
        params: { demoId: 'demo-one' },
      },
    )
    expect(res.status).toBe(200)
    expect(res.headers.get('content-disposition')).toBe('inline; filename="trace.yaml"')
    const text = await res.text()
    expect(text).toContain('stage: R1')
  })

  it('GET /api/demo/bundles/:demoId/artifact supports attachment downloads', async () => {
    const { GET } = await import('@/app/api/demo/bundles/[demoId]/artifact/route')
    const res = await GET(
      createRequest('http://test/api/demo/bundles/demo-one/artifact?path=trace.yaml&download=1'),
      {
        params: { demoId: 'demo-one' },
      },
    )
    expect(res.status).toBe(200)
    expect(res.headers.get('content-disposition')).toBe('attachment; filename="trace.yaml"')
  })
})
