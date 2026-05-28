import React from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import type { WorkflowDetail } from '@/lib/api/workflows'
import { LibraryWorkflowRunner } from '@/components/workflow/LibraryWorkflowRunner'

const pushMock = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: pushMock,
  }),
}))

const WORKFLOW: WorkflowDetail = {
  id: 'workflow_preprocessing_qc',
  stage: 'preprocessing',
  cost_tier: 'expensive',
  description: 'Preprocessing QC workflow',
  impl: 'workflow: validate -> run_bids_app',
  modalities: ['fmri'],
  supported_recipe_targets: ['neurodesk', 'container', 'slurm'],
  primary_target: 'neurodesk',
  execution_recipe_available: true,
  runtime: {
    kind: 'declarative_workflow',
    steps: [
      {
        id: 'validate',
        tool: 'validate_bids_structure',
        params: {},
      },
    ],
  },
  params: {
    schema: {
      type: 'object',
      properties: {},
      required: [],
    },
    defaults: {},
  },
}

describe('<LibraryWorkflowRunner>', () => {
  beforeEach(() => {
    pushMock.mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
    cleanup()
  })

  it('renders Neurodesk setup guidance from workflow preflight', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            workflow_id: WORKFLOW.id,
            direct_run_enabled: true,
            schema_source: 'catalog',
            schema: {
              type: 'object',
              properties: {},
              required: [],
            },
            defaults: {
              schema_property_defaults: {},
              workflow_defaults: {},
              merged: {},
            },
            discovered_inputs: [],
            missing_contract_fields: [],
          }),
          {
            status: 200,
            headers: { 'content-type': 'application/json' },
          },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            error: {
              code: 'WF_PREFLIGHT_FAILED',
              message: 'This workflow cannot run in the current environment.',
              details: {
                checks: [{ tool_id: 'run_bids_app', status: 'missing', available: false }],
                warnings: ['Runtime tool inventory unavailable: timeout'],
                guidance: {
                  kind: 'neurodesk_setup_required',
                  runtime_target: 'neurodesk',
                  install_path: 'app',
                  summary: 'This workflow depends on a Neurodesk-backed runtime.',
                  detail: 'Expected Neurodesk modules: fmriprep/23.2.3, mriqc/24.0.2',
                  next_action_url: 'https://neurodesk.org/getting-started/local/neurodeskapp/',
                  required_modules: ['fmriprep/23.2.3', 'mriqc/24.0.2'],
                  required_env_vars: ['FS_LICENSE'],
                  actions: [
                    {
                      id: 'neurodesk-play',
                      label: 'Try Neurodesk Play',
                      href: 'https://play.neurodesk.org/',
                    },
                  ],
                },
              },
            },
          }),
          {
            status: 409,
            headers: { 'content-type': 'application/json' },
          },
        ),
      )

    render(<LibraryWorkflowRunner workflow={WORKFLOW} />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Preview checks' })).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: 'Run via MCP in Codex/Cursor' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Run via MCP in Codex/Cursor' }))
    expect(pushMock).toHaveBeenCalledWith(
      '/settings?tab=integrations&handoff=coding-agent&workflowId=workflow_preprocessing_qc&workflowLabel=workflow_preprocessing_qc',
    )

    fireEvent.click(screen.getByRole('button', { name: 'Preview checks' }))

    await waitFor(() => {
      expect(screen.getByText('Neurodesk setup')).toBeInTheDocument()
    })
    expect(screen.getByText('This workflow depends on a Neurodesk-backed runtime.')).toBeInTheDocument()
    expect(screen.getByText('Open in Neurodesk Play')).toBeInTheDocument()
    expect(screen.getByText('Re-check environment')).toBeInTheDocument()
    expect(screen.getByText('FS_LICENSE')).toBeInTheDocument()
    expect(screen.getByText(/Long-running workflows can take tens of minutes to hours/)).toBeInTheDocument()
  })

  it('renders recipe handoff guidance for long local/container workflows', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
    fetchMock
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            workflow_id: 'workflow_fastsurfer',
            direct_run_enabled: true,
            schema_source: 'catalog',
            schema: {
              type: 'object',
              properties: {},
              required: [],
            },
            defaults: {
              schema_property_defaults: {},
              workflow_defaults: {},
              merged: {},
            },
            discovered_inputs: [],
            missing_contract_fields: [],
          }),
          {
            status: 200,
            headers: { 'content-type': 'application/json' },
          },
        ),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            error: {
              code: 'WF_PREFLIGHT_FAILED',
              message: 'This workflow is available as a recipe handoff.',
              details: {
                checks: [{ tool_id: 'workflow_fastsurfer', status: 'missing', available: false }],
                warnings: ['Container runtime is not available in the hosted UI.'],
                guidance: {
                  kind: 'recipe_handoff_required',
                  runtime_target: 'container',
                  summary: 'Run this workflow locally or in a coding agent.',
                  detail: 'Use the generated recipe with a mounted BIDS dataset and FS_LICENSE.',
                  required_env_vars: ['FS_LICENSE'],
                  supported_recipe_targets: ['container'],
                  container_images: {
                    fastsurfer: 'deepmi/fastsurfer:latest',
                  },
                },
              },
            },
          }),
          {
            status: 409,
            headers: { 'content-type': 'application/json' },
          },
        ),
      )

    render(
      <LibraryWorkflowRunner
        workflow={{
          ...WORKFLOW,
          id: 'workflow_fastsurfer',
          supported_recipe_targets: ['container'],
          primary_target: 'container',
          execution_recipe_available: true,
        }}
      />,
    )

    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Preview checks' })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: 'Preview checks' }))

    await waitFor(() => {
      expect(screen.getByText('Recipe handoff')).toBeInTheDocument()
    })
    expect(screen.getByText('Run this workflow locally or in a coding agent.')).toBeInTheDocument()
    expect(screen.getByText(/Long-running workflows can take tens of minutes to hours/)).toBeInTheDocument()
    expect(screen.getAllByText('container').length).toBeGreaterThan(0)
    expect(screen.getByText('deepmi/fastsurfer:latest')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Run via MCP in Codex/Cursor' })).toBeInTheDocument()
  })
})
