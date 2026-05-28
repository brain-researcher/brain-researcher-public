import { describe, expect, it } from 'vitest'

import {
  ANALYSIS_TYPES,
  STUDIO_RUNTIME_TOOL_IDS,
} from '@/config/analysis-presets'

describe('analysis presets use canonical runtime tools', () => {
  it('keeps every pipeline tool within the canonical runtime tool id set', () => {
    const canonical = new Set(STUDIO_RUNTIME_TOOL_IDS)
    for (const analysis of ANALYSIS_TYPES) {
      for (const pipeline of analysis.pipelines) {
        expect(canonical.has(pipeline.runConfig.tool)).toBe(true)
      }
    }
  })

  it('routes preprocessing presets through run_bids_app with explicit app names', () => {
    const preprocess = ANALYSIS_TYPES.find((analysis) => analysis.id === 'preprocess')
    expect(preprocess).toBeDefined()

    for (const pipeline of preprocess?.pipelines ?? []) {
      expect(pipeline.runConfig.tool).toBe('run_bids_app')
      expect(typeof pipeline.runConfig.defaultParameters?.app).toBe('string')
      expect(String(pipeline.runConfig.defaultParameters?.app).length).toBeGreaterThan(0)
    }
  })

  it('routes nilearn connectivity through workflow_rest_connectome_e2e with workflow-native defaults', () => {
    const connectivity = ANALYSIS_TYPES.find((analysis) => analysis.id === 'connectivity')
    const pipeline = connectivity?.pipelines.find((candidate) => candidate.id === 'nilearn_connectivity')
    expect(pipeline).toBeDefined()
    expect(pipeline?.runConfig.tool).toBe('workflow_rest_connectome_e2e')
    expect(pipeline?.runConfig.defaultParameters?.atlas_name).toBe('Schaefer2018_200')
    expect(pipeline?.runConfig.defaultParameters?.connectivity_kind).toBe('correlation')
  })
})
