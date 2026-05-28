// @vitest-environment jsdom
import { render, screen, fireEvent } from '@testing-library/react'
import { vi } from 'vitest'
import { ChatWorkspace } from '../chat-workspace'

// Mocks
const submitPrompt = vi.fn()
const cancelExecution = vi.fn()
const useChatMock = vi.fn()

function makeUseChatState(overrides: Record<string, any> = {}) {
  return {
    messages: [
      {
        id: 'a1',
        type: 'assistant',
        content: 'done',
        timestamp: new Date(),
        lastCheckpointId: 'ck-abc',
      },
    ],
    isLoading: false,
    submitPrompt,
    cancelExecution,
    replaceMessages: vi.fn(),
    setCodingMode: vi.fn(),
    connectionState: 'connected',
    resetConnectionState: vi.fn(),
    ...overrides,
  }
}

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: null, status: 'unauthenticated' }),
}))

vi.mock('@/hooks/use-chat', () => ({
  useChat: () => useChatMock(),
}))

vi.mock('@/hooks/use-copilot', () => ({ useCopilot: () => ({ toggleCopilot: vi.fn() }) }))
vi.mock('@/hooks/use-aria-live', () => ({ useAriaLive: () => ({ announceLoading: vi.fn(), announceComplete: vi.fn(), announceError: vi.fn() }) }))
vi.mock('@/hooks/use-toast', () => ({ useToast: () => ({ toast: vi.fn() }) }))
vi.mock('@/lib/websocket-manager', () => ({ useWebSocket: () => ({ isConnected: false, disconnect: vi.fn() }) }))
vi.mock('@/lib/service-endpoints', () => ({
  serviceEndpoints: {
    useProxy: true,
    orchestrator: (path: string) => path,
    orchestratorApi: (path: string) => path,
    agent: (path: string) => path,
    kg: (path: string) => path,
  },
}))
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))

describe('ChatWorkspace resume checkpoint', () => {
  beforeEach(() => {
    submitPrompt.mockReset()
    useChatMock.mockReset()
    useChatMock.mockReturnValue(makeUseChatState())
  })

  it('passes resumeCheckpointId from Resume button into submitPrompt on send', () => {
    render(<ChatWorkspace />)

    // Click Resume on the assistant message
    const resumeButton = screen.getByTestId('resume-from-checkpoint')
    fireEvent.click(resumeButton)

    // Type a new prompt and send
    const textarea = screen.getByPlaceholderText(/ask a question/i)
    fireEvent.change(textarea, { target: { value: 'new question' } })
    const send = screen.getByTestId('chat-send-button')
    fireEvent.click(send)

    expect(submitPrompt).toHaveBeenCalled()
    const call = submitPrompt.mock.calls.at(-1) as any
    expect(call?.[2]?.resumeCheckpointId).toBe('ck-abc')
  })

  it('auto-resumes from assistant lastCheckpointId on the next send', () => {
    useChatMock.mockReturnValue(
      makeUseChatState({
        messages: [
          {
            id: 'a2',
            type: 'assistant',
            content: 'clarification needed',
            timestamp: new Date(),
            lastCheckpointId: 'ck-meta-123',
          },
        ],
      }),
    )

    render(<ChatWorkspace />)

    const textarea = screen.getByPlaceholderText(/ask a question/i)
    fireEvent.change(textarea, { target: { value: 'use local nilearn' } })
    const send = screen.getByTestId('chat-send-button')
    fireEvent.click(send)

    expect(submitPrompt).toHaveBeenCalled()
    const call = submitPrompt.mock.calls.at(-1) as any
    expect(call?.[2]?.resumeCheckpointId).toBe('ck-meta-123')
  })
})
