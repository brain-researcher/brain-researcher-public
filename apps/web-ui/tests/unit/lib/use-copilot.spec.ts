// @vitest-environment jsdom
import { renderHook, act, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const copilotSuggestMock = vi.fn()
const chatMock = vi.fn()

vi.mock('@/lib/brain-researcher-api', () => ({
  brainResearcherAPI: {
    copilotSuggest: (...args: any[]) => copilotSuggestMock(...args),
    chat: (...args: any[]) => chatMock(...args),
  },
}))

import { useCopilot } from '@/hooks/use-copilot'

describe('useCopilot backend-first behavior', () => {
  beforeEach(() => {
    copilotSuggestMock.mockReset()
    chatMock.mockReset()
  })

  it('loads backend params and methods when panel opens', async () => {
    copilotSuggestMock.mockResolvedValue({
      suggestions: [
        {
          name: 'smoothing_fwhm',
          description: 'Spatial smoothing kernel',
          reason: 'Common pre-statistics denoising',
          score: 2.2,
          autocomplete: { smoothing_fwhm: 6 },
        },
      ],
      methods: [
        {
          id: 'intent-glm-first',
          intent_id: 'glm_first_level_fmri',
          name: 'First-level GLM (task fMRI)',
          description: 'Single-subject GLM for task fMRI',
          reason: 'Matched intent catalog entry',
          score: 2.6,
          parameters: [{ name: 'hrf_model', value: 'spm' }],
        },
      ],
    })

    const { result } = renderHook(() => useCopilot())

    act(() => {
      result.current.toggleCopilot()
    })

    await waitFor(() => {
      expect(copilotSuggestMock).toHaveBeenCalledTimes(1)
    })

    await waitFor(() => {
      expect(result.current.suggestions.length).toBeGreaterThan(0)
      expect(result.current.recommendations.length).toBeGreaterThan(0)
    })

    expect(result.current.suggestions[0]?.source).toBe('backend')
    expect(result.current.recommendations[0]?.id).toBe('intent-glm-first')
    expect(result.current.recommendations[0]?.name).toContain('GLM')
  })

  it('uses backend chat + methods on sendMessage without local placeholder fallback', async () => {
    copilotSuggestMock.mockResolvedValue({
      suggestions: [
        {
          name: 'parcellation',
          description: 'Atlas for region definition',
          reason: 'Connectivity requires ROIs',
          score: 2.4,
          autocomplete: { parcellation: 'Schaefer2018_200' },
        },
      ],
      methods: [
        {
          id: 'intent-connectivity',
          intent_id: 'connectivity_matrix_fmri',
          name: 'Functional connectivity matrix (fMRI)',
          description: 'Compute FC matrix from ROI timeseries',
          reason: 'Matched intent catalog entry',
          score: 2.5,
          parameters: [{ name: 'bandpass_filter', value: '0.01-0.1' }],
        },
      ],
    })
    chatMock.mockResolvedValue('Backend chat response.')

    const { result } = renderHook(() => useCopilot())

    await act(async () => {
      await result.current.sendMessage('run connectivity analysis')
    })

    await waitFor(() => {
      expect(chatMock).toHaveBeenCalledWith('run connectivity analysis', { copilot: true })
      expect(result.current.messages.length).toBe(2)
    })

    const copilotMessage = result.current.messages[1]
    expect(copilotMessage.type).toBe('copilot')
    expect(copilotMessage.content).toBe('Backend chat response.')
    expect(copilotMessage.suggestions?.[0]?.source).toBe('backend')
    expect(copilotMessage.recommendations?.[0]?.id).toBe('intent-connectivity')
    expect(copilotMessage.content).not.toContain("I'm here to help with your neuroimaging analysis")
  })

  it('post-processes internal reasoning style chat into user-facing text', async () => {
    copilotSuggestMock.mockResolvedValue({ suggestions: [], methods: [] })
    chatMock.mockResolvedValue(
      "The user said 'hi', which is a greeting. No specialized neuroimaging tool is needed for this interaction. I should respond with a friendly greeting.",
    )

    const { result } = renderHook(() => useCopilot())

    await act(async () => {
      await result.current.sendMessage('hi')
    })

    await waitFor(() => {
      expect(result.current.messages.length).toBe(2)
    })

    const copilotMessage = result.current.messages[1]
    expect(copilotMessage.type).toBe('copilot')
    expect(copilotMessage.content).toBe(
      'Hi! How can I help with your neuroimaging analysis today?',
    )
    expect(copilotMessage.content).not.toContain('The user said')
    expect(copilotMessage.content).not.toContain('I should')
  })

  it('reports backend errors instead of falling back to local copilot text', async () => {
    copilotSuggestMock.mockRejectedValue(new Error('suggest down'))
    chatMock.mockRejectedValue(new Error('chat down'))

    const { result } = renderHook(() => useCopilot())

    await act(async () => {
      await result.current.sendMessage('hi')
    })

    await waitFor(() => {
      expect(result.current.messages.length).toBe(2)
    })

    const copilotMessage = result.current.messages[1]
    expect(copilotMessage.type).toBe('copilot')
    expect(copilotMessage.content).toContain('Copilot backend unavailable: chat down')
    expect(copilotMessage.content).toContain(
      '(Params/Methods backend unavailable: suggest down)',
    )
    expect(copilotMessage.content).not.toContain("I'm here to help with your neuroimaging analysis")
  })
})
