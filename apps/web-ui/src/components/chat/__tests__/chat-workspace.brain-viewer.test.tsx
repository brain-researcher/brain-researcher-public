// @vitest-environment jsdom
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const {
  submitPrompt,
  cancelExecution,
  routerPush,
  routerReplace,
  fetchWorkflowGraph,
  fetchBrainMaps,
  mockedRunCard,
} = vi.hoisted(() => ({
  submitPrompt: vi.fn(),
  cancelExecution: vi.fn(),
  routerPush: vi.fn(),
  routerReplace: vi.fn(),
  fetchWorkflowGraph: vi.fn(async () => null),
  fetchBrainMaps: vi.fn(async () => []),
  mockedRunCard: {
    id: 'analysis-123',
    outputs: {
      artifacts: [
        {
          name: 'zstat_map.nii.gz',
          url: '/artifacts/analysis-123/zstat_map.nii.gz',
          type: 'brain_map',
        },
      ],
    },
  },
}))

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: null, status: 'unauthenticated' }),
  getSession: vi.fn(async () => null),
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: routerPush, replace: routerReplace }),
  useSearchParams: () => new URLSearchParams(),
}))

vi.mock('@/hooks/use-chat', () => ({
  useChat: () => ({
    messages: [],
    isLoading: false,
    submitPrompt,
    cancelExecution,
    replaceMessages: vi.fn(),
    addMessage: vi.fn(),
    setCodingMode: vi.fn(),
    threadId: null,
    connectionState: 'connected',
    resetConnectionState: vi.fn(),
  }),
}))

vi.mock('@/hooks/use-copilot', () => ({ useCopilot: () => ({ toggleCopilot: vi.fn() }) }))
vi.mock('@/hooks/use-aria-live', () => ({
  useAriaLive: () => ({
    announceLoading: vi.fn(),
    announceComplete: vi.fn(),
    announceError: vi.fn(),
  }),
}))
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }))
vi.mock('@/hooks/use-advanced-mode', () => ({
  useAdvancedMode: () => ({ enabled: false, hydrated: true }),
}))
vi.mock('@/lib/websocket-manager', () => ({
  useWebSocket: () => ({ isConnected: false, disconnect: vi.fn() }),
}))
vi.mock('@/hooks/use-run-card', () => ({
  useRunCard: () => ({
    runCard: undefined,
    isLoading: false,
    error: null,
    refetch: vi.fn(),
    clear: vi.fn(),
  }),
  invalidateRunCardCache: vi.fn(),
}))
vi.mock('@/lib/visualizations', () => ({
  fetchWorkflowGraph,
  fetchBrainMaps,
}))
vi.mock('@/lib/service-endpoints', () => ({
  serviceEndpoints: {
    useProxy: true,
    orchestrator: (path: string) => path,
    orchestratorApi: (path: string) => path,
    agent: (path: string) => path,
    kg: (path: string) => path,
  },
}))
vi.mock('@/lib/api', () => ({
  openSSE: () => ({
    addEventListener: vi.fn(),
    close: vi.fn(),
    onmessage: null,
    onerror: null,
  }),
}))

vi.mock('@/components/brain/Brain3D', () => ({
  Brain3D: (props: any) => (
    <div
      data-testid="brain3d"
      data-job-id={props.jobId ?? ''}
      data-base-volume={props.config?.baseVolume ?? ''}
      data-preferred-overlay-name={props.preferredOverlayName ?? ''}
    />
  ),
}))

vi.mock('../evidence-rail', async () => {
  const React = await import('react')
  return {
    EvidenceRail: ({ onEvidenceDataChange }: any) => {
      React.useEffect(() => {
        onEvidenceDataChange?.({ mappedRunCard: mockedRunCard })
      }, [onEvidenceDataChange])
      return <div data-testid="evidence-rail" />
    },
  }
})
vi.mock('../diagnosis-card', () => ({
  DiagnosisCard: () => <div data-testid="diagnosis-card" />,
}))
vi.mock('../attempt-switcher', () => ({
  AttemptSwitcher: () => null,
}))
vi.mock('../studio-plan-panel', () => ({
  StudioPlanPanel: () => <div data-testid="studio-plan-panel" />,
}))
vi.mock('@/components/visualization/visualization-panel', () => ({
  VisualizationPanel: () => <div data-testid="visualization-panel" />,
}))
vi.mock('@/components/copilot/copilot-panel', () => ({
  CopilotPanel: () => null,
}))
vi.mock('@/components/share/share-modal', () => ({
  ShareModal: () => null,
}))
vi.mock('@/components/mcp/mcp-configuration-modal', () => ({
  McpConfigurationModal: () => null,
}))
vi.mock('@/components/landing/StepsList', () => ({
  StepsList: () => null,
}))
vi.mock('@/components/progress/analysis-stream-events-panel', () => ({
  AnalysisStreamEventsPanel: () => null,
}))
vi.mock('@/components/ui/real-time-progress', () => ({
  RealTimeProgress: () => null,
}))
vi.mock('@/components/workspace/workspace-switcher', () => ({
  WorkspaceSwitcher: () => null,
}))

describe('ChatWorkspace brain viewer', () => {
  const originalFetch = global.fetch

  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubEnv('NEXT_PUBLIC_ENABLE_STUDIO_BRAIN_VIEWER_BETA', '1')
  })

  afterEach(() => {
    global.fetch = originalFetch
    vi.unstubAllEnvs()
  })

  it('auto-opens the Studio viewer on the Charts tab using the analysis job-backed path', async () => {
    const { ChatWorkspace } = await import('../chat-workspace')

    global.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/api/analyses/analysis-123')) {
        return {
          ok: true,
          json: async () => ({
            analysis_id: 'analysis-123',
            status: 'completed',
            artifacts: [
              {
                name: 'zstat_map.nii.gz',
                url: '/artifacts/analysis-123/zstat_map.nii.gz',
                type: 'brain_map',
              },
            ],
          }),
        } as Response
      }
      throw new Error(`Unexpected fetch: ${url}`)
    }) as typeof global.fetch

    render(<ChatWorkspace analysisId="analysis-123" />)

    await waitFor(() => {
      const viewer = screen.getByTestId('brain3d')
      expect(viewer).toHaveAttribute('data-job-id', 'analysis-123')
      expect(viewer).toHaveAttribute('data-base-volume', '')
      expect(viewer).toHaveAttribute('data-preferred-overlay-name', 'zstat_map.nii.gz')
    })
  })
})
