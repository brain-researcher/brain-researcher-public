// @vitest-environment jsdom
import '@testing-library/jest-dom/vitest'
import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { act } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { AutoresearchExperience } from '../autoresearch-experience'

const replace = vi.fn()

vi.mock('next/navigation', () => ({
  usePathname: () => '/autoresearch',
  useRouter: () => ({ replace }),
  useSearchParams: () => new URLSearchParams(window.location.search),
}))

describe('<AutoresearchExperience>', () => {
  beforeEach(() => {
    replace.mockReset()
    window.history.replaceState({}, '', '/autoresearch')
    vi.spyOn(HTMLElement.prototype, 'scrollIntoView').mockImplementation(() => {})
  })

  afterEach(() => {
    cleanup()
    vi.restoreAllMocks()
  })

  it('switches programs by keyboard and reflects the selection in the URL state', async () => {
    const user = userEvent.setup()
    render(<AutoresearchExperience />)

    await act(async () => {
      screen.getByRole('tab', { name: 'Neuroimaging' }).focus()
      await user.keyboard('{ArrowRight}')
    })

    expect(screen.getByRole('heading', { name: 'BCI and neural interfaces' })).toBeInTheDocument()
    expect(replace).toHaveBeenCalledWith(
      expect.stringMatching(/^\/autoresearch\?program=bci&direction=/),
      { scroll: false },
    )
  })

  it('hydrates a program, direction, and topic from a topic-based deep link', () => {
    window.history.replaceState(
      {},
      '',
      '/autoresearch?program=neuroimaging&direction=open-infrastructure&topic=alzheimer%20disease',
    )

    render(<AutoresearchExperience />)

    expect(
      screen.getByRole('heading', { name: 'Open data, standards and reusable pipelines' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Alzheimer disease' })).toBeInTheDocument()
  })

  it('searches topics, exposes source context, and prefills the proposal form', async () => {
    const user = userEvent.setup()
    render(<AutoresearchExperience />)

    const search = screen.getByRole('searchbox', { name: 'Search the source index' })
    await act(async () => {
      await user.type(search, 'Alzheimer disease')
    })
    await act(async () => {
      await user.click(screen.getByRole('button', { name: 'Alzheimer disease' }))
    })

    expect(screen.getByRole('heading', { name: 'Alzheimer disease' })).toBeInTheDocument()
    await act(async () => {
      await user.click(screen.getByRole('button', { name: 'See source' }))
    })
    expect(screen.getByText('Original source lead')).toBeInTheDocument()

    const questionButton = screen.getByRole('button', {
      name: /Use starting question: Does vascular risk improve prediction/i,
    })
    await act(async () => {
      await user.click(questionButton)
    })

    expect(screen.getByLabelText('Scientific question')).toHaveValue(
      'Does vascular risk improve prediction of cognitive decline or Alzheimer conversion beyond age, education, and APOE4?',
    )
    expect(screen.getByLabelText('Research area')).toHaveValue('Neuroimaging and brain measurement')
    expect(HTMLElement.prototype.scrollIntoView).toHaveBeenCalled()
  })

  it('does not expose a fake submission state when no approved destination is configured', () => {
    render(<AutoresearchExperience />)

    expect(screen.getByRole('button', { name: 'Submission unavailable' })).toBeDisabled()
    expect(screen.getByRole('status')).toHaveTextContent('does not send or store your information')
    expect(screen.queryByText(/proposal submitted/i)).not.toBeInTheDocument()
  })

  it('exposes the configured form-encoded POST destination without inventing a success state', () => {
    const { container } = render(
      <AutoresearchExperience proposalDestination="https://forms.example.org/autoresearch" />,
    )

    const form = container.querySelector('form')
    expect(form).toHaveAttribute('action', 'https://forms.example.org/autoresearch')
    expect(form).toHaveAttribute('method', 'post')
    expect(screen.getByRole('button', { name: 'Submit proposal' })).toBeEnabled()
    expect(screen.getByRole('status')).toHaveTextContent('configured external destination')
    expect(screen.queryByText(/proposal submitted/i)).not.toBeInTheDocument()
  })
})
