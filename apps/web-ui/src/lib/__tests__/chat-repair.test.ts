import {
  applyRepairPlanPatchToDraft,
  buildRepairMessageMetadata,
  extractRepairProposal,
} from '../chat-repair'

describe('chat-repair', () => {
  it('extracts a repair proposal from the first fenced json block', () => {
    const proposal = extractRepairProposal(
      [
        'The confound regressor is missing. Reduce the scope and retry.',
        '```json',
        JSON.stringify(
          {
            plan_patch: {
              parameter_overrides: {
                smoothing_fwhm: 4,
              },
            },
            validation_intent: 'Re-run validation on the reduced smoothing setting.',
            handoff: {
              required: false,
              reason: null,
            },
          },
          null,
          2,
        ),
        '```',
      ].join('\n'),
    )

    expect(proposal).not.toBeNull()
    expect(proposal?.narrative).toContain('Reduce the scope and retry')
    expect(proposal?.planPatch).toEqual({
      parameter_overrides: {
        smoothing_fwhm: 4,
      },
    })
    expect(proposal?.validationIntent).toContain('Re-run validation')
    expect(proposal?.handoff?.required).toBe(false)
  })

  it('returns null when the repair json block is malformed', () => {
    const proposal = extractRepairProposal(
      'Try a smaller subset first.\n```json\n{ plan_patch: invalid }\n```',
    )

    expect(proposal).toBeNull()
  })

  it('merges a repair plan patch into the current Studio draft', () => {
    const nextDraft = applyRepairPlanPatchToDraft(
      JSON.stringify({
        version: 1,
        updated_at: 10,
        dataset_id: 'ds-old',
        dataset_version: '1.0.0',
        pipeline_id: 'glm_old',
        parameter_overrides: {
          smoothing_fwhm: 6,
        },
      }),
      {
        dataset_id: 'ds-new',
        pipeline_id: 'glm_repaired',
        parameter_values: {
          smoothing_fwhm: 4,
          high_pass: 0.01,
        },
      },
      {
        analysisId: 'task_glm',
      },
    )

    expect(nextDraft).toMatchObject({
      version: 1,
      dataset_id: 'ds-new',
      pipeline_id: 'glm_repaired',
      analysis_id: 'task_glm',
      parameter_overrides: {
        smoothing_fwhm: 4,
        high_pass: 0.01,
      },
    })
    expect(typeof nextDraft?.updated_at).toBe('number')
  })

  it('builds compact repair metadata for assistant messages', () => {
    const metadata = buildRepairMessageMetadata({
      run_id: 'run-123',
      analysis_id: 'analysis-123',
      tool_name: 'fitlins',
      error_type: 'workflow_error',
      repair_attempt_count: 2,
      failing_step: {
        id: 'step-3',
        name: 'Model fit',
        tool: 'fitlins',
        status: 'failed',
        error: 'confounds.tsv missing',
      },
    })

    expect(metadata).toEqual({
      repair_request: true,
      repair_context: {
        run_id: 'run-123',
        analysis_id: 'analysis-123',
        tool_name: 'fitlins',
        error_type: 'workflow_error',
        repair_attempt_count: 2,
        failing_step: {
          id: 'step-3',
          name: 'Model fit',
          tool: 'fitlins',
          status: 'failed',
          error: 'confounds.tsv missing',
        },
      },
    })
  })
})
