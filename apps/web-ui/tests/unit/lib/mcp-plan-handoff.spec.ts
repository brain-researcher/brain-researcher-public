import { describe, expect, it } from 'vitest'

import { buildLatestPlanContinuationPrompt } from '@/lib/mcp-plan-handoff'

describe('buildLatestPlanContinuationPrompt', () => {
  it('uses plan id and thread id when both are available', () => {
    const prompt = buildLatestPlanContinuationPrompt({
      planId: 'plan_123',
      threadId: 'thread_abc',
    })

    expect(prompt).toContain('Brain Researcher plan plan_123')
    expect(prompt).toContain('thread "thread_abc"')
    expect(prompt).toContain('get_latest_plan(thread_id="thread_abc")')
  })

  it('falls back to thread-scoped latest-plan lookup when plan id is missing', () => {
    const prompt = buildLatestPlanContinuationPrompt({
      threadId: 'thread_only',
    })

    expect(prompt).toContain('Continue from my Brain Researcher plan')
    expect(prompt).toContain('get_latest_plan(thread_id="thread_only")')
  })

  it('builds a workflow handoff prompt when only workflow context is available', () => {
    const prompt = buildLatestPlanContinuationPrompt({
      workflowLabel: 'workflow_rest_connectome_e2e',
      datasetId: 'ds000114',
      datasetVersion: '1.0.1',
    })

    expect(prompt).toContain('Brain Researcher workflow handoff')
    expect(prompt).toContain('workflow "workflow_rest_connectome_e2e"')
    expect(prompt).toContain('dataset "ds000114:1.0.1"')
    expect(prompt).toContain('fetch the execution recipe')
    expect(prompt).toContain('get_execution_recipe(')
    expect(prompt).toContain('tool_id="workflow_rest_connectome_e2e"')
    expect(prompt).toContain('target_runtime="python"')
    expect(prompt).toContain('params={"dataset_id": "ds000114"}')
  })

  it('uses workflow id, not human label, for recipe lookup calls', () => {
    const prompt = buildLatestPlanContinuationPrompt({
      workflowId: 'workflow_rest_connectome_e2e',
      workflowLabel: 'Nilearn Connectivity',
      datasetId: 'ds000114',
    })

    expect(prompt).toContain('workflow "Nilearn Connectivity"')
    expect(prompt).toContain('tool_id="workflow_rest_connectome_e2e"')
    expect(prompt).toContain('params={"dataset_id": "ds000114"}')
    expect(prompt).not.toContain('tool_id="Nilearn Connectivity"')
  })

  it('prefers explicit workflow id over noncanonical handoff chosen tool', () => {
    const prompt = buildLatestPlanContinuationPrompt({
      workflowId: 'workflow_rest_connectome_e2e',
      workflowLabel: 'Nilearn Connectivity',
      datasetId: 'ds000114',
      handoffPack: {
        chosen_tool: 'Nilearn Connectivity',
      },
    })

    expect(prompt).toContain('tool_id="workflow_rest_connectome_e2e"')
    expect(prompt).not.toContain('tool_id="Nilearn Connectivity"')
  })

  it('mentions the MCP handoff pack contract when one is provided', () => {
    const prompt = buildLatestPlanContinuationPrompt({
      handoffPack: {
        schema_version: 'br-plan-handoff-v1',
        workflow_id: 'workflow_rest_connectome_e2e',
        dataset_ref: 'ds:openneuro:ds000114',
        execution: { target_runtime: 'python' },
      },
    })

    expect(prompt).toContain('br-plan-handoff-v1 pack')
    expect(prompt).toContain('workflow_id=workflow_rest_connectome_e2e')
    expect(prompt).toContain('target_runtime=python')
    expect(prompt).toContain('dataset "ds:openneuro:ds000114"')
    expect(prompt).toContain('params={"dataset_id": "ds000114"}')
  })

  it('normalizes unsupported coding-agent names away from MCP runtime targets', () => {
    const prompt = buildLatestPlanContinuationPrompt({
      handoffPack: {
        schema_version: 'br-plan-handoff-v1',
        workflow_id: 'workflow_rest_connectome_e2e',
        dataset_ref: 'ds:openneuro:ds000114',
        execution: {
          target_runtime: 'codex',
          supported_recipe_targets: ['python'],
        },
      },
    })

    expect(prompt).toContain('target_runtime=python')
    expect(prompt).toContain('target_runtime="python"')
    expect(prompt).not.toContain('target_runtime=codex')
    expect(prompt).not.toContain('target_runtime="codex"')
  })
})
