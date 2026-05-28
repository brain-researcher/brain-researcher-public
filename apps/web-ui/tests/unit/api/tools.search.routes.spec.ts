import fs from 'fs'
import os from 'os'
import path from 'path'

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { NextRequest } from 'next/server'

const createRequest = (url: string) => new NextRequest(new URL(url))

describe('Tools search route', () => {
  let projectRoot: string

  beforeEach(() => {
    vi.resetModules()
    projectRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'br-tools-search-'))
    fs.mkdirSync(path.join(projectRoot, 'configs', 'grandmaster'), { recursive: true })
    fs.mkdirSync(path.join(projectRoot, 'configs', 'catalog'), { recursive: true })

    fs.writeFileSync(
      path.join(projectRoot, 'configs', 'grandmaster', 'toolset_vfinal.yaml'),
      'version: vFinal\natomic_tools: []\n',
      'utf-8',
    )
    fs.writeFileSync(
      path.join(projectRoot, 'configs', 'tools_catalog_merged.json'),
      JSON.stringify({ tools: [] }),
      'utf-8',
    )
    fs.writeFileSync(
      path.join(projectRoot, 'configs', 'catalog', 'capabilities.yaml'),
      `
tools:
  - id: ibl_sorter
    name: IBL Kilosort
    description: Mounted IBL Kilosort runner
    package: ibl
    domain: advanced
    runtime_kind: python
    modality: [multimodal]
    intents: [spike_sorting]
    capabilities: [spike_sorting, ephys_qc]
    consumes: [file_path]
    produces: [spike_times, qc_report]
    tags: [ibl, neuropixels, kilosort]
    python:
      module: brain_researcher.services.tools.ibl_tools
      function: IBLKilosortTool
      entry_type: class
`,
      'utf-8',
    )
    process.env.PROJECT_ROOT = projectRoot
  })

  afterEach(() => {
    delete process.env.PROJECT_ROOT
    fs.rmSync(projectRoot, { recursive: true, force: true })
  })

  it('includes capabilities.yaml tools in search results', async () => {
    const { GET } = await import('@/app/api/tools/search/route')
    const res = await GET(createRequest('http://test/api/tools/search'))
    expect(res.status).toBe(200)

    const data = await res.json()
    expect(data.tools).toEqual(
      expect.arrayContaining([
        expect.objectContaining({
          name: 'ibl_sorter',
          source: 'capabilities',
          module: 'brain_researcher.services.tools.ibl_tools',
        }),
      ]),
    )
  })

  it('matches search queries against capabilities metadata', async () => {
    const { GET } = await import('@/app/api/tools/search/route')
    const res = await GET(createRequest('http://test/api/tools/search?q=neuropixels%20kilosort'))
    expect(res.status).toBe(200)

    const data = await res.json()
    expect(data.tools).toHaveLength(1)
    expect(data.tools[0].name).toBe('ibl_sorter')
  })
})
