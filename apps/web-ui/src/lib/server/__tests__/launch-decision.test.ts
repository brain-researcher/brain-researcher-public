import { describe, expect, it } from 'vitest'

import { deriveLaunchDecision } from '../launch-decision'

describe('deriveLaunchDecision', () => {
  it('keeps manual/admin workflow status ahead of blocked checks', () => {
    const decision = deriveLaunchDecision({
      recipeLaunchStatus: 'manual_admin_only',
      checks: [
        {
          id: 'authenticated',
          status: 'blocked',
          detail: 'Sign in to verify this run.',
        },
      ],
    })

    expect(decision).toEqual(
      expect.objectContaining({
        status: 'manual_admin_only',
        code: 'manual_admin_only',
        can_launch: false,
        primary_action: 'handoff',
      }),
    )
  })

  it('routes auth blocks to sign-in when the workflow is otherwise launchable', () => {
    const decision = deriveLaunchDecision({
      recipeLaunchStatus: 'launchable',
      checks: [
        {
          id: 'authenticated',
          status: 'blocked',
          detail: 'Sign in to continue.',
        },
      ],
    })

    expect(decision).toEqual(
      expect.objectContaining({
        status: 'blocked',
        code: 'blocked_auth',
        can_launch: false,
        primary_action: 'sign_in',
      }),
    )
  })

  it('routes credit blocks to grant-credits when no workflow handoff status applies', () => {
    const decision = deriveLaunchDecision({
      checks: [
        {
          id: 'credits_sufficient',
          status: 'blocked',
          detail: 'Credit estimate unavailable.',
        },
      ],
    })

    expect(decision).toEqual(
      expect.objectContaining({
        status: 'blocked',
        code: 'blocked_credit',
        can_launch: false,
        primary_action: 'grant_credits',
      }),
    )
  })

  it('routes credit blocks to handoff when an MCP recipe is available', () => {
    const decision = deriveLaunchDecision({
      recipeLaunchStatus: 'launchable',
      mcpRecipeAvailable: true,
      checks: [
        {
          id: 'credits_sufficient',
          status: 'blocked',
          detail: 'Need 1 credits; available 0.',
        },
      ],
    })

    expect(decision).toEqual(
      expect.objectContaining({
        status: 'blocked',
        code: 'blocked_credit',
        can_launch: false,
        primary_action: 'handoff',
      }),
    )
    expect(decision.reason).toContain('Hosted launch blocked; MCP recipe available.')
  })

  it('keeps auth blocks on sign-in even when an MCP recipe is available', () => {
    const decision = deriveLaunchDecision({
      recipeLaunchStatus: 'launchable',
      mcpRecipeAvailable: true,
      checks: [
        {
          id: 'authenticated',
          status: 'blocked',
          detail: 'Sign in to continue.',
        },
      ],
    })

    expect(decision).toEqual(
      expect.objectContaining({
        status: 'blocked',
        code: 'blocked_auth',
        can_launch: false,
        primary_action: 'sign_in',
      }),
    )
  })

  it('routes runtime and data readiness blocks to handoff when an MCP recipe is available', () => {
    const runtimeDecision = deriveLaunchDecision({
      recipeLaunchStatus: 'launchable',
      mcpRecipeAvailable: true,
      checks: [
        {
          id: 'runtime_executable',
          status: 'blocked',
          detail: 'Blocked by allowlist: run_bids_app',
        },
      ],
    })
    const dataDecision = deriveLaunchDecision({
      recipeLaunchStatus: 'launchable',
      mcpRecipeAvailable: true,
      checks: [
        {
          id: 'resource_readiness',
          status: 'blocked',
          detail: 'Backend readiness checks timed out.',
        },
      ],
    })

    expect(runtimeDecision).toEqual(
      expect.objectContaining({
        code: 'blocked_missing_runtime',
        primary_action: 'handoff',
      }),
    )
    expect(dataDecision).toEqual(
      expect.objectContaining({
        code: 'blocked_data',
        primary_action: 'handoff',
      }),
    )
  })

  it('keeps handoff-only workflow status ahead of credit blocks', () => {
    const decision = deriveLaunchDecision({
      recipeLaunchStatus: 'handoff_only',
      checks: [
        {
          id: 'credits_sufficient',
          status: 'blocked',
          detail: 'Credit estimate unavailable.',
        },
      ],
    })

    expect(decision).toEqual(
      expect.objectContaining({
        status: 'handoff_only',
        code: 'handoff_only',
        can_launch: false,
        primary_action: 'handoff',
      }),
    )
    expect(decision.reason).toContain('local, Neurodesk, Slurm, or coding-agent')
    expect(decision.reason).toContain('instead of the hosted UI')
  })

  it('treats recipe handoff runtime guidance as handoff-only ahead of runtime blocks', () => {
    const decision = deriveLaunchDecision({
      recipeLaunchStatus: 'launchable',
      runtimeGuidance: {
        kind: 'recipe_handoff_required',
        summary: 'Hosted Studio cannot execute this container workflow directly.',
      },
      checks: [
        {
          id: 'runtime_executable',
          status: 'blocked',
          detail: 'Blocked by allowlist: run_fastsurfer',
        },
      ],
    })

    expect(decision).toEqual(
      expect.objectContaining({
        status: 'handoff_only',
        code: 'handoff_only',
        can_launch: false,
        primary_action: 'handoff',
        reason: 'Hosted Studio cannot execute this container workflow directly.',
      }),
    )
  })

  it('treats recipe-capable Neurodesk setup guidance as handoff-only', () => {
    const decision = deriveLaunchDecision({
      recipeLaunchStatus: 'launchable',
      runtimeGuidance: {
        kind: 'neurodesk_setup_required',
        summary: 'This workflow depends on a Neurodesk-backed runtime.',
        supported_recipe_targets: ['neurodesk', 'container', 'slurm'],
      },
      checks: [
        {
          id: 'runtime_executable',
          status: 'blocked',
          detail: 'Blocked by allowlist: run_bids_app',
        },
        {
          id: 'credits_sufficient',
          status: 'blocked',
          detail: 'Credit estimate unavailable for this launchable workflow.',
        },
      ],
    })

    expect(decision).toEqual(
      expect.objectContaining({
        status: 'handoff_only',
        code: 'handoff_only',
        can_launch: false,
        primary_action: 'handoff',
        reason: 'This workflow depends on a Neurodesk-backed runtime.',
      }),
    )
  })
})
