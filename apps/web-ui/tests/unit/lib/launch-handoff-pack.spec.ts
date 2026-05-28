import { describe, expect, it } from 'vitest'

import { buildPlannerHandoffPack } from '@/lib/launch-handoff-pack'

describe('buildPlannerHandoffPack', () => {
  it('builds the MCP-compatible handoff shape for workflow launches', () => {
    const pack = buildPlannerHandoffPack({
      workflowId: 'workflow_rest_connectome_e2e',
      chosenTool: 'workflow_rest_connectome_e2e',
      datasetRef: 'ds:openneuro:ds000114',
      inputs: {
        dataset_id: 'ds:openneuro:ds000114',
        api_key: 'secret',
      },
      requiredTools: [
        'workflow_rest_connectome_e2e',
        'fetch_atlas',
        'extract_timeseries',
        'compute_connectivity',
      ],
      supportedRecipeTargets: ['python'],
      preflightStatus: 'passed',
    })

    expect(pack.schema_version).toBe('br-plan-handoff-v1')
    expect(pack.workflow_id).toBe('workflow_rest_connectome_e2e')
    expect(pack.chosen_tool).toBe('workflow_rest_connectome_e2e')
    expect(pack.dataset_ref).toBe('ds:openneuro:ds000114')
    expect(pack.run_mode_hint).toBe('recipe_required')
    expect(pack.inputs.api_key).toBe('[redacted]')
    expect(pack.execution).toEqual(
      expect.objectContaining({
        kind: 'brain_researcher_orchestrator',
        submit_route: '/run',
        preflight_route: '/api/preflight/check',
        workflow_id: 'workflow_rest_connectome_e2e',
        target_runtime: 'python',
        preflight_status: 'passed',
      }),
    )
    expect(pack.recipe_lookup).toEqual(
      expect.objectContaining({
        tool_name: 'get_execution_recipe',
        tool_id: 'workflow_rest_connectome_e2e',
        params: expect.objectContaining({
          api_key: '[redacted]',
        }),
      }),
    )
  })
})
