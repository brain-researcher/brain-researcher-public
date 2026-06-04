// @vitest-environment jsdom
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { McpConfigurationPanel } from '../mcp-configuration-panel'
import { McpSetupGuide } from '../mcp-setup-guide'

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { id: 'u1' } }, status: 'authenticated' }),
}))

vi.mock('@/hooks/use-toast', () => ({
  useToast: () => ({ toast: vi.fn() }),
}))

vi.mock('@/hooks/use-auth', () => ({
  useAuth: () => ({
    isAuthenticated: true,
    isLoading: false,
  }),
}))

describe('McpConfigurationPanel', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input)
        const payload = url.includes('/verify')
          ? { backend: 'redis', redis_available: true, pepper_configured: true }
          : { tokens: [] }
        return new Response(JSON.stringify(payload), {
          status: 200,
          headers: { 'content-type': 'application/json' },
        })
      }),
    )
  })

  it('renders plan-aware continuation details when plan context is provided', () => {
    render(
      <McpConfigurationPanel
        planId="plan_123"
        threadId="thread_abc"
        workflowLabel="Connectivity · Schaefer-200"
        datasetId="ds000224"
        continuationPrompt='Continue from Brain Researcher plan plan_123 for thread "thread_abc".'
      />,
    )

    expect(screen.getByText(/Continue from current Studio plan/i)).toBeInTheDocument()
    expect(screen.getByText('plan_123')).toBeInTheDocument()
    expect(screen.getByText('thread_abc')).toBeInTheDocument()
    expect(screen.getByText('Connectivity · Schaefer-200')).toBeInTheDocument()
    expect(screen.getByText('ds000224')).toBeInTheDocument()
    expect(
      screen.getByText(/Continue from Brain Researcher plan plan_123/i),
    ).toBeInTheDocument()
  })

  it('renders KG-only continuation prompts without plan context', () => {
    render(
      <McpConfigurationPanel
        continuationPrompt={
          'Continue from this Brain Researcher KG search handoff. Use BR MCP KG tools first for query "default mode network". Start with kg_search_nodes.'
        }
      />,
    )

    expect(screen.getByText(/Continue in MCP/i)).toBeInTheDocument()
    expect(screen.queryByText(/Plan ID:/i)).not.toBeInTheDocument()
    expect(screen.getByText(/default mode network/i)).toBeInTheDocument()
    expect(screen.getByText(/kg_search_nodes/i)).toBeInTheDocument()
  })

  it('uses the workflow id for generated MCP recipe calls', () => {
    render(
      <McpConfigurationPanel
        workflowId="workflow_rest_connectome_e2e"
        workflowLabel="Connectivity · Schaefer-200"
        datasetId="ds000114"
      />,
    )

    expect(screen.getByText('Connectivity · Schaefer-200')).toBeInTheDocument()
    expect(screen.getByText(/tool_id="workflow_rest_connectome_e2e"/)).toBeInTheDocument()
    expect(screen.getByText(/params=\{"dataset_id": "ds000114"\}/)).toBeInTheDocument()
    expect(screen.queryByText(/tool_id="Connectivity · Schaefer-200"/)).not.toBeInTheDocument()
  })

  it('renders the MCP setup guide steps, handoff prompt, and reference', () => {
    render(<McpSetupGuide />)

    expect(screen.getByText('Verify the connection')).toBeInTheDocument()
    expect(screen.getByText('Run a workflow handoff')).toBeInTheDocument()
    expect(screen.getAllByText(/server_info and system_self_test tools/i).length).toBeGreaterThan(0)
    expect(screen.getByText(/tool_id="workflow_rest_connectome_e2e"/)).toBeInTheDocument()
    expect(screen.getByText('Required first check')).toBeInTheDocument()
    expect(screen.getAllByText('get_execution_recipe').length).toBeGreaterThan(0)
    expect(screen.getByRole('link', { name: /Open starter repo/i })).toHaveAttribute(
      'href',
      'https://github.com/brain-researcher/brain-researcher-agent-kit',
    )
  })
})
