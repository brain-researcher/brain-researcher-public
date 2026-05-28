import { describe, expect, it } from 'vitest'

import type { WorkflowDetail, WorkflowParameterContract } from '@/lib/api/workflows'
import { resolveWorkflowParamContract } from '@/lib/server/workflow-params'

function createWorkflow(
  stepParams: Record<string, unknown>[],
  params?: WorkflowParameterContract,
): WorkflowDetail {
  return {
    id: 'wf_contract_test',
    stage: 'glm',
    cost_tier: 'cheap',
    description: 'workflow contract test',
    modalities: [],
    impl: 'unit-test',
    runtime: {
      kind: 'pipeline',
      steps: stepParams.map((step, idx) => ({
        id: `step_${idx + 1}`,
        tool: `tool_${idx + 1}`,
        params: step,
      })),
    },
    params,
  }
}

describe('workflow params contract inference', () => {
  it('parses ${inputs.key} and ${inputs.key:-default} placeholders', () => {
    const workflow = createWorkflow([
      {
        dataset_id: '${inputs.dataset_id}',
        n_perm: '${inputs.n_perm:-1000}',
        output_dir: '/tmp/${inputs.output_dir:-results}',
        nested: ['x', '${inputs.dry_run:-false}'],
      },
    ])

    const contract = resolveWorkflowParamContract(workflow)

    expect(contract.discoveredInputKeys).toEqual(['dataset_id', 'dry_run', 'n_perm', 'output_dir'])
    expect(contract.defaultsBySource.placeholder_inferred_defaults).toEqual({
      n_perm: 1000,
      output_dir: 'results',
      dry_run: false,
    })
    expect(contract.defaultsBySource.merged).toMatchObject({
      n_perm: 1000,
      output_dir: 'results',
      dry_run: false,
    })
  })

  it('does not require fields missing from explicit schema when inferred default exists', () => {
    const workflow = createWorkflow(
      [
        {
          dataset: '${inputs.dataset}',
          n_perm: '${inputs.n_perm:-500}',
        },
      ],
      {
        schema: {
          type: 'object',
          required: ['dataset', 'n_perm'],
          properties: {
            dataset: { type: 'string' },
          },
        },
      },
    )

    const contract = resolveWorkflowParamContract(workflow)

    expect(contract.missingContractFields).toEqual(['n_perm'])
    expect(contract.required).toEqual(['dataset'])
    expect(contract.required).not.toContain('n_perm')
  })

  it('adds heuristic defaults for common workflow keys', () => {
    const workflow = createWorkflow([
      {
        output_dir: '${inputs.output_dir}',
        n_perm: '${inputs.n_perm}',
        n_permutations: '${inputs.n_permutations}',
        n_splits: '${inputs.n_splits}',
        radius: '${inputs.radius}',
        smoothing_fwhm: '${inputs.smoothing_fwhm}',
        standardize: '${inputs.standardize}',
        detrend: '${inputs.detrend}',
        low_pass: '${inputs.low_pass}',
        high_pass: '${inputs.high_pass}',
        t_r: '${inputs.t_r}',
        cv_type: '${inputs.cv_type}',
        task_type: '${inputs.task_type}',
        container_type: '${inputs.container_type}',
        dry_run: '${inputs.dry_run}',
      },
    ])

    const contract = resolveWorkflowParamContract(workflow)

    expect(contract.defaultsBySource.heuristic_inferred_defaults).toMatchObject({
      output_dir: '/tmp/brain-researcher/wf_contract_test',
      n_perm: 1000,
      n_permutations: 1000,
      n_splits: 5,
      radius: 6,
      smoothing_fwhm: 6,
      standardize: true,
      detrend: true,
      low_pass: 0.1,
      high_pass: 0.01,
      t_r: 2,
      cv_type: 'kfold',
      task_type: 'classification',
      container_type: 'docker',
      dry_run: false,
    })
    expect(contract.required).toEqual([])
    expect(contract.schema.properties?.output_dir?.type).toBe('string')
    expect(contract.schema.properties?.n_splits?.type).toBe('integer')
    expect(contract.schema.properties?.low_pass?.type).toBe('number')
    expect(contract.schema.properties?.dry_run?.type).toBe('boolean')
  })

  it('infers missing-field types from inferred defaults including arrays', () => {
    const workflow = createWorkflow([
      {
        labels: '${inputs.labels:-["A","B"]}',
        standardize: '${inputs.standardize:-false}',
        n_perm: '${inputs.n_perm:-1000}',
        smoothing_fwhm: '${inputs.smoothing_fwhm:-6.5}',
        model_name: '${inputs.model_name:-ridge}',
      },
    ])

    const contract = resolveWorkflowParamContract(workflow)
    const properties = contract.schema.properties ?? {}

    expect(contract.defaultsBySource.placeholder_inferred_defaults).toMatchObject({
      labels: ['A', 'B'],
      standardize: false,
      n_perm: 1000,
      smoothing_fwhm: 6.5,
      model_name: 'ridge',
    })
    expect(properties.labels?.type).toBe('array')
    expect(properties.standardize?.type).toBe('boolean')
    expect(properties.n_perm?.type).toBe('integer')
    expect(properties.smoothing_fwhm?.type).toBe('number')
    expect(properties.model_name?.type).toBe('string')
  })

  it('preserves explicit schema defaults and types over inferred defaults', () => {
    const workflow = createWorkflow(
      [
        {
          container_type: '${inputs.container_type:-docker}',
          radius: '${inputs.radius:-6.5}',
        },
      ],
      {
        schema: {
          type: 'object',
          properties: {
            container_type: { type: 'string', default: 'singularity' },
            radius: { type: 'string' },
          },
        },
      },
    )

    const contract = resolveWorkflowParamContract(workflow)

    expect(contract.schema.properties?.container_type?.type).toBe('string')
    expect(contract.schema.properties?.radius?.type).toBe('string')
    expect(contract.defaultsBySource.placeholder_inferred_defaults).toMatchObject({
      container_type: 'docker',
      radius: '6.5',
    })
    expect(contract.defaultsBySource.schema_property_defaults).toMatchObject({
      container_type: 'singularity',
    })
    expect(contract.defaultsBySource.merged.container_type).toBe('singularity')
  })
})
