import { describe, expect, it } from 'vitest'

import {
  buildMcpRecipeCallText,
  normalizeDatasetIdForMcpRecipe,
} from '@/lib/mcp-recipe-handoff'

describe('mcp recipe handoff helpers', () => {
  it('adds known dataset context to get_execution_recipe params', () => {
    expect(
      buildMcpRecipeCallText({
        workflowId: 'workflow_rest_connectome_e2e',
        targetRuntime: 'python',
        datasetId: 'ds000114',
        params: {},
      }),
    ).toContain('params={"dataset_id": "ds000114"}')
  })

  it('normalizes OpenNeuro URN dataset ids for recipe params', () => {
    expect(normalizeDatasetIdForMcpRecipe('ds:openneuro:ds000114')).toBe('ds000114')
    expect(
      buildMcpRecipeCallText({
        workflowId: 'workflow_rest_connectome_e2e',
        targetRuntime: 'python',
        datasetId: 'ds:openneuro:ds000114',
        params: {},
      }),
    ).toContain('params={"dataset_id": "ds000114"}')
  })
})
